#!/usr/bin/env python3
"""Policy guardrails for profile-template scope in Siindbad/Siindbad."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    violations: list[str] = []

    readme = ROOT / "README.md"
    readme_text = _read(readme)

    required = 'src="./assets/readme-top-dark.svg'
    if required not in readme_text:
        violations.append(f"{readme.as_posix()}: missing required profile banner source ({required})")

    forbidden_readme = [
        "readme-top-dark-template.svg",
        "HackHub-Save-File-Editor",
        "HackHub-Editor-Source",
    ]
    for needle in forbidden_readme:
        if needle in readme_text:
            violations.append(f"{readme.as_posix()}: forbidden external/project-template reference: {needle}")

    workflow = ROOT / ".github" / "workflows" / "profile-stats.yml"
    workflow_text = _read(workflow)
    forbidden_workflow = [
        "Sync dark template to public repo",
        "PUBLIC_REPO",
        "readme-top-dark-template.svg",
    ]
    for needle in forbidden_workflow:
        if needle in workflow_text:
            violations.append(f"{workflow.as_posix()}: forbidden cross-repo sync marker: {needle}")

    if violations:
        print("Profile scope policy violation(s):", file=sys.stderr)
        for v in violations:
            print(f"- {v}", file=sys.stderr)
        print("Rule: profile banner/template is scoped to Siindbad/Siindbad only.", file=sys.stderr)
        return 1

    print("Profile scope policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
