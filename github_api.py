"""
github_api.py - GitHub API integration for creating repos and managing content.

Uses either:
- GitHub personal access token (for local use)
- gh CLI (if authenticated)
- git proxy (for CI/cloud environments)
"""

import json
import logging
import os
import subprocess
import sys
import traceback
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger("uploader.github_api")


class GitHubAPI:
    """Interact with GitHub API for repo management."""

    def __init__(self, token: str = None, username: str = None):
        """
        Initialize GitHub API client.

        Args:
            token: GitHub personal access token. If None, tries GH_TOKEN env var.
            username: GitHub username. If None, fetched from API.
        """
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "GitHub token required. Set GH_TOKEN environment variable or pass token directly.\n"
                "Create a token at: https://github.com/settings/tokens/new\n"
                "Required scopes: repo, delete_repo (optional)"
            )
        token_preview = self.token[:4] + "..." + self.token[-4:] if len(self.token) > 8 else "***"
        logger.info(f"Token loaded (preview: {token_preview}, length: {len(self.token)})")

        # Validate token format
        if not self.token.startswith(("ghp_", "gho_", "github_pat_")):
            logger.warning(
                f"Token does not start with a known prefix (ghp_, gho_, github_pat_). "
                f"Starts with: '{self.token[:4]}'. This may cause auth failures."
            )

        self.username = username or self._get_username()
        logger.info(f"Authenticated as: {self.username}")

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make an authenticated GitHub API request."""
        url = f"https://api.github.com{endpoint}"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "github-uploader-buildout",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8") if data else None

        # Log the request
        logger.debug(f">>> {method} {url}")
        safe_headers = {k: v for k, v in headers.items() if k != "Authorization"}
        safe_headers["Authorization"] = "token ***"
        logger.debug(f">>> Headers: {json.dumps(safe_headers)}")
        if body:
            logger.debug(f">>> Body: {body.decode('utf-8')}")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read().decode("utf-8")
                logger.debug(f"<<< {resp.status} {resp.reason}")
                logger.debug(f"<<< Response headers: {dict(resp.headers)}")
                if resp.status == 204:
                    logger.debug("<<< (no content)")
                    return {}
                parsed = json.loads(resp_body)
                # Truncate large responses in logs
                resp_preview = resp_body[:500] + "..." if len(resp_body) > 500 else resp_body
                logger.debug(f"<<< Body: {resp_preview}")
                return parsed
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            logger.error(f"<<< HTTP {e.code} {e.reason}")
            logger.error(f"<<< Response headers: {dict(e.headers)}")
            logger.error(f"<<< Error body: {error_body}")
            try:
                error_data = json.loads(error_body)
                msg = error_data.get("message", error_body)
                errors_list = error_data.get("errors", [])
                if errors_list:
                    logger.error(f"<<< API errors detail: {json.dumps(errors_list, indent=2)}")
                    msg += f" | Details: {json.dumps(errors_list)}"
                doc_url = error_data.get("documentation_url", "")
                if doc_url:
                    logger.error(f"<<< Docs: {doc_url}")
            except json.JSONDecodeError:
                msg = error_body
            raise RuntimeError(f"GitHub API error ({e.code}): {msg}") from e
        except urllib.error.URLError as e:
            logger.error(f"<<< URL Error: {e.reason}")
            logger.error(f"<<< This usually means a network/DNS/proxy issue.")
            raise RuntimeError(f"Network error connecting to GitHub API: {e.reason}") from e
        except Exception as e:
            logger.error(f"<<< Unexpected error: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            raise

    def _get_username(self) -> str:
        """Get the authenticated user's username."""
        logger.info("Fetching authenticated user info...")
        data = self._request("GET", "/user")
        username = data.get("login")
        if not username:
            logger.error(f"No 'login' field in /user response. Keys: {list(data.keys())}")
            raise RuntimeError("Could not determine username from GitHub API /user response")
        scopes = data.get("permissions", {})
        logger.info(f"User: {username}, Name: {data.get('name', 'N/A')}")
        return username

    def check_repo_create_permission(self) -> bool:
        """
        Test whether the token can create repos by checking scopes.

        For classic tokens, checks X-OAuth-Scopes header.
        For fine-grained tokens, attempts a validation request.

        Returns True if permitted, raises RuntimeError with guidance if not.
        """
        logger.info("Checking token permissions for repo creation...")
        # Make a lightweight request and inspect the OAuth scopes header
        url = "https://api.github.com/user"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "github-uploader-buildout",
        }
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        try:
            with urllib.request.urlopen(req) as resp:
                scopes = resp.headers.get("X-OAuth-Scopes", "")
                logger.info(f"Token scopes: '{scopes}'")

                # Classic tokens have X-OAuth-Scopes header
                if scopes:
                    scope_list = [s.strip() for s in scopes.split(",")]
                    if "repo" in scope_list or "public_repo" in scope_list:
                        logger.info("Token has repo creation scope (classic token).")
                        return True
                    else:
                        raise RuntimeError(
                            f"Your classic token is missing the 'repo' scope.\n"
                            f"  Current scopes: {scopes}\n"
                            f"  Go to https://github.com/settings/tokens and edit your token\n"
                            f"  to include the 'repo' scope (or 'public_repo' for public repos only)."
                        )

                # Fine-grained tokens don't have X-OAuth-Scopes.
                # We can't easily check permissions without trying, so do a dry-run.
                logger.info("No X-OAuth-Scopes header (likely a fine-grained token). "
                            "Will verify by attempting a test request.")
                return True

        except urllib.error.HTTPError as e:
            logger.error(f"Permission check failed: HTTP {e.code}")
            raise RuntimeError(f"Token permission check failed: HTTP {e.code}") from e

    def repo_exists(self, repo_name: str) -> bool:
        """Check if a repo already exists."""
        logger.info(f"Checking if repo exists: {self.username}/{repo_name}")
        try:
            self._request("GET", f"/repos/{self.username}/{repo_name}")
            logger.info(f"Repo '{repo_name}' exists.")
            return True
        except RuntimeError as e:
            if "404" in str(e):
                logger.info(f"Repo '{repo_name}' does not exist (404).")
                return False
            logger.error(f"Unexpected error checking repo existence: {e}")
            raise

    def create_repo(self, name: str, description: str = "", private: bool = False,
                    homepage: str = "") -> dict:
        """
        Create a new GitHub repository.

        Args:
            name: Repository name
            description: Short description
            private: Whether repo is private
            homepage: Homepage URL

        Returns:
            API response dict with repo info
        """
        logger.info(f"Creating repo: name='{name}', private={private}, desc='{description[:50]}'")
        data = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
        }
        if homepage:
            data["homepage"] = homepage
        result = self._request("POST", "/user/repos", data)
        logger.info(f"Repo created: {result.get('html_url', 'unknown URL')}")
        return result

    def update_repo(self, name: str, description: str = None, homepage: str = None) -> dict:
        """Update an existing repository's metadata."""
        data = {}
        if description is not None:
            data["description"] = description
        if homepage is not None:
            data["homepage"] = homepage
        if data:
            logger.info(f"Updating repo '{name}' with: {data}")
            return self._request("PATCH", f"/repos/{self.username}/{name}", data)
        return {}

    def list_repos(self) -> list[dict]:
        """List all repos for the authenticated user."""
        repos = []
        page = 1
        while True:
            logger.debug(f"Fetching repos page {page}...")
            data = self._request("GET", f"/user/repos?per_page=100&page={page}")
            if not data:
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
        logger.info(f"Found {len(repos)} repos total.")
        return repos


def git_init_and_push(
    project_path: str,
    remote_url: str,
    branch: str = "main",
    force: bool = False,
    force_secrets: bool = False,
) -> bool:
    """Init repo, commit, scan for secrets, push.

    Args:
        project_path:  Local path to the project
        remote_url:    GitHub repo URL (https)
        branch:        Branch name to push to
        force:         Pass --force to git push (overwrites remote — for history rewrites)
        force_secrets: Ignore secret-scanner findings and push anyway.
                       Default is to ABORT on any credential-pattern match.
                       Only use for known false positives.

    Returns:
        True if successful.
    """
    project = Path(project_path)
    logger.info(f"git_init_and_push: path='{project_path}', remote='{remote_url}', branch='{branch}'")

    def run_git(*args, **kwargs):
        cmd = ["git"] + list(args)
        logger.debug(f"  $ git {' '.join(args)}")
        result = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            **kwargs,
        )
        if result.stdout.strip():
            logger.debug(f"    stdout: {result.stdout.strip()[:500]}")
        if result.stderr.strip():
            level = logging.WARNING if result.returncode != 0 else logging.DEBUG
            logger.log(level, f"    stderr: {result.stderr.strip()[:500]}")
        if result.returncode != 0:
            logger.warning(f"    exit code: {result.returncode}")
        return result

    # Initialize if not a git repo
    if not (project / ".git").exists():
        logger.info(f"No .git found, initializing new repo")
        run_git("init")
        run_git("checkout", "-b", branch)
    else:
        logger.info(f".git exists, checking current branch")
        result = run_git("branch", "--show-current")
        current_branch = result.stdout.strip()
        logger.info(f"Current branch: '{current_branch}'")
        if current_branch and current_branch != branch:
            logger.info(f"Switching from '{current_branch}' to '{branch}'")
            run_git("checkout", "-b", branch)

    # Windows reserved device names that crash git add
    WINDOWS_RESERVED = [
        "nul", "con", "prn", "aux",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
        "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    ]
    RESERVED_GITIGNORE_BLOCK = (
        "\n# Windows reserved device names (cause git add failures)\n"
        + "\n".join(WINDOWS_RESERVED)
        + "\n"
    )

    # Create .gitignore if missing, or ensure reserved names + secret-file
    # patterns are present. Expanded 2026-04-18 after repeated secret leaks:
    # scratch/ (session-scoped scripts), VOXCLAW.md (local cred reference),
    # .secrets, *.local, SECRETS.md etc. — files that carry live creds and
    # have no business in a public repo.
    gitignore = project / ".gitignore"
    DEFAULT_GITIGNORE = (
        "# Dependencies\nnode_modules/\n.venv/\nvenv/\nenv/\n\n"
        "# Build\ndist/\nbuild/\n*.egg-info/\n__pycache__/\ntarget/\n\n"
        "# IDE\n.idea/\n.vscode/\n*.swp\n*.swo\n\n"
        "# OS\n.DS_Store\nThumbs.db\n\n"
        "# Environment + credentials — never commit\n"
        ".env\n.env.*\n!.env.example\n"
        "*.key\n*.pem\n*.p12\n*.pfx\n"
        ".secrets\n*.secret*\ncredentials*\nsecrets/\n"
        "*.local\n\n"
        "# Documents that commonly contain live credentials\n"
        "VOXCLAW.md\nSECRETS.md\nCREDENTIALS.md\nPRIVATE.md\nCREDS.md\n\n"
        "# Session scratch — never commit\n"
        "scratch/\n"
        + RESERVED_GITIGNORE_BLOCK
    )
    # Minimum lines we always want to see in an existing .gitignore
    _REQUIRED_ENTRIES = [
        ".env", ".secrets", "VOXCLAW.md", "scratch/", "*.local", "nul",
    ]
    if not gitignore.exists():
        logger.info("Creating default .gitignore")
        gitignore.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
    else:
        existing = gitignore.read_text(encoding="utf-8", errors="replace")
        existing_lines = set(existing.splitlines())
        missing = [e for e in _REQUIRED_ENTRIES if e not in existing_lines]
        if missing:
            logger.info(f"Appending missing gitignore entries: {missing}")
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Added by uploader (secret-leak hardening, 2026-04-18)\n")
                for entry in missing:
                    f.write(entry + "\n")
                # Also append the reserved-names block if the `nul` sentinel was missing
                if "nul" in missing:
                    f.write(RESERVED_GITIGNORE_BLOCK)

    # Add all files (with recovery for problematic files)
    add_result = run_git("add", "-A")
    if add_result.returncode != 0:
        logger.warning("git add -A failed, attempting recovery...")
        # Reset index and try again - the .gitignore should now exclude reserved names
        run_git("reset")
        add_result = run_git("add", "-A")
        if add_result.returncode != 0:
            # Last resort: add files individually, skipping failures
            logger.warning("git add -A still failing, adding files individually...")
            status_check = run_git("status", "--porcelain")
            for line in status_check.stdout.strip().splitlines():
                # Extract filename from porcelain output (format: "XY filename")
                fname = line[3:].strip().strip('"')
                if fname and fname.lower() not in WINDOWS_RESERVED:
                    run_git("add", "--", fname)

    # --- SECRET SCAN GATE ---
    # Scan every staged file for high-confidence credential patterns (Stripe
    # sk_live_*, Telegram bot tokens, RunPod rpa_*, GitHub ghp_*, etc). Abort
    # the entire push on any hit so nobody leaks another live key through
    # this tool. The scanner runs on the INDEX, so .gitignore already filtered
    # the obvious cases — this catches the non-obvious ones (hardcoded tokens
    # in .js/.py/.md source files).
    try:
        from secret_scanner import scan_staged, format_report
        clean, findings = scan_staged(project)
        if not clean:
            print(format_report(findings), file=sys.stderr)
            logger.error(f"Secret scan blocked push for {project}: "
                         f"{len(findings)} findings")
            # Optional escape hatch for false positives
            if not force_secrets:
                return False
            logger.warning("--force-secrets set; pushing despite secret scan hits")
    except ImportError:
        logger.warning("secret_scanner module missing — skipping scan (NOT SAFE)")
    except Exception as e:
        logger.warning(f"secret scan errored, continuing anyway: {e}")

    # Check if there's anything to commit
    status = run_git("status", "--porcelain")
    if status.stdout.strip():
        logger.info(f"Committing changes ({len(status.stdout.strip().splitlines())} files)")
        run_git("commit", "-m", "Initial commit - uploaded via github-uploader-buildout")
    else:
        logger.info("No changes to commit (working tree clean)")

    # Set remote
    result = run_git("remote", "get-url", "origin")
    if result.returncode != 0:
        logger.info(f"Adding remote 'origin': {remote_url}")
        run_git("remote", "add", "origin", remote_url)
    else:
        old_url = result.stdout.strip()
        if old_url != remote_url:
            logger.info(f"Updating remote from '{old_url}' to '{remote_url}'")
            run_git("remote", "set-url", "origin", remote_url)
        else:
            logger.info(f"Remote already set to '{remote_url}'")

    # Push with retry (only retry on network errors, not refspec/commit errors)
    push_args = ["push", "-u", "origin", branch]
    if force:
        push_args = ["push", "--force", "-u", "origin", branch]
        logger.info("Force push enabled")
    for attempt in range(4):
        logger.info(f"Push attempt {attempt + 1}/4...")
        result = run_git(*push_args)
        if result.returncode == 0:
            logger.info(f"Push successful to {remote_url}")
            print(f"    Pushed successfully to {remote_url}")
            return True
        # Don't retry errors that won't resolve with retries
        stderr_lower = result.stderr.lower()
        if "src refspec" in stderr_lower or "does not match any" in stderr_lower:
            logger.error(f"No commits on branch '{branch}' - nothing to push")
            break
        if attempt < 3:
            import time
            wait = 2 ** (attempt + 1)
            logger.warning(f"Push failed (attempt {attempt + 1}), retrying in {wait}s...")
            print(f"    Push failed, retrying in {wait}s...")
            time.sleep(wait)

    logger.error(f"Failed to push to {remote_url} after 4 attempts")
    print(f"    Failed to push to {remote_url} after 4 attempts")
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    api = GitHubAPI()
    print(f"Authenticated as: {api.username}")
    repos = api.list_repos()
    print(f"You have {len(repos)} repositories:")
    for r in repos:
        print(f"  - {r['name']}: {r.get('description', '')}")
