#!/usr/bin/env python3
"""Build an anchor-aware inventory for MkDocs text projects.

The inventory is a deterministic source model for downstream agent-memory and
meaning-graph adapters. It does not write to memory itself.

Example:
    python scripts/wtd-inventory.py --config mkdocs.yml --include-drafts --format json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from mkdocs_common import flatten_nav_files, load_yaml_config
from wtd_sections_common import CODE_FENCE_RE, anchored_headings


@dataclass
class Section:
    section_uid: str
    anchor: str | None
    heading_level: int
    heading: str
    url: str | None
    github_url: str | None
    changed: str | None
    start_line: int
    end_line: int
    text: str


@dataclass
class Chapter:
    chapter: str
    status: str
    title: str
    nav_path: str | None
    source_path: str
    url: str | None
    github_url: str | None
    created: str | None = None
    published: str | None = None
    changed: str | None = None
    sections: list[Section] = field(default_factory=list)


@dataclass
class Inventory:
    corpus: str
    repo: str | None
    commit: str | None
    commit_date: str | None
    site_url: str | None
    docs_dir: str
    chapters: list[Chapter]
    warnings: list[str] = field(default_factory=list)


def slug_for_path(path: str) -> str:
    return path.removesuffix(".md")


def page_url(site_url: str | None, chapter: str) -> str | None:
    if not site_url:
        return None
    root = site_url.rstrip("/")
    if chapter == "index":
        return f"{root}/"
    return f"{root}/{chapter}/"


def anchor_url(base_url: str | None, anchor: str | None) -> str | None:
    if not base_url:
        return None
    if not anchor:
        return base_url
    return f"{base_url.rstrip('/')}/#{anchor}"


def repo_blob_url(
    repo_url: str | None, commit: str | None, source_path: str, start: int, end: int
) -> str | None:
    if not repo_url or not commit:
        return None
    repo = repo_url.rstrip("/")
    if repo.startswith("git@github.com:"):
        repo = "https://github.com/" + repo.removeprefix("git@github.com:")
    repo = repo.removesuffix(".git")
    if "github.com" not in repo:
        return None
    return f"{repo}/blob/{commit}/{source_path}#L{start}-L{end}"


def git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return None


def git_commit_date(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", "-s", "--format=%cI", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return None


def git_file_commit_date(repo_root: Path, source_path: str) -> str | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "-1",
                "--format=%cI",
                "--",
                source_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return None


def git_range_commit_date(
    repo_root: Path, source_path: str, start_line: int, end_line: int
) -> str | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "-1",
                "--format=%cI",
                "-L",
                f"{start_line},{end_line}:{source_path}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        output = result.stdout.strip()
        if not output:
            return None
        match = re.search(
            r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b",
            output,
        )
        return match.group(0) if match else None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return None


def content_line_offset(raw_content: str) -> int:
    """Return number of original file lines removed before content line 1.

    Offsets account for removed frontmatter and leading blank lines stripped from body.
    """
    lines = raw_content.splitlines()
    if not lines:
        return 0

    offset = 0
    body_start = 0
    if lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                body_start = i + 1
                break

    offset += body_start
    while body_start < len(lines) and lines[body_start] == "":
        body_start += 1
        offset += 1
    return offset


def iter_markdown_files(docs_dir: Path) -> Iterable[Path]:
    return sorted(p for p in docs_dir.rglob("*.md") if p.is_file())


def first_heading(content: str, fallback: str) -> str:
    in_fence = False
    for line in content.splitlines():
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)(?:\s*\{[^}]*\})?\s*$", line)
        if match:
            return match.group(1).strip()
    return fallback


def section_text(lines: list[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line]).strip()


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    end_match = re.search(r"\n---\n", content[4:])
    if not end_match:
        return {}, content
    fm_raw = content[4 : end_match.start() + 4]
    body = content[end_match.end() + 4 :]
    try:
        loaded = yaml.safe_load(fm_raw)
        frontmatter = loaded if isinstance(loaded, dict) else {}
    except yaml.YAMLError:
        frontmatter = {}
    return frontmatter, body


def frontmatter_value(frontmatter: dict[str, Any], key: str) -> str | None:
    value = frontmatter.get(key)
    if value is None:
        return None
    return str(value)


def build_chapter(
    *,
    docs_dir: Path,
    repo_root: Path,
    filepath: str,
    status: str,
    site_url: str | None,
    repo_url: str | None,
    commit: str | None,
) -> Chapter:
    source_file = docs_dir / filepath
    raw_content = source_file.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(raw_content)
    content = body.lstrip("\n")
    lines = content.splitlines()
    line_offset = content_line_offset(raw_content)
    chapter_slug = slug_for_path(filepath)
    source_path = str(source_file.relative_to(repo_root))
    changed = git_file_commit_date(repo_root, source_path)
    base_url = page_url(site_url, chapter_slug)
    chapter_github_url = repo_blob_url(
        repo_url, commit, source_path, 1, max(1, len(lines))
    )
    title = first_heading(content, chapter_slug)

    headings = anchored_headings(lines)
    sections: list[Section] = []
    for index, (line_no, level, heading, anchor) in enumerate(headings):
        # Every explicit anchor is a public address and a memory/graph boundary.
        # Stop at the next explicit anchor at any heading level to avoid parent/child duplication.
        next_line = (
            headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        )
        end_line = max(line_no, next_line - 1)
        raw_start_line = line_offset + line_no
        raw_end_line = line_offset + end_line
        sections.append(
            Section(
                section_uid=anchor,
                anchor=anchor,
                heading_level=level,
                heading=heading,
                url=anchor_url(base_url, anchor),
                github_url=repo_blob_url(
                    repo_url, commit, source_path, line_no, end_line
                ),
                changed=git_range_commit_date(
                    repo_root, source_path, raw_start_line, raw_end_line
                )
                or changed,
                start_line=line_no,
                end_line=end_line,
                text=section_text(lines, line_no, end_line),
            )
        )

    if not sections:
        # Chapter-level document: page itself is public even without heading anchors.
        sections.append(
            Section(
                section_uid="chapter",
                anchor=None,
                heading_level=1,
                heading=title,
                url=base_url,
                github_url=chapter_github_url,
                changed=changed,
                start_line=1,
                end_line=max(1, len(lines)),
                text=content.strip(),
            )
        )

    return Chapter(
        chapter=chapter_slug,
        status=status,
        title=title,
        nav_path=filepath if status == "published" else None,
        source_path=source_path,
        url=base_url,
        github_url=chapter_github_url,
        created=frontmatter_value(frontmatter, "created"),
        published=frontmatter_value(frontmatter, "published"),
        changed=changed,
        sections=sections,
    )


def validate_inventory(chapters: list[Chapter]) -> list[str]:
    warnings: list[str] = []
    seen_doc_keys: set[str] = set()
    for chapter in chapters:
        seen_sections: set[str] = set()
        for section in chapter.sections:
            key = f"{chapter.chapter}#{section.section_uid}"
            if key in seen_doc_keys:
                warnings.append(f"Duplicate document key: {key}")
            seen_doc_keys.add(key)
            if section.section_uid in seen_sections:
                warnings.append(
                    f"Duplicate section_uid in {chapter.chapter}: {section.section_uid}"
                )
            seen_sections.add(section.section_uid)
    return warnings


def build_inventory(config_path: Path, include_drafts: bool) -> Inventory:
    config = load_yaml_config(str(config_path))
    config_dir = config_path.parent
    docs_dir_name = config.get("docs_dir", "docs")
    docs_dir = (config_dir / docs_dir_name).resolve()
    if not docs_dir.exists():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")

    nav_files = flatten_nav_files(config.get("nav", []))
    nav_set = set(nav_files)
    all_files = [str(p.relative_to(docs_dir)) for p in iter_markdown_files(docs_dir)]
    draft_files = [path for path in all_files if path not in nav_set]

    repo_root = config_dir.resolve()
    commit = git_commit(repo_root)
    commit_date = git_commit_date(repo_root)
    repo_url = config.get("repo_url")
    site_url = config.get("site_url")

    chapters: list[Chapter] = []
    for filepath in nav_files:
        if (docs_dir / filepath).exists():
            chapters.append(
                build_chapter(
                    docs_dir=docs_dir,
                    repo_root=repo_root,
                    filepath=filepath,
                    status="published",
                    site_url=site_url,
                    repo_url=repo_url,
                    commit=commit,
                )
            )

    if include_drafts:
        for filepath in draft_files:
            chapters.append(
                build_chapter(
                    docs_dir=docs_dir,
                    repo_root=repo_root,
                    filepath=filepath,
                    status="draft",
                    site_url=site_url,
                    repo_url=repo_url,
                    commit=commit,
                )
            )

    warnings = validate_inventory(chapters)
    return Inventory(
        corpus="wtd",
        repo=repo_url,
        commit=commit,
        commit_date=commit_date,
        site_url=site_url,
        docs_dir=docs_dir_name,
        chapters=chapters,
        warnings=warnings,
    )


def summarize(inv: Inventory) -> str:
    chapter_count = len(inv.chapters)
    section_count = sum(len(ch.sections) for ch in inv.chapters)
    draft_count = sum(1 for ch in inv.chapters if ch.status == "draft")
    published_count = chapter_count - draft_count
    lines = [
        f"corpus: {inv.corpus}",
        f"commit: {inv.commit}",
        f"commit_date: {inv.commit_date}",
        f"site_url: {inv.site_url}",
        f"chapters: {chapter_count} ({published_count} published, {draft_count} draft)",
        f"sections: {section_count}",
    ]
    if inv.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in inv.warnings)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build WTD/text-forge source inventory"
    )
    parser.add_argument("--config", default="mkdocs.yml", help="Path to mkdocs.yml")
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Include Markdown files under docs_dir that are not in nav",
    )
    parser.add_argument("--format", choices=["json", "summary"], default="summary")
    args = parser.parse_args()

    inv = build_inventory(Path(args.config).resolve(), args.include_drafts)
    if args.format == "json":
        print(json.dumps(asdict(inv), ensure_ascii=False, indent=2))
    else:
        print(summarize(inv))


if __name__ == "__main__":
    main()
