#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


class _IgnoreUnknownTagsLoader(yaml.SafeLoader):
    pass


def _unknown(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
    # Handle mkdocs.yml custom tags like !ENV by returning the underlying scalar/sequence.
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_IgnoreUnknownTagsLoader.add_multi_constructor("!", _unknown)


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    # If mkdocs.yml contains unexpected types (e.g., from !ENV sequences),
    # render them in a readable way rather than crashing.
    return str(value).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process EPUB book_meta.yml placeholders"
    )
    parser.add_argument("--mkdocs-config", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    mkdocs_path = Path(args.mkdocs_config)
    template_path = Path(args.template)
    out_path = Path(args.out)

    mk = {}
    if mkdocs_path.exists():
        mk = (
            yaml.load(
                mkdocs_path.read_text(encoding="utf-8"), Loader=_IgnoreUnknownTagsLoader
            )
            or {}
        )

    site_name = _as_str(mk.get("site_name"))
    site_desc = _as_str(mk.get("site_description"))
    site_author = _as_str(mk.get("site_author"))
    site_url = _as_str(mk.get("site_url"))
    copyright_ = _as_str(mk.get("copyright"))

    # Read EPUB metadata from text-forge plugin config
    plugins = mk.get("plugins") or []
    text_forge_config = {}
    for plugin_entry in plugins:
        if isinstance(plugin_entry, dict) and "text-forge" in plugin_entry:
            text_forge_config = plugin_entry["text-forge"] or {}
            break

    epub_title = _as_str(text_forge_config.get("epub_title"))
    epub_subtitle = _as_str(text_forge_config.get("epub_subtitle"))
    epub_author = _as_str(text_forge_config.get("epub_author"))
    epub_identifier = _as_str(text_forge_config.get("epub_identifier"))
    epub_publisher = _as_str(text_forge_config.get("epub_publisher"))
    epub_rights = _as_str(text_forge_config.get("epub_rights"))

    title = epub_title or site_name or "Book"
    subtitle = epub_subtitle or site_desc
    author = epub_author or site_author
    identifier = epub_identifier or site_url or "urn:book"
    publisher = epub_publisher or site_author or "Publisher"

    rights = epub_rights
    if not rights:
        rights = copyright_ or (
            f'<a href="{site_url}">{site_url}</a>' if site_url else ""
        )

    text = template_path.read_text(encoding="utf-8")
    replacements = {
        "[title]": title,
        "[subtitle]": subtitle,
        "[author]": author,
        "[identifier]": identifier,
        "[publisher]": publisher,
        "[rights]": rights,
        "[edition]": args.edition,
        "[date]": args.date,
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    leftovers = sorted(set(re.findall(r"\[[a-z_]+\]", text)))
    if leftovers:
        raise SystemExit(
            f"Unreplaced placeholders in book_meta: {', '.join(leftovers)}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
