#!/usr/bin/env python3
"""Prepare a local Techlab release without deployment concerns."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_PYPROJECT = ROOT_DIR / "backend" / "pyproject.toml"
FRONTEND_PACKAGE = ROOT_DIR / "frontend" / "package.json"
RELEASE_NOTES = ROOT_DIR / "release-notes-techlab.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version = "[^"]+"$')
LATEST_HEADING = "## Latest Changes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Semantic version, for example 0.2.0")
    return parser.parse_args()


def validate_version(version: str) -> None:
    if VERSION_RE.fullmatch(version) is None:
        raise SystemExit(f"Invalid version {version!r}; expected X.Y.Z")


def update_backend_version(version: str) -> None:
    content = BACKEND_PYPROJECT.read_text(encoding="utf-8")
    updated, count = PYPROJECT_VERSION_RE.subn(f'version = "{version}"', content, count=1)
    if count != 1:
        raise SystemExit(f"Unable to update version in {BACKEND_PYPROJECT}")
    BACKEND_PYPROJECT.write_text(updated, encoding="utf-8")


def update_frontend_version(version: str) -> None:
    package_data = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    package_data["version"] = version
    FRONTEND_PACKAGE.write_text(
        json.dumps(package_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_release_notes(version: str) -> None:
    content = RELEASE_NOTES.read_text(encoding="utf-8")
    if LATEST_HEADING not in content:
        raise SystemExit(f"{RELEASE_NOTES} must contain a '{LATEST_HEADING}' section")

    heading_pattern = re.compile(r"(?m)^## .+$")
    headings = list(heading_pattern.finditer(content))
    latest = next((heading for heading in headings if heading.group(0) == LATEST_HEADING), None)
    if latest is None:
        raise SystemExit(f"{RELEASE_NOTES} must contain a '{LATEST_HEADING}' section")

    next_heading = next((heading for heading in headings if heading.start() > latest.start()), None)
    section_start = latest.end()
    section_end = next_heading.start() if next_heading else len(content)
    latest_body = content[section_start:section_end].strip()

    if not latest_body:
        raise SystemExit(f"{LATEST_HEADING} is empty; add release notes before finalizing")

    release_heading = f"## {version}-techlab"
    if re.search(rf"(?m)^{re.escape(release_heading)}$", content):
        raise SystemExit(f"{release_heading} already exists in {RELEASE_NOTES}")

    before = content[: latest.start()].rstrip()
    after = content[section_end:].lstrip()
    sections = [
        before,
        f"{LATEST_HEADING}\n\n- TODO: add upcoming changes.",
        f"{release_heading}\n\n{latest_body}",
    ]
    if after:
        sections.append(after)

    RELEASE_NOTES.write_text("\n\n".join(section for section in sections if section) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    version = args.version
    validate_version(version)
    update_backend_version(version)
    update_frontend_version(version)
    update_release_notes(version)
    print(f"Prepared Techlab release {version}")
    print("Next steps:")
    print(f"- review release-notes-techlab.md")
    print(f"- regenerate the OpenAPI client if the backend schema changed")
    print(f"- commit the release changes")
    print(f"- tag with: git tag -a techlab-v{version} -m 'Techlab release {version}'")


if __name__ == "__main__":
    main()
