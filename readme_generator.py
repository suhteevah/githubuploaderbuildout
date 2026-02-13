"""
readme_generator.py - Generates or updates README.md files with project info
and PayPal donation section.
"""

from pathlib import Path


DONATION_SECTION = """
---

## Support This Project

If you find this project useful, consider buying me a coffee! Your support helps me keep building and sharing open-source tools.

[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg?logo=paypal)](https://www.paypal.com/paypal.me/gankstapony)

**PayPal:** [gankstapony@hotmail.com](https://paypal.me/gankstapony)

Every donation, no matter how small, is greatly appreciated and motivates continued development. Thank you!
"""


def generate_readme(
    project_name: str,
    project_type: str = "",
    description: str = "",
    paypal_email: str = "gankstapony@hotmail.com",
) -> str:
    """
    Generate a complete README.md for a project.

    Args:
        project_name: Name of the project
        project_type: Language/framework type
        description: Project description
        paypal_email: PayPal email for donations

    Returns:
        Complete README.md content as string
    """
    lines = [f"# {project_name}", ""]

    if description:
        lines.append(description)
        lines.append("")

    if project_type:
        lines.append(f"**Built with:** {project_type}")
        lines.append("")

    lines.append("## Getting Started")
    lines.append("")
    lines.append("Clone the repository:")
    lines.append("")
    lines.append("```bash")
    lines.append(f"git clone https://github.com/suhteevah/{project_name}.git")
    lines.append(f"cd {project_name}")
    lines.append("```")
    lines.append("")

    # Add type-specific instructions
    if project_type:
        install_instructions = _get_install_instructions(project_type)
        if install_instructions:
            lines.append("## Installation")
            lines.append("")
            lines.extend(install_instructions)
            lines.append("")

    lines.append("## License")
    lines.append("")
    lines.append("This project is open source and available under the [MIT License](LICENSE).")

    # Add donation section
    donation = _build_donation_section(paypal_email)
    lines.append(donation)

    return "\n".join(lines) + "\n"


def _get_install_instructions(project_type: str) -> list[str]:
    """Get language-specific install instructions."""
    instructions = {
        "Node.js/JavaScript": [
            "```bash",
            "npm install",
            "npm start",
            "```",
        ],
        "TypeScript": [
            "```bash",
            "npm install",
            "npm run build",
            "npm start",
            "```",
        ],
        "Python": [
            "```bash",
            "pip install -r requirements.txt",
            "python main.py",
            "```",
        ],
        "Rust": [
            "```bash",
            "cargo build --release",
            "cargo run",
            "```",
        ],
        "Go": [
            "```bash",
            "go build",
            "go run .",
            "```",
        ],
        "Java (Maven)": [
            "```bash",
            "mvn clean install",
            "mvn exec:java",
            "```",
        ],
        "Java (Gradle)": [
            "```bash",
            "gradle build",
            "gradle run",
            "```",
        ],
        "Ruby": [
            "```bash",
            "bundle install",
            "ruby main.rb",
            "```",
        ],
        "PHP": [
            "```bash",
            "composer install",
            "php index.php",
            "```",
        ],
    }
    return instructions.get(project_type, [])


def _build_donation_section(paypal_email: str) -> str:
    """Build the donation section with the given PayPal email."""
    # Extract username from email for paypal.me link
    username = paypal_email.split("@")[0]

    return f"""
---

## Support This Project

If you find this project useful, consider buying me a coffee! Your support helps me keep building and sharing open-source tools.

[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg?logo=paypal)](https://www.paypal.me/{username})

**PayPal:** [{paypal_email}](https://paypal.me/{username})

Every donation, no matter how small, is greatly appreciated and motivates continued development. Thank you!"""


def update_existing_readme(readme_path: str, paypal_email: str = "gankstapony@hotmail.com") -> str:
    """
    Update an existing README.md to include the donation section.

    If the donation section already exists, it's replaced. Otherwise, it's appended.

    Args:
        readme_path: Path to existing README.md
        paypal_email: PayPal email for donations

    Returns:
        Updated README content
    """
    path = Path(readme_path)
    content = path.read_text(encoding="utf-8", errors="ignore")

    donation = _build_donation_section(paypal_email)

    # Check if donation section already exists
    if "## Support This Project" in content:
        # Replace existing donation section
        parts = content.split("## Support This Project")
        # Keep everything before the section
        before = parts[0].rstrip()
        content = before + "\n" + donation + "\n"
    else:
        # Append donation section
        content = content.rstrip() + "\n" + donation + "\n"

    return content


def ensure_readme(
    project_path: str,
    project_name: str,
    project_type: str = "",
    description: str = "",
    paypal_email: str = "gankstapony@hotmail.com",
) -> None:
    """
    Ensure a project has a README.md with donation section.

    If README exists, adds/updates donation section.
    If README doesn't exist, creates a complete one.

    Args:
        project_path: Path to the project directory
        project_name: Name of the project
        project_type: Language/framework type
        description: Project description
        paypal_email: PayPal email for donations
    """
    project = Path(project_path)
    readme = project / "README.md"

    if readme.exists():
        content = update_existing_readme(str(readme), paypal_email)
        print(f"    Updated existing README.md with donation section")
    else:
        content = generate_readme(project_name, project_type, description, paypal_email)
        print(f"    Created new README.md")

    readme.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    # Demo
    content = generate_readme(
        "my-cool-project",
        "Python",
        "A cool project that does cool things.",
    )
    print(content)
