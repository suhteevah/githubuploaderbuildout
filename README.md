# GitHub Uploader Buildout

Automatically scan a drive or directory for code projects, create individual GitHub repositories for each one, add donation links to READMEs, and push everything to GitHub.

## Features

- **Auto-detection**: Scans for projects by recognizing `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`, and many more
- **Claude Code awareness**: Identifies Claude Code projects by `.claude/`, `CLAUDE.md`, etc.
- **Smart README generation**: Creates or updates README.md files with project info and a PayPal donation section
- **GitHub API integration**: Automatically creates repos and pushes code
- **Safe defaults**: Dry-run mode, interactive confirmation, skip-existing behavior

## Quick Start

### 1. Get a GitHub Personal Access Token

Go to [github.com/settings/tokens/new](https://github.com/settings/tokens/new) and create a token with the **`repo`** scope.

### 2. Set the token

**Windows (Command Prompt):**
```cmd
set GH_TOKEN=ghp_your_token_here
```

**Windows (PowerShell):**
```powershell
$env:GH_TOKEN = "ghp_your_token_here"
```

**Linux/Mac:**
```bash
export GH_TOKEN=ghp_your_token_here
```

### 3. Run the script

```bash
# Scan J: drive and upload all projects (interactive)
python upload_to_github.py

# Scan a specific folder
python upload_to_github.py --path "J:\MyProjects"

# Only Claude Code projects
python upload_to_github.py --claude-only

# Dry run first to see what would happen
python upload_to_github.py --dry-run

# Auto-confirm everything (non-interactive)
python upload_to_github.py --yes
```

Or use the Windows batch file:

```cmd
run_upload.bat
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--path`, `-p` | Root path to scan (default: `J:\`) |
| `--claude-only`, `-c` | Only upload Claude Code projects |
| `--yes`, `-y` | Skip confirmation prompts |
| `--dry-run`, `-d` | Preview without making changes |
| `--paypal` | PayPal email for donations (default: baal_hosting@live.com) |
| `--max-depth` | How deep to scan directories (default: 3) |
| `--private` | Create private repos |
| `--token`, `-t` | GitHub token (alternative to GH_TOKEN env var) |
| `--branch`, `-b` | Branch to push to (default: main) |

## Project Structure

```
githubuploaderbuildout/
  upload_to_github.py    # Main script - run this
  scanner.py             # Project detection and scanning
  github_api.py          # GitHub API and git operations
  readme_generator.py    # README creation with donation section
  run_upload.bat         # Windows quick-start batch file
```

## How It Works

1. **Scan**: Walks the target directory tree looking for project markers (package.json, .git, etc.)
2. **Identify**: Classifies each project by type (Python, Node.js, Rust, etc.) and detects Claude Code projects
3. **Create repos**: Uses the GitHub API to create a new public repo for each project
4. **Update READMEs**: Adds or updates README.md with project info and a PayPal donation link
5. **Push**: Initializes git (if needed), commits, and pushes to GitHub

## Requirements

- Python 3.8+
- Git installed and on PATH
- GitHub personal access token with `repo` scope

---

## Support This Project

If you find this project useful, consider buying me a coffee! Your support helps me keep building and sharing open-source tools.

[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg?logo=paypal)](https://www.paypal.me/baal_hosting)

**PayPal:** [baal_hosting@live.com](https://paypal.me/baal_hosting)

Every donation, no matter how small, is greatly appreciated and motivates continued development. Thank you!
