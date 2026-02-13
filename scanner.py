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

import os
from pathlib import Path


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
        except Exception:
            pass

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
        except Exception:
            pass

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
            except Exception:
                pass

    return ""


def scan_directory(root_path: str, max_depth: int = 3, claude_only: bool = False) -> list[dict]:
    """
    Scan a directory for projects.

    Args:
        root_path: The root directory to scan (e.g., "J:\\")
        max_depth: Maximum directory depth to search
        claude_only: If True, only return projects with Claude Code indicators

    Returns:
        List of dicts with project info:
        {
            "name": str,
            "path": str,
            "type": str,
            "description": str,
            "is_claude": bool,
            "has_git": bool,
            "markers_found": list[str],
        }
    """
    root = Path(root_path)
    if not root.exists():
        print(f"Error: Path '{root_path}' does not exist.")
        return []

    projects = []
    seen_paths = set()

    def _scan(directory: Path, depth: int):
        if depth > max_depth:
            return
        if directory.name in SKIP_DIRS:
            return

        try:
            entries = list(directory.iterdir())
        except PermissionError:
            return
        except OSError:
            return

        entry_names = {e.name for e in entries}
        markers_found = [m for m in PROJECT_MARKERS if m in entry_names]

        if markers_found:
            real_path = str(directory.resolve())
            if real_path not in seen_paths:
                seen_paths.add(real_path)
                is_claude = is_claude_project(directory)

                if claude_only and not is_claude:
                    pass  # Skip non-Claude projects when filtering
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
                    print(f"  Found: {directory.name} ({project_info['type']})"
                          f"{' [Claude Code]' if is_claude else ''}")
            return  # Don't recurse into project subdirectories

        # Recurse into subdirectories
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                _scan(entry, depth + 1)

    print(f"Scanning '{root_path}' for projects (max depth: {max_depth})...")
    _scan(root, 0)
    print(f"\nFound {len(projects)} project(s).")
    return projects


if __name__ == "__main__":
    import sys
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
