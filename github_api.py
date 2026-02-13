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

    # Create .gitignore if missing
    gitignore = project / ".gitignore"
    if not gitignore.exists():
        logger.info("Creating default .gitignore")
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

    # Push with retry
    for attempt in range(4):
        logger.info(f"Push attempt {attempt + 1}/4...")
        result = run_git("push", "-u", "origin", branch)
        if result.returncode == 0:
            logger.info(f"Push successful to {remote_url}")
            print(f"    Pushed successfully to {remote_url}")
            return True
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
