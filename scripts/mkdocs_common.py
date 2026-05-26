"""Shared MkDocs helpers for text-forge scripts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(config_path: str | Path) -> dict[str, Any]:
    """Load MkDocs YAML configuration with graceful custom-tag handling."""
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.constructor.ConstructorError:
            # Handle MkDocs-style custom tags (e.g. !ENV) and Python object tags.
            f.seek(0)

            class SkipUnknownLoader(yaml.SafeLoader):
                pass

            def _construct_unknown(loader: Any, node: Any) -> Any:
                # Best-effort: preserve the underlying YAML structure but ignore the tag.
                if isinstance(node, yaml.ScalarNode):
                    return loader.construct_scalar(node)
                if isinstance(node, yaml.SequenceNode):
                    return loader.construct_sequence(node)
                if isinstance(node, yaml.MappingNode):
                    return loader.construct_mapping(node)
                return None

            def skip_unknown(loader: Any, tag_suffix: str, node: Any) -> Any:
                return _construct_unknown(loader, node)

            SkipUnknownLoader.add_multi_constructor("!python", skip_unknown)
            SkipUnknownLoader.add_multi_constructor(
                "tag:yaml.org,2002:python/", skip_unknown
            )
            # MkDocs commonly uses custom tags like !ENV (provided via pyyaml-env-tag).
            # Treat any unknown "!Something" tag as the underlying YAML node.
            SkipUnknownLoader.add_multi_constructor("!", skip_unknown)

            config = yaml.load(f, Loader=SkipUnknownLoader)

    return config if isinstance(config, dict) else {}


def remove_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown."""
    if content.startswith("---\n"):
        end_match = re.search(r"\n---\n", content[4:])
        if end_match:
            return content[end_match.end() + 4 :]
    return content


def flatten_nav_files(nav_config: list[Any]) -> list[str]:
    """Flatten navigation config into ordered list of .md filenames.

    Recursively walks the nav tree and returns only file entries,
    skipping section headers and external links.
    """
    files: list[str] = []
    for item in nav_config:
        if isinstance(item, str):
            if item.endswith(".md"):
                files.append(item)
        elif isinstance(item, dict):
            for section_items in item.values():
                if isinstance(section_items, str):
                    if section_items.endswith(".md"):
                        files.append(section_items)
                elif isinstance(section_items, list):
                    files.extend(flatten_nav_files(section_items))
    return files
