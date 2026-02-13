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
import sys
import os
import time

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_directory
from github_api import GitHubAPI, git_init_and_push
from readme_generator import ensure_readme


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
        default=r"J:\\",
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

    args = parser.parse_args()

    print_banner()

    # Normalize path for Windows
    scan_path = args.path.replace("\\\\", "\\")
    if not os.path.exists(scan_path):
        # Try common variations
        alternatives = [
            scan_path,
            scan_path.rstrip("\\") + "\\",
            scan_path.rstrip("/") + "/",
        ]
        found = False
        for alt in alternatives:
            if os.path.exists(alt):
                scan_path = alt
                found = True
                break
        if not found:
            print(f"Error: Path '{scan_path}' does not exist.")
            print(f"Make sure the drive is connected and accessible.")
            sys.exit(1)

    # Step 1: Scan for projects
    print(f"Step 1: Scanning '{scan_path}' for projects...\n")
    projects = scan_directory(scan_path, max_depth=args.max_depth, claude_only=args.claude_only)

    if not projects:
        print("No projects found. Try:")
        print(f"  - Check that '{scan_path}' contains project folders")
        print("  - Increase --max-depth")
        print("  - Remove --claude-only flag to include all projects")
        sys.exit(0)

    print_project_table(projects)

    # Step 2: Confirm
    if not args.yes and not args.dry_run:
        print(f"This will create {len(projects)} GitHub repo(s) and push code.")
        response = input("Continue? [y/N]: ").strip().lower()
        if response not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    # Step 3: Connect to GitHub
    if not args.dry_run:
        print("\nStep 2: Connecting to GitHub...\n")
        try:
            api = GitHubAPI(token=args.token)
            print(f"  Authenticated as: {api.username}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        api = None
        print("\nStep 2: [DRY RUN] Skipping GitHub authentication\n")

    # Step 4: Process each project
    print(f"\nStep 3: Processing {len(projects)} project(s)...\n")

    results = {"success": [], "skipped": [], "failed": []}

    for i, project in enumerate(projects, 1):
        name = sanitize_repo_name(project["name"])
        print(f"\n[{i}/{len(projects)}] {name}")
        print(f"  Path: {project['path']}")
        print(f"  Type: {project['type']}")

        if args.dry_run:
            print(f"  [DRY RUN] Would create repo: {name}")
            print(f"  [DRY RUN] Would update README.md with donation section")
            print(f"  [DRY RUN] Would push to GitHub")
            results["success"].append(name)
            continue

        try:
            # Check if repo already exists
            if api.repo_exists(name):
                print(f"  Repo '{name}' already exists on GitHub, will push updates")
            else:
                # Create the repo
                desc = project["description"][:200] if project["description"] else ""
                repo_data = api.create_repo(
                    name=name,
                    description=desc,
                    private=args.private,
                )
                print(f"  Created repo: {repo_data.get('html_url', name)}")

            # Update/create README with donation section
            ensure_readme(
                project_path=project["path"],
                project_name=name,
                project_type=project["type"],
                description=project["description"],
                paypal_email=args.paypal,
            )

            # Push to GitHub
            remote_url = f"https://github.com/{api.username}/{name}.git"
            success = git_init_and_push(project["path"], remote_url, args.branch)

            if success:
                results["success"].append(name)
                print(f"  Done: https://github.com/{api.username}/{name}")
            else:
                results["failed"].append(name)

        except Exception as e:
            print(f"  Error: {e}")
            results["failed"].append(name)

    # Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Successful: {len(results['success'])}")
    if results["success"]:
        for name in results["success"]:
            url = f"https://github.com/{api.username if api else 'USER'}/{name}" if not args.dry_run else name
            print(f"    - {url}")
    if results["skipped"]:
        print(f"  Skipped: {len(results['skipped'])}")
        for name in results["skipped"]:
            print(f"    - {name}")
    if results["failed"]:
        print(f"  Failed: {len(results['failed'])}")
        for name in results["failed"]:
            print(f"    - {name}")
    print()


if __name__ == "__main__":
    main()
