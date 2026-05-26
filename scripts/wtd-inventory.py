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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mkdocs_common import flatten_nav_files, load_yaml_config, remove_frontmatter

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*(\{[^}]*\})\s*$")
ID_ATTR_RE = re.compile(r"(?:^|\s)#([^\s}]+)")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    section_uid: str
    anchor: str | None
    heading_level: int
    heading: str
    url: str | None
    github_url: str | None
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
    sections: list[Section] = field(default_factory=list)


@dataclass
class Inventory:
    corpus: str
    repo: str | None
    commit: str | None
    site_url: str | None
    docs_dir: str
    chapters: list[Chapter]
    warnings: list[str] = field(default_factory=list)


def slug_for_path(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


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


def repo_blob_url(repo_url: str | None, commit: str | None, source_path: str, start: int, end: int) -> str | None:
    if not repo_url or not commit:
        return None
    repo = repo_url.rstrip("/")
    if repo.startswith("git@github.com:"):
        repo = "https://github.com/" + repo.removeprefix("git@github.com:")
    if repo.endswith(".git"):
        repo = repo[:-4]
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
    except Exception:
        return None


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


def anchored_headings(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """Return (line_number, level, heading_text, anchor) for headings with {#id}.

    Handles attr_list with additional attributes, e.g.:
        ## Title {#anchor style="..."}
    """
    out: list[tuple[int, int, str, str]] = []
    in_fence = False
    for idx, line in enumerate(lines, start=1):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        hashes, raw_heading, attrs = match.groups()
        id_match = ID_ATTR_RE.search(attrs.strip("{}"))
        if not id_match:
            continue
        heading = re.sub(r"\s+", " ", raw_heading).strip()
        out.append((idx, len(hashes), heading, id_match.group(1)))
    return out


def section_text(lines: list[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line]).strip()


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
    content = remove_frontmatter(source_file.read_text(encoding="utf-8")).lstrip("\n")
    lines = content.splitlines()
    chapter_slug = slug_for_path(filepath)
    source_path = str(source_file.relative_to(repo_root))
    base_url = page_url(site_url, chapter_slug)
    chapter_github_url = repo_blob_url(repo_url, commit, source_path, 1, max(1, len(lines)))
    title = first_heading(content, chapter_slug)

    headings = anchored_headings(lines)
    sections: list[Section] = []
    for index, (line_no, level, heading, anchor) in enumerate(headings):
        # Every explicit anchor is a public address and a memory/graph boundary.
        # Stop at the next explicit anchor at any heading level to avoid parent/child duplication.
        next_line = headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        end_line = max(line_no, next_line - 1)
        sections.append(
            Section(
                section_uid=anchor,
                anchor=anchor,
                heading_level=level,
                heading=heading,
                url=anchor_url(base_url, anchor),
                github_url=repo_blob_url(repo_url, commit, source_path, line_no, end_line),
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
                warnings.append(f"Duplicate section_uid in {chapter.chapter}: {section.section_uid}")
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
        f"site_url: {inv.site_url}",
        f"chapters: {chapter_count} ({published_count} published, {draft_count} draft)",
        f"sections: {section_count}",
    ]
    if inv.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in inv.warnings)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build WTD/text-forge source inventory")
    parser.add_argument("--config", default="mkdocs.yml", help="Path to mkdocs.yml")
    parser.add_argument("--include-drafts", action="store_true", help="Include Markdown files under docs_dir that are not in nav")
    parser.add_argument("--format", choices=["json", "summary"], default="summary")
    args = parser.parse_args()

    inv = build_inventory(Path(args.config).resolve(), args.include_drafts)
    if args.format == "json":
        print(json.dumps(asdict(inv), ensure_ascii=False, indent=2))
    else:
        print(summarize(inv))


if __name__ == "__main__":
    main()
