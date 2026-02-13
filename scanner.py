"""
scanner.py - Detects Claude Code projects on a given drive/directory.

Identifies projects by looking for common indicators:
- .git directories (existing git repos)
- package.json (Node.js projects)
- requirements.txt / setup.py / pyproject.toml (Python projects)
- Cargo.toml (Rust projects)
- go.mod (Go projects)
- .claude/ directory or claude.json (Claude Code specific markers)
- Any folder with source code files that looks like a project
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("uploader.scanner")

# Files/dirs that indicate a project root
PROJECT_MARKERS = [
    ".git",
    "package.json",
    "requirements.txt",
    "setup.py",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "CMakeLists.txt",
    "pom.xml",
    "build.gradle",
    ".claude",
    "claude.json",
    ".claudeignore",
]

# Directories to skip during scanning
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".cache",
    ".npm",
    ".yarn",
    ".pnpm-store",
    "$RECYCLE.BIN",
    "System Volume Information",
    "Recovery",
    ".Trash-1000",
}

# Claude Code specific indicators (weighted higher)
CLAUDE_INDICATORS = [
    ".claude",
    "claude.json",
    ".claudeignore",
    "CLAUDE.md",
    ".claude.toml",
]


def is_claude_project(project_path: Path) -> bool:
    """Check if a project has Claude Code specific files."""
    for indicator in CLAUDE_INDICATORS:
        if (project_path / indicator).exists():
            logger.debug(f"  Claude indicator found: {indicator}")
            return True
    return False


def detect_project_type(project_path: Path) -> str:
    """Detect the type/language of a project."""
    checks = [
        ("package.json", "Node.js/JavaScript"),
        ("tsconfig.json", "TypeScript"),
        ("requirements.txt", "Python"),
        ("setup.py", "Python"),
        ("pyproject.toml", "Python"),
        ("Cargo.toml", "Rust"),
        ("go.mod", "Go"),
        ("pom.xml", "Java (Maven)"),
        ("build.gradle", "Java (Gradle)"),
        ("CMakeLists.txt", "C/C++ (CMake)"),
        ("Makefile", "C/C++ (Make)"),
        ("Gemfile", "Ruby"),
        ("composer.json", "PHP"),
        ("pubspec.yaml", "Dart/Flutter"),
        ("*.sln", "C#/.NET"),
    ]
    for filename, project_type in checks:
        if filename.startswith("*"):
            if list(project_path.glob(filename)):
                return project_type
        elif (project_path / filename).exists():
            return project_type
    return "Unknown"


def get_project_description(project_path: Path) -> str:
    """Try to extract a description from the project."""
    # Check package.json
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        try:
            import json
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("description"):
                    return data["description"]
        except Exception as e:
            logger.debug(f"  Could not read package.json: {e}")

    # Check pyproject.toml for description
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "r", encoding="utf-8") as f:
                content = f.read()
                for line in content.split("\n"):
                    if line.strip().startswith("description"):
                        desc = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if desc:
                            return desc
        except Exception as e:
            logger.debug(f"  Could not read pyproject.toml: {e}")

    # Check existing README
    for readme_name in ["README.md", "README.txt", "README", "readme.md"]:
        readme = project_path / readme_name
        if readme.exists():
            try:
                with open(readme, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    # Get first non-empty, non-heading line as description
                    for line in lines[1:6]:  # Skip title, check next few lines
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            return stripped[:200]
            except Exception as e:
                logger.debug(f"  Could not read {readme_name}: {e}")

    return ""


def scan_directory(root_path: str, max_depth: int = 3, claude_only: bool = False) -> list[dict]:
    """
    Scan a directory for projects.

    Args:
        root_path: The root directory to scan (e.g., "J:\\")
        max_depth: Maximum directory depth to search
        claude_only: If True, only return projects with Claude Code indicators

    Returns:
        List of dicts with project info
    """
    root = Path(root_path)
    logger.info(f"scan_directory: root='{root_path}', max_depth={max_depth}, claude_only={claude_only}")

    if not root.exists():
        logger.error(f"Path '{root_path}' does not exist!")
        print(f"Error: Path '{root_path}' does not exist.")
        return []

    if not root.is_dir():
        logger.error(f"Path '{root_path}' is not a directory!")
        print(f"Error: Path '{root_path}' is not a directory.")
        return []

    logger.info(f"Path verified: '{root_path}' exists and is a directory")

    projects = []
    seen_paths = set()
    dirs_scanned = 0
    dirs_skipped = 0
    permission_errors = 0

    def _scan(directory: Path, depth: int):
        nonlocal dirs_scanned, dirs_skipped, permission_errors

        if depth > max_depth:
            logger.debug(f"  Max depth reached at: {directory}")
            return
        if directory.name in SKIP_DIRS:
            dirs_skipped += 1
            logger.debug(f"  Skipping (in SKIP_DIRS): {directory}")
            return

        dirs_scanned += 1

        try:
            entries = list(directory.iterdir())
        except PermissionError:
            permission_errors += 1
            logger.warning(f"  Permission denied: {directory}")
            return
        except OSError as e:
            logger.warning(f"  OS error scanning {directory}: {e}")
            return

        entry_names = {e.name for e in entries}
        markers_found = [m for m in PROJECT_MARKERS if m in entry_names]

        if markers_found:
            real_path = str(directory.resolve())
            if real_path not in seen_paths:
                seen_paths.add(real_path)
                is_claude = is_claude_project(directory)

                logger.debug(f"  Project candidate: {directory.name} | markers={markers_found} | claude={is_claude}")

                if claude_only and not is_claude:
                    logger.debug(f"  Skipping (not Claude, claude_only=True): {directory.name}")
                else:
                    project_info = {
                        "name": directory.name,
                        "path": str(directory),
                        "type": detect_project_type(directory),
                        "description": get_project_description(directory),
                        "is_claude": is_claude,
                        "has_git": (directory / ".git").exists(),
                        "markers_found": markers_found,
                    }
                    projects.append(project_info)
                    logger.info(f"  FOUND: {directory.name} ({project_info['type']})"
                                f"{' [Claude]' if is_claude else ''} at {directory}")
                    print(f"  Found: {directory.name} ({project_info['type']})"
                          f"{' [Claude Code]' if is_claude else ''}")
            return  # Don't recurse into project subdirectories

        # Recurse into subdirectories
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                _scan(entry, depth + 1)

    print(f"Scanning '{root_path}' for projects (max depth: {max_depth})...")
    _scan(root, 0)

    logger.info(f"Scan complete: {len(projects)} projects found, "
                f"{dirs_scanned} dirs scanned, {dirs_skipped} skipped, "
                f"{permission_errors} permission errors")
    print(f"\nFound {len(projects)} project(s).")

    if permission_errors > 0:
        print(f"  ({permission_errors} directories skipped due to permissions)")
        logger.warning(f"{permission_errors} directories could not be read (permission denied)")

    return projects


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    path = sys.argv[1] if len(sys.argv) > 1 else "J:\\"
    claude_only = "--claude-only" in sys.argv
    projects = scan_directory(path, claude_only=claude_only)
    for p in projects:
        print(f"\n  {p['name']}")
        print(f"    Path: {p['path']}")
        print(f"    Type: {p['type']}")
        print(f"    Claude: {p['is_claude']}")
        print(f"    Git: {p['has_git']}")
        if p['description']:
            print(f"    Desc: {p['description']}")
