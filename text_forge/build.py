"""
Build functions for EPUB generation.

Pipeline: mkdocs.yml → combine → normalize → pandoc → EPUB
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml


def load_mkdocs_config(config_path: Path) -> dict:
    """Load mkdocs.yml configuration."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        # Handle MkDocs custom tags like !ENV
        class IgnoreUnknownLoader(yaml.SafeLoader):
            pass

        def unknown_constructor(loader, tag_suffix, node):
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            elif isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            elif isinstance(node, yaml.MappingNode):
                return loader.construct_mapping(node)
            return None

        IgnoreUnknownLoader.add_multi_constructor("!", unknown_constructor)
        config = yaml.load(f, Loader=IgnoreUnknownLoader)

    return config


def combine_chapters(config_path: Path, output_path: Path) -> None:
    """
    Combine markdown chapters from mkdocs.yml navigation.

    Uses mkdocs-combine.py script.
    """
    script = Path(__file__).parent.parent / "scripts" / "mkdocs-combine.py"

    if not script.exists():
        raise FileNotFoundError(f"mkdocs-combine.py not found at {script}")

    print(f"Combining chapters from {config_path}...")

    with open(output_path, "w", encoding="utf-8") as out:
        result = subprocess.run(
            [sys.executable, str(script), str(config_path)],
            stdout=out,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    print(f"✓ Combined markdown saved to {output_path}")


def normalize_markdown(input_path: Path, output_path: Path) -> None:
    """
    Normalize PyMdown syntax to Pandoc-compatible markdown.

    Uses pymdown-pandoc.lua filter.
    """
    lua_filter = Path(__file__).parent.parent / "scripts" / "pymdown-pandoc.lua"

    if not lua_filter.exists():
        raise FileNotFoundError(f"pymdown-pandoc.lua not found at {lua_filter}")

    print(f"Normalizing markdown syntax...")

    result = subprocess.run(
        [
            "pandoc",
            str(input_path),
            "--from",
            "markdown",
            "--to",
            "markdown",
            "--lua-filter",
            str(lua_filter),
            "--output",
            str(output_path),
        ],
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    print(f"✓ Normalized markdown saved to {output_path}")


def process_epub_metadata(config_path: Path, output_path: Path) -> None:
    """
    Generate EPUB metadata YAML from mkdocs.yml.

    Uses process-epub-meta.py script.
    """
    import datetime
    import subprocess

    script = Path(__file__).parent.parent / "scripts" / "process-epub-meta.py"
    meta_template = Path(__file__).parent.parent / "epub" / "book_meta.yml"

    if not script.exists():
        raise FileNotFoundError(f"process-epub-meta.py not found at {script}")
    if not meta_template.exists():
        raise FileNotFoundError(f"book_meta.yml not found at {meta_template}")

    print(f"Processing EPUB metadata...")

    # Get git info for edition and date
    try:
        git_result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            check=True,
            cwd=config_path.parent,
        )
        edition = git_result.stdout.strip()
    except subprocess.CalledProcessError:
        edition = "dev"

    date = datetime.datetime.now().strftime("%Y-%m-%d")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--mkdocs-config",
            str(config_path),
            "--template",
            str(meta_template),
            "--out",
            str(output_path),
            "--edition",
            edition,
            "--date",
            date,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    print(f"✓ EPUB metadata saved to {output_path}")


def build_epub_with_pandoc(
    markdown_path: Path,
    metadata_path: Path,
    css_path: Path,
    cover_path: Optional[Path],
    output_path: Path,
) -> None:
    """
    Build EPUB using pandoc.
    """
    print(f"Building EPUB with pandoc...")

    cmd = [
        "pandoc",
        str(markdown_path),
        "--from",
        "markdown",
        "--to",
        "epub",
        "--metadata-file",
        str(metadata_path),
        "--css",
        str(css_path),
        "--output",
        str(output_path),
    ]

    if cover_path and cover_path.exists():
        cmd.extend(["--epub-cover-image", str(cover_path)])

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)

    print(f"✓ EPUB saved to {output_path}")


def build_epub_pipeline(config_path: Path, build_dir: Path) -> Path:
    """
    Run complete EPUB build pipeline.

    Returns path to generated EPUB file.
    """
    config_path = config_path.resolve()
    content_root = config_path.parent
    build_dir.mkdir(parents=True, exist_ok=True)

    # Load config to get docs_dir and other settings
    config = load_mkdocs_config(config_path)
    docs_dir = Path(config.get("docs_dir", "docs"))

    # Pipeline paths
    combined_md = build_dir / "text_combined.txt"
    normalized_md = build_dir / "pandoc.md"
    metadata_yaml = build_dir / "book_meta.yml"
    epub_file = build_dir / "text_book.epub"

    # Static assets
    css_file = Path(__file__).parent.parent / "epub" / "epub.css"
    cover_file = content_root / docs_dir / "img" / "cover.jpg"

    try:
        # Step 1: Combine chapters
        combine_chapters(config_path, combined_md)

        # Step 2: Normalize markdown
        normalize_markdown(combined_md, normalized_md)

        # Step 3: Process metadata
        process_epub_metadata(config_path, metadata_yaml)

        # Step 4: Build EPUB
        build_epub_with_pandoc(
            normalized_md,
            metadata_yaml,
            css_file,
            cover_file if cover_file.exists() else None,
            epub_file,
        )

        print(f"\n✓ EPUB build complete: {epub_file}")
        return epub_file

    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        raise
    except FileNotFoundError as e:
        print(f"✗ Build failed: {e}", file=sys.stderr)
        raise


def build_mkdocs_site(config_path: Path, site_dir: Optional[Path] = None) -> Path:
    """
    Build MkDocs site.

    Returns path to site directory.
    """
    config_path = config_path.resolve()

    # Load config to get site_dir
    config = load_mkdocs_config(config_path)
    if site_dir is None:
        site_dir = Path(config.get("site_dir", "public"))

    print(f"\nBuilding MkDocs site...")

    result = subprocess.run(
        ["mkdocs", "build", "--config-file", str(config_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    print(f"✓ Site built to {site_dir}")
    return site_dir


def copy_build_artifacts(build_dir: Path, docs_dir: Path) -> None:
    """
    Copy build artifacts (EPUB, combined text) to docs assets directory.

    This makes them available for download from the published site.
    """
    import shutil

    assets_dir = docs_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nCopying build artifacts to {assets_dir}...")

    # Copy EPUB
    epub_src = build_dir / "text_book.epub"
    if epub_src.exists():
        shutil.copy2(epub_src, assets_dir / "text_book.epub")
        print(f"✓ Copied {epub_src.name}")

    # Copy combined text
    txt_src = build_dir / "text_combined.txt"
    if txt_src.exists():
        shutil.copy2(txt_src, assets_dir / "text_combined.txt")
        print(f"✓ Copied {txt_src.name}")


def build_site_pipeline(config_path: Path, build_dir: Path) -> None:
    """
    Run complete site + EPUB build pipeline.

    1. Build EPUB
    2. Copy artifacts to docs/assets
    3. Build MkDocs site
    """
    config_path = config_path.resolve()
    content_root = config_path.parent

    # Load config
    config = load_mkdocs_config(config_path)
    docs_dir = content_root / Path(config.get("docs_dir", "docs"))

    try:
        # Step 1: Build EPUB
        epub_file = build_epub_pipeline(config_path, build_dir)

        # Step 2: Copy artifacts
        copy_build_artifacts(build_dir, docs_dir)

        # Step 3: Build site
        site_dir = build_mkdocs_site(config_path)

        print(f"\n✓ Full build complete!")
        print(f"  EPUB: {epub_file}")
        print(f"  Site: {site_dir}")

    except Exception as e:
        print(f"\n✗ Build failed: {e}", file=sys.stderr)
        raise
