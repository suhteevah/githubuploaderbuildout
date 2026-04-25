"""
secret_scanner.py — Pre-push secret scan for github-uploader-buildout.

Scans the git index (files about to be committed + pushed) for high-confidence
secret patterns. Aborts the push if any real secret is found, printing the file
and line so the operator can redact or gitignore before retrying.

This is the fix for the "initial commit uploaded via github-uploader-buildout"
leaks seen in 2026-02 (Stripe sk_live in clawhub-skill-repo) and 2026-04
(Telegram bot token in claudio-os, RunPod + VoxClaw Gateway tokens in claudeai).

The scanner only checks tracked files so repo-level gitignores are respected;
it is a defense-in-depth layer *after* the gitignore filter.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("uploader.secret_scanner")


# High-confidence secret patterns. Each tuple = (name, compiled regex).
# These are vendor-specific formats with enough entropy that a false positive
# is rare. Everything blocks the push.
_PATTERNS = [
    # Stripe live secret
    ("Stripe live secret key",
     re.compile(r"sk_live_[A-Za-z0-9]{24,}")),
    # Stripe restricted live (also money-moving)
    ("Stripe restricted live key",
     re.compile(r"rk_live_[A-Za-z0-9]{24,}")),
    # AWS access key
    ("AWS access key",
     re.compile(r"AKIA[0-9A-Z]{16}")),
    # AWS secret access key (context: AWS_SECRET_ACCESS_KEY = ...)
    ("AWS secret key (contextual)",
     re.compile(r"aws[_-]?secret[_-]?access[_-]?key[\"'\s:=]+[A-Za-z0-9/+=]{40}", re.IGNORECASE)),
    # GitHub PAT (fine-grained or classic)
    ("GitHub personal access token",
     re.compile(r"\bghp_[A-Za-z0-9]{36,}\b")),
    ("GitHub server-to-server token",
     re.compile(r"\bghs_[A-Za-z0-9]{36,}\b")),
    ("GitHub user-to-server token",
     re.compile(r"\bgho_[A-Za-z0-9]{36,}\b")),
    # Google API key
    ("Google API key",
     re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # Slack bot / app / user tokens
    ("Slack token",
     re.compile(r"\bxox[baprs]-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24,}\b")),
    # Telegram bot token
    ("Telegram bot token",
     re.compile(r"\b[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}\b")),
    # RunPod API key
    ("RunPod API key",
     re.compile(r"\brpa_[A-Za-z0-9]{24,}\b")),
    # OpenAI legacy keys
    ("OpenAI secret key",
     re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    # Anthropic API keys
    ("Anthropic API key",
     re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b")),
    # PEM-encoded private keys (SSH, RSA, EC, OpenSSH)
    ("Private key block",
     re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
    # Discord bot token
    ("Discord bot token",
     re.compile(r"\b[MN][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,}\b")),
    # Twilio account SID + auth (contextual)
    ("Twilio auth token (contextual)",
     re.compile(r"twilio[_-]?auth[_-]?token[\"'\s:=]+[a-f0-9]{32}", re.IGNORECASE)),
    # SendGrid
    ("SendGrid API key",
     re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{30,}\b")),
    # Mailgun
    ("Mailgun key",
     re.compile(r"\bkey-[a-f0-9]{32}\b")),
    # Tailscale auth keys (pre-auth keys for joining the tailnet)
    # Added 2026-04-25 after kVHj9zhN... leaked through clawhub bulk upload.
    ("Tailscale auth key",
     re.compile(r"\btskey-(?:auth|api|client)-[A-Za-z0-9_-]{20,}\b")),
    # Anthropic OAuth tokens (Claude Max sessions). Different scope than
    # API keys — these grant Claude.ai/Code access bound to the user's plan.
    ("Anthropic OAuth token",
     re.compile(r"\bsk-ant-oat0[0-9]-[A-Za-z0-9_-]{40,}\b")),
]


# Filenames + patterns that commonly contain creds and are rarely intentional
# in a public repo. Soft block: warn + suggest gitignore, but still allow --force.
# These supplement the scanner — they trigger even if no regex hits.
_SUSPICIOUS_FILENAMES = {
    "secrets.md",
    "credentials.md",
    "private.md",
    "voxclaw.md",   # Matt-specific; this doc has been leaked before
    ".secrets",
    "creds.txt",
    "passwords.txt",
    # Common SSH private-key filenames (no extension — would not match *.key/*.pem).
    # Added 2026-04-25 after `satibook-key` (RSA private) leaked through bulk upload.
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    # Anthropic / Claude Code session credentials.
    ".credentials.json",
    "credentials.json",
    # Discord bot token holders.
    "discord-bot-token.secret",
    "discord_bot_token.secret",
}

# Filename patterns (regex) that block the push regardless of content.
# These catch the bulk-upload-of-home-dir bug where Windows absolute paths
# end up as repo files (the `:` gets Unicode-escaped to U+F03A).
_BLOCKED_PATH_PATTERNS = [
    # Windows absolute paths leaked into the repo as filenames.
    # The Unicode private-use char U+F03A (\xef\x80\xba in UTF-8) replaces `:`.
    ("Windows absolute path leaked as filename",
     re.compile(r"^C[\xef\x80\xba:]Users", re.IGNORECASE)),
    ("Windows system path leaked as filename",
     re.compile(r"^C[\xef\x80\xba:]Windows", re.IGNORECASE)),
    # No-extension key files at repo root (e.g. satibook-key, prod-key).
    ("Bare SSH key filename at repo root",
     re.compile(r"^[a-zA-Z0-9_-]+-key$")),
]


def _list_staged_files(project: Path) -> list[Path]:
    """Return the absolute paths of files currently staged in the index."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=str(project), capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(f"git diff --cached failed: {result.stderr.strip()}")
        return []
    paths = [p for p in result.stdout.split("\x00") if p]
    return [project / p for p in paths]


def _file_is_binaryish(path: Path) -> bool:
    """Cheap binary check — look for NUL bytes in first 8KB."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except Exception:
        return True  # treat unreadable as skippable


def _scan_file(path: Path, repo_root: Path) -> list[tuple[str, int, str]]:
    """Return list of (pattern_name, line_number, matched_snippet) for a file."""
    if _file_is_binaryish(path):
        return []
    rel = path.relative_to(repo_root)
    hits: list[tuple[str, int, str]] = []

    # Filename-based soft checks
    if path.name.lower() in _SUSPICIOUS_FILENAMES:
        hits.append((f"suspicious filename: {path.name}", 0,
                     f"{rel} — file name commonly contains credentials"))

    # Hard-block path patterns: bulk-upload-of-home-dir bug, bare SSH keys.
    rel_str = str(rel).replace("\\", "/")
    for blocked_name, blocked_pat in _BLOCKED_PATH_PATTERNS:
        # Check both the repo-relative path and just the filename.
        if blocked_pat.search(rel_str) or blocked_pat.search(path.name):
            hits.append((blocked_name, 0,
                         f"{rel} — path matches a known leak pattern"))
            break

    # Content scan
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                for name, pat in _PATTERNS:
                    m = pat.search(line)
                    if m:
                        snippet = line.strip()
                        if len(snippet) > 120:
                            idx = snippet.find(m.group(0))
                            start = max(0, idx - 30)
                            end = min(len(snippet), idx + len(m.group(0)) + 30)
                            snippet = "..." + snippet[start:end] + "..."
                        hits.append((name, i, snippet))
    except Exception as e:
        logger.debug(f"could not scan {rel}: {e}")
    return hits


def scan_staged(project: Path) -> tuple[bool, list[str]]:
    """Scan every staged file in `project` for secrets.

    Returns (clean, report_lines). `clean` is False if any secret was found.
    `report_lines` contains human-readable findings to print.
    """
    staged = _list_staged_files(project)
    logger.info(f"secret scan: {len(staged)} staged files")
    findings: list[str] = []
    for f in staged:
        if not f.exists():
            continue
        hits = _scan_file(f, project)
        for name, line_no, snippet in hits:
            rel = f.relative_to(project)
            loc = f"{rel}:{line_no}" if line_no else f"{rel}"
            findings.append(f"  [{name}] {loc}\n      {snippet}")
    return (len(findings) == 0, findings)


def format_report(findings: list[str]) -> str:
    """Render findings into a block that gets printed to stderr before abort."""
    header = (
        "\n" + "=" * 70 + "\n"
        "SECRET SCAN FAILED — push aborted.\n"
        "The following files contain patterns that look like live credentials.\n"
        "Redact them, add to .gitignore, or rotate and then delete before retrying.\n"
        + "=" * 70 + "\n"
    )
    body = "\n".join(findings)
    footer = (
        "\n" + "=" * 70 + "\n"
        "To force-push anyway (NOT recommended), re-run with --force-secrets\n"
        "(you should only do this for known false positives).\n"
        + "=" * 70 + "\n"
    )
    return header + body + footer


if __name__ == "__main__":
    # Standalone: scan the cwd
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    # Stage files first if the caller forgot
    subprocess.run(["git", "add", "-A"], cwd=str(project))
    clean, findings = scan_staged(project)
    if clean:
        print(f"clean: no secrets detected in staged files of {project}")
        sys.exit(0)
    print(format_report(findings), file=sys.stderr)
    sys.exit(1)
