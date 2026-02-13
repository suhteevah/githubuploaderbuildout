#!/usr/bin/env python3
"""
upload_to_github.py - Main orchestrator script.

Scans a drive/directory for Claude Code projects, creates GitHub repos for each,
adds donation README sections, and pushes everything.

Usage:
    # Set your GitHub token first:
    #   Windows: set GH_TOKEN=ghp_your_token_here
    #   Linux/Mac: export GH_TOKEN=ghp_your_token_here

    # Scan J: drive and upload all projects (interactive)
    python upload_to_github.py

    # Scan a specific path
    python upload_to_github.py --path "J:\\MyProjects"

    # Only Claude Code projects
    python upload_to_github.py --claude-only

    # Non-interactive mode (auto-confirm everything)
    python upload_to_github.py --yes

    # Dry run (show what would happen without making changes)
    python upload_to_github.py --dry-run

    # Set custom PayPal email
    python upload_to_github.py --paypal "youremail@example.com"
"""

import argparse
import datetime
import logging
import os
import platform
import sys
import traceback

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_directory
from github_api import GitHubAPI, git_init_and_push
from readme_generator import ensure_readme

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_log.txt")


def setup_logging(verbose: bool = False):
    """
    Set up logging to both console and a log file.

    The log file always gets DEBUG-level detail.
    The console gets INFO by default, DEBUG if --verbose.
    """
    root_logger = logging.getLogger("uploader")
    root_logger.setLevel(logging.DEBUG)

    # File handler - always verbose
    file_handler = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_fmt = logging.Formatter("  [LOG] %(message)s")
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    return root_logger


def sanitize_repo_name(name: str) -> str:
    """
    Sanitize a folder name to be a valid GitHub repo name.
    GitHub repo names can contain alphanumerics, hyphens, underscores, and dots.
    """
    sanitized = ""
    for char in name:
        if char.isalnum() or char in "-_.":
            sanitized += char
        elif char in " /\\":
            sanitized += "-"
    # Remove leading/trailing hyphens/dots
    sanitized = sanitized.strip("-.")
    # Collapse multiple hyphens
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "unnamed-project"


def print_banner():
    """Print a banner."""
    print("=" * 60)
    print("  GitHub Uploader Buildout")
    print("  Scan, create repos, add donations, and push to GitHub")
    print("=" * 60)
    print()


def print_project_table(projects: list[dict]):
    """Print a formatted table of discovered projects."""
    print(f"\n{'#':<4} {'Name':<30} {'Type':<20} {'Claude':<8} {'Git':<5}")
    print("-" * 70)
    for i, p in enumerate(projects, 1):
        claude = "Yes" if p["is_claude"] else "No"
        git = "Yes" if p["has_git"] else "No"
        name = p["name"][:28]
        ptype = p["type"][:18]
        print(f"{i:<4} {name:<30} {ptype:<20} {claude:<8} {git:<5}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Upload Claude Code projects to individual GitHub repos."
    )
    parser.add_argument(
        "--path", "-p",
        default="J:\\",
        help="Root path to scan for projects (default: J:\\)",
    )
    parser.add_argument(
        "--claude-only", "-c",
        action="store_true",
        help="Only upload projects with Claude Code indicators",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-confirm all prompts (non-interactive mode)",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--paypal",
        default="gankstapony@hotmail.com",
        help="PayPal email for donation links (default: gankstapony@hotmail.com)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum directory depth to scan (default: 3)",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create private repos instead of public",
    )
    parser.add_argument(
        "--token", "-t",
        help="GitHub personal access token (or set GH_TOKEN env var)",
    )
    parser.add_argument(
        "--branch", "-b",
        default="main",
        help="Branch name to push to (default: main)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose debug output on console (log file is always verbose)",
    )

    args = parser.parse_args()

    # Set up logging FIRST
    logger = setup_logging(verbose=args.verbose)
    logger.info("=" * 60)
    logger.info("GitHub Uploader Buildout - Run started")
    logger.info(f"Timestamp: {datetime.datetime.now().isoformat()}")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Working dir: {os.getcwd()}")
    logger.info(f"Args: {vars(args)}")
    logger.info("=" * 60)

    print_banner()
    print(f"  Log file: {LOG_FILE}")
    print(f"  (All debug details are written to the log file)\n")

    # Normalize path for Windows
    scan_path = args.path
    # Handle double-escaped backslashes from shell
    scan_path = scan_path.replace("\\\\", "\\")
    logger.info(f"Scan path (raw): '{args.path}' -> (normalized): '{scan_path}'")

    if not os.path.exists(scan_path):
        # Try common variations for Windows drive paths
        alternatives = [
            scan_path,
            scan_path.rstrip("\\") + "\\",
            scan_path.rstrip("/") + "/",
            scan_path.rstrip("\\/"),
        ]
        # Also try without trailing slash for drive letters like J:
        if len(scan_path) >= 2 and scan_path[1] == ":":
            alternatives.append(scan_path[:2] + "\\")
            alternatives.append(scan_path[:2] + "/")
            alternatives.append(scan_path[:2])

        logger.info(f"Path '{scan_path}' not found, trying alternatives: {alternatives}")
        found = False
        for alt in alternatives:
            logger.debug(f"  Trying: '{alt}' -> exists={os.path.exists(alt)}")
            if os.path.exists(alt):
                scan_path = alt
                found = True
                logger.info(f"Found working path: '{alt}'")
                break
        if not found:
            msg = f"Error: Path '{scan_path}' does not exist."
            print(msg)
            print("Make sure the drive is connected and accessible.")
            logger.error(msg)
            logger.error(f"Tried alternatives: {alternatives}")
            logger.error("Exiting.")
            sys.exit(1)

    # Step 1: Scan for projects
    print(f"Step 1: Scanning '{scan_path}' for projects...\n")
    logger.info(f"Step 1: Scanning '{scan_path}' (max_depth={args.max_depth}, claude_only={args.claude_only})")
    projects = scan_directory(scan_path, max_depth=args.max_depth, claude_only=args.claude_only)

    if not projects:
        print("No projects found. Try:")
        print(f"  - Check that '{scan_path}' contains project folders")
        print("  - Increase --max-depth")
        print("  - Remove --claude-only flag to include all projects")
        logger.warning("No projects found. Exiting.")
        sys.exit(0)

    logger.info(f"Found {len(projects)} projects:")
    for i, p in enumerate(projects, 1):
        logger.info(f"  {i}. {p['name']} | type={p['type']} | claude={p['is_claude']} | path={p['path']}")

    print_project_table(projects)

    # Step 2: Confirm
    if not args.yes and not args.dry_run:
        print(f"This will create {len(projects)} GitHub repo(s) and push code.")
        response = input("Continue? [y/N]: ").strip().lower()
        if response not in ("y", "yes"):
            print("Aborted.")
            logger.info("User aborted at confirmation prompt.")
            sys.exit(0)

    # Step 3: Connect to GitHub
    if not args.dry_run:
        print("\nStep 2: Connecting to GitHub...\n")
        logger.info("Step 2: Connecting to GitHub API...")
        try:
            api = GitHubAPI(token=args.token)
            print(f"  Authenticated as: {api.username}")
        except ValueError as e:
            print(f"Error: {e}")
            logger.error(f"GitHub auth failed (ValueError): {e}")
            logger.error(traceback.format_exc())
            sys.exit(1)
        except RuntimeError as e:
            print(f"Error connecting to GitHub: {e}")
            logger.error(f"GitHub auth failed (RuntimeError): {e}")
            logger.error(traceback.format_exc())
            print(f"\n  Check the log file for details: {LOG_FILE}")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {type(e).__name__}: {e}")
            logger.error(f"GitHub auth failed (unexpected): {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            print(f"\n  Check the log file for details: {LOG_FILE}")
            sys.exit(1)
    else:
        api = None
        print("\nStep 2: [DRY RUN] Skipping GitHub authentication\n")
        logger.info("Step 2: DRY RUN - skipping GitHub auth")

    # Step 4: Process each project
    print(f"\nStep 3: Processing {len(projects)} project(s)...\n")
    logger.info(f"Step 3: Processing {len(projects)} project(s)...")

    results = {"success": [], "skipped": [], "failed": []}

    for i, project in enumerate(projects, 1):
        name = sanitize_repo_name(project["name"])
        print(f"\n[{i}/{len(projects)}] {name}")
        print(f"  Path: {project['path']}")
        print(f"  Type: {project['type']}")
        logger.info(f"--- [{i}/{len(projects)}] Processing: {name} ---")
        logger.info(f"  Original name: '{project['name']}' -> Sanitized: '{name}'")
        logger.info(f"  Path: {project['path']}")
        logger.info(f"  Type: {project['type']}")
        logger.info(f"  Description: {project['description'][:100] if project['description'] else '(none)'}")
        logger.info(f"  Markers: {project['markers_found']}")

        if args.dry_run:
            print(f"  [DRY RUN] Would create repo: {name}")
            print(f"  [DRY RUN] Would update README.md with donation section")
            print(f"  [DRY RUN] Would push to GitHub")
            results["success"].append(name)
            continue

        try:
            # Check if repo already exists
            exists = api.repo_exists(name)
            if exists:
                print(f"  Repo '{name}' already exists on GitHub, will push updates")
                logger.info(f"Repo '{name}' already exists, will update")
            else:
                # Create the repo
                desc = project["description"][:200] if project["description"] else ""
                logger.info(f"Creating new repo '{name}' with desc: '{desc[:80]}'")
                repo_data = api.create_repo(
                    name=name,
                    description=desc,
                    private=args.private,
                )
                print(f"  Created repo: {repo_data.get('html_url', name)}")
                logger.info(f"Repo created successfully: {repo_data.get('html_url', name)}")

            # Update/create README with donation section
            logger.info(f"Ensuring README.md with donation section...")
            ensure_readme(
                project_path=project["path"],
                project_name=name,
                project_type=project["type"],
                description=project["description"],
                paypal_email=args.paypal,
            )
            logger.info("README.md updated/created.")

            # Push to GitHub
            remote_url = f"https://github.com/{api.username}/{name}.git"
            logger.info(f"Pushing to: {remote_url}")
            success = git_init_and_push(project["path"], remote_url, args.branch)

            if success:
                results["success"].append(name)
                url = f"https://github.com/{api.username}/{name}"
                print(f"  Done: {url}")
                logger.info(f"SUCCESS: {url}")
            else:
                results["failed"].append(name)
                logger.error(f"FAILED: Push failed for '{name}'")

        except Exception as e:
            print(f"  Error: {e}")
            logger.error(f"FAILED: Exception processing '{name}': {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            results["failed"].append(name)

    # Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    logger.info("=" * 40)
    logger.info("SUMMARY")

    print(f"  Successful: {len(results['success'])}")
    logger.info(f"Successful: {len(results['success'])}")
    if results["success"]:
        for name in results["success"]:
            if not args.dry_run and api:
                url = f"https://github.com/{api.username}/{name}"
            else:
                url = name
            print(f"    - {url}")
            logger.info(f"  OK: {url}")

    if results["skipped"]:
        print(f"  Skipped: {len(results['skipped'])}")
        logger.info(f"Skipped: {len(results['skipped'])}")
        for name in results["skipped"]:
            print(f"    - {name}")
            logger.info(f"  SKIP: {name}")

    if results["failed"]:
        print(f"  Failed: {len(results['failed'])}")
        logger.info(f"Failed: {len(results['failed'])}")
        for name in results["failed"]:
            print(f"    - {name}")
            logger.error(f"  FAIL: {name}")

    print()
    if results["failed"]:
        print(f"  Some uploads failed. Check the log for details:")
        print(f"    {LOG_FILE}")
    else:
        print(f"  Full log saved to: {LOG_FILE}")
    print()

    logger.info(f"Run completed. Success={len(results['success'])}, Failed={len(results['failed'])}, Skipped={len(results['skipped'])}")


if __name__ == "__main__":
    main()
