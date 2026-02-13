"""
github_api.py - GitHub API integration for creating repos and managing content.

Uses either:
- GitHub personal access token (for local use)
- gh CLI (if authenticated)
- git proxy (for CI/cloud environments)
"""

import json
import os
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


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
        self.username = username or self._get_username()

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
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 204:
                    return {}
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_data = json.loads(error_body)
                msg = error_data.get("message", error_body)
            except json.JSONDecodeError:
                msg = error_body
            raise RuntimeError(f"GitHub API error ({e.code}): {msg}") from e

    def _get_username(self) -> str:
        """Get the authenticated user's username."""
        data = self._request("GET", "/user")
        return data["login"]

    def repo_exists(self, repo_name: str) -> bool:
        """Check if a repo already exists."""
        try:
            self._request("GET", f"/repos/{self.username}/{repo_name}")
            return True
        except RuntimeError as e:
            if "404" in str(e):
                return False
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
        data = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": False,  # We'll push our own content
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
        }
        if homepage:
            data["homepage"] = homepage
        return self._request("POST", "/user/repos", data)

    def update_repo(self, name: str, description: str = None, homepage: str = None) -> dict:
        """Update an existing repository's metadata."""
        data = {}
        if description is not None:
            data["description"] = description
        if homepage is not None:
            data["homepage"] = homepage
        if data:
            return self._request("PATCH", f"/repos/{self.username}/{name}", data)
        return {}

    def list_repos(self) -> list[dict]:
        """List all repos for the authenticated user."""
        repos = []
        page = 1
        while True:
            data = self._request("GET", f"/user/repos?per_page=100&page={page}")
            if not data:
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
        return repos


def git_init_and_push(project_path: str, remote_url: str, branch: str = "main") -> bool:
    """
    Initialize a git repo (if needed) and push to GitHub.

    Args:
        project_path: Local path to the project
        remote_url: GitHub repo URL (https)
        branch: Branch name to push to

    Returns:
        True if successful
    """
    project = Path(project_path)

    def run_git(*args, **kwargs):
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(project),
            capture_output=True,
            text=True,
            **kwargs,
        )
        if result.returncode != 0 and "already exists" not in result.stderr:
            print(f"    git {' '.join(args)}: {result.stderr.strip()}")
        return result

    # Initialize if not a git repo
    if not (project / ".git").exists():
        run_git("init")
        run_git("checkout", "-b", branch)
    else:
        # Check current branch
        result = run_git("branch", "--show-current")
        current_branch = result.stdout.strip()
        if current_branch and current_branch != branch:
            # Create or switch to target branch
            run_git("checkout", "-b", branch)

    # Create .gitignore if missing
    gitignore = project / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# Dependencies\nnode_modules/\n.venv/\nvenv/\nenv/\n\n"
            "# Build\ndist/\nbuild/\n*.egg-info/\n__pycache__/\n\n"
            "# IDE\n.idea/\n.vscode/\n*.swp\n*.swo\n\n"
            "# OS\n.DS_Store\nThumbs.db\n\n"
            "# Environment\n.env\n.env.local\n*.key\n*.pem\n",
            encoding="utf-8",
        )

    # Add all files
    run_git("add", "-A")

    # Check if there's anything to commit
    status = run_git("status", "--porcelain")
    if status.stdout.strip():
        run_git("commit", "-m", "Initial commit - uploaded via github-uploader-buildout")

    # Set remote
    result = run_git("remote", "get-url", "origin")
    if result.returncode != 0:
        run_git("remote", "add", "origin", remote_url)
    else:
        run_git("remote", "set-url", "origin", remote_url)

    # Push with retry
    for attempt in range(4):
        result = run_git("push", "-u", "origin", branch)
        if result.returncode == 0:
            print(f"    Pushed successfully to {remote_url}")
            return True
        if attempt < 3:
            import time
            wait = 2 ** (attempt + 1)
            print(f"    Push failed, retrying in {wait}s...")
            time.sleep(wait)

    print(f"    Failed to push to {remote_url} after 4 attempts")
    return False


if __name__ == "__main__":
    api = GitHubAPI()
    print(f"Authenticated as: {api.username}")
    repos = api.list_repos()
    print(f"You have {len(repos)} repositories:")
    for r in repos:
        print(f"  - {r['name']}: {r.get('description', '')}")
