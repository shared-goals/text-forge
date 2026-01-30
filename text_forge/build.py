"""
Build functions for EPUB generation.

Pipeline: mkdocs.yml → combine → normalize → pandoc → EPUB
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml


def _get_data_path(relative_path: str) -> Path:
    """
    Get path to data files (scripts, epub assets, etc.).

    Looks in installed location first (sys.prefix/share/text-forge/...),
    then falls back to repo-relative path for development.
    """
    # Try installed location (when installed via pip)
    installed = Path(sys.prefix) / "share" / "text-forge" / relative_path
    if installed.exists():
        return installed

    # Fall back to repo-relative path (for development)
    repo_relative = Path(__file__).parent.parent / relative_path
    if repo_relative.exists():
        return repo_relative

    raise FileNotFoundError(
        f"Could not find {relative_path} in installed location ({installed}) "
        f"or repo-relative location ({repo_relative})"
    )


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
    script = _get_data_path("scripts/mkdocs-combine.py")

    print(f"Combining chapters from {config_path}...")

    with open(output_path, "w", encoding="utf-8") as out:
        subprocess.run(
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
    lua_filter = _get_data_path("scripts/pymdown-pandoc.lua")

    print("Normalizing markdown syntax...")

    subprocess.run(
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

    script = _get_data_path("scripts/process-epub-meta.py")
    meta_template = _get_data_path("epub/book_meta.yml")

    print("Processing EPUB metadata...")

    # Get git info for edition and date (matching Makefile implementation)
    # Try to get most recent tag first
    git_tag = None
    try:
        git_result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
            cwd=config_path.parent,
        )
        git_tag = git_result.stdout.strip()
    except subprocess.CalledProcessError:
        pass
    
    # Fallback to describe if no tag found
    if not git_tag:
        try:
            git_result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                capture_output=True,
                text=True,
                check=True,
                cwd=config_path.parent,
            )
            git_tag = git_result.stdout.strip()
        except subprocess.CalledProcessError:
            git_tag = "dev"

    # Get date from last commit or use today
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        git_result = subprocess.run(
            ["git", "log", "-1", "--format=%cs"],
            capture_output=True,
            text=True,
            check=True,
            cwd=config_path.parent,
        )
        if git_result.stdout.strip():
            date = git_result.stdout.strip()
    except subprocess.CalledProcessError:
        pass

    # Format date with Russian month names (matching Makefile)
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
    russian_months = {
        "January": "января", "February": "февраля", "March": "марта",
        "April": "апреля", "May": "мая", "June": "июня",
        "July": "июля", "August": "августа", "September": "сентября",
        "October": "октября", "November": "ноября", "December": "декабря"
    }
    date_display = date_obj.strftime("%d %B %Y")
    for eng, rus in russian_months.items():
        date_display = date_display.replace(eng, rus)
    
    # Combine tag and formatted date as edition (like Makefile: "v0.51.0b1, 29 января 2026")
    edition = f"{git_tag}, {date_display}"

    subprocess.run(
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
    docs_dir: Path,
) -> None:
    """
    Build EPUB using pandoc.
    """
    print("Building EPUB with pandoc...")

    cmd = [
        "pandoc",
        str(markdown_path),
        "--from",
        "markdown+smart",
        "--to",
        "epub3",
        "--standalone",
        "--toc",
        "--toc-depth=2",
        "--metadata-file",
        str(metadata_path),
        "--resource-path",
        str(docs_dir),
        "--css",
        str(css_path),
        "--output",
        str(output_path),
    ]

    if cover_path and cover_path.exists():
        cmd.extend(["--epub-cover-image", str(cover_path)])

    subprocess.run(cmd, check=True, capture_output=True, text=True)

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
    css_file = _get_data_path("epub/epub.css")
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
            docs_dir,
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


def build_mkdocs_site(
    config_path: Path, site_dir: Optional[Path] = None, strict: bool = False
) -> Path:
    """
    Build MkDocs site.

    Returns path to site directory.
    """
    config_path = config_path.resolve()

    # Load config to get site_dir
    config = load_mkdocs_config(config_path)
    if site_dir is None:
        site_dir = Path(config.get("site_dir", "public"))

    print("\nBuilding MkDocs site...")

    cmd = [sys.executable, "-m", "mkdocs", "build", "--config-file", str(config_path)]
    if site_dir:
        cmd.extend(["--site-dir", str(site_dir)])
    if strict:
        cmd.append("--strict")

    subprocess.run(
        cmd,
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


def create_root_redirect(site_dir: Path, redirect_target: str = "/ru/") -> None:
    """
    Create root redirect HTML file.

    Creates public/index.html that redirects to the specified target (e.g., /ru/).
    """
    public_dir = site_dir.parent
    public_dir.mkdir(parents=True, exist_ok=True)

    redirect_file = public_dir / "index.html"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={redirect_target}"><link rel="canonical" href="{redirect_target}"><title>Redirecting to {redirect_target}</title></head><body><p>Redirecting to <a href="{redirect_target}">{redirect_target}</a>...</p><script>window.location.href="{redirect_target}";</script></body></html>"""

    redirect_file.write_text(html, encoding="utf-8")
    print(f"✓ Created root redirect: {redirect_file} → {redirect_target}")


def build_site_pipeline(
    config_path: Path,
    build_dir: Path,
    site_dir: Optional[Path] = None,
    strict: bool = False,
    copy_artifacts: bool = True,
    create_redirect: bool = True,
    redirect_target: str = "/ru/",
) -> None:
    """
    Run complete site + EPUB build pipeline.

    1. Build EPUB
    2. Copy artifacts to docs/assets (optional)
    3. Build MkDocs site
    4. Create root redirect (optional)
    """
    config_path = config_path.resolve()
    content_root = config_path.parent

    # Load config
    config = load_mkdocs_config(config_path)
    docs_dir = content_root / Path(config.get("docs_dir", "docs"))

    try:
        # Step 1: Build EPUB
        epub_file = build_epub_pipeline(config_path, build_dir)

        # Step 2: Copy artifacts (optional)
        if copy_artifacts:
            copy_build_artifacts(build_dir, docs_dir)

        # Step 3: Build site
        built_site_dir = build_mkdocs_site(config_path, site_dir, strict)

        # Step 4: Create root redirect (optional)
        if create_redirect:
            create_root_redirect(built_site_dir, redirect_target)

        print("\n✓ Full build complete!")
        print(f"  EPUB: {epub_file}")
        print(f"  Site: {built_site_dir}")

    except Exception as e:
        print(f"\n✗ Build failed: {e}", file=sys.stderr)
        raise
