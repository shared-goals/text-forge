"""
Command-line interface for text-forge.

Provides commands for building EPUB, combining markdown, and other tasks.
"""

import sys
from pathlib import Path

import click


@click.group()
@click.version_option()
def main():
    """text-forge - MkDocs plugin and build tools for text projects."""
    pass


@main.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default="mkdocs.yml",
    help="Path to mkdocs.yml configuration file",
)
@click.option(
    "--build-dir",
    type=click.Path(path_type=Path),
    default="build",
    help="Build output directory",
)
def epub(config, build_dir):
    """Build EPUB from MkDocs project."""
    from text_forge.build import build_epub_pipeline

    try:
        epub_file = build_epub_pipeline(config, build_dir)
        click.echo(f"\n✓ Success! EPUB: {epub_file}")
    except Exception as e:
        click.echo(f"\n✗ Failed: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--config",
    type=click.Path(exists=True),
    default="mkdocs.yml",
    help="Path to mkdocs.yml configuration file",
)
def combine(config):
    """Combine markdown files based on nav structure."""
    click.echo(f"Combining markdown from {config}...")
    click.echo("TODO: Implement combine logic")


@main.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default="mkdocs.yml",
    help="Path to mkdocs.yml configuration file",
)
@click.option(
    "--build-dir",
    type=click.Path(path_type=Path),
    default="build",
    help="Build output directory",
)
@click.option(
    "--site-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="MkDocs site output directory (default: from mkdocs.yml)",
)
@click.option(
    "--strict/--no-strict",
    default=True,
    help="Run mkdocs build with --strict (fail on warnings)",
)
@click.option(
    "--copy-artifacts/--no-copy-artifacts",
    default=True,
    help="Copy EPUB and combined text to site_dir root",
)
@click.option(
    "--create-404-redirect/--no-create-404-redirect",
    default=True,
    help="Create 404.html for legacy URL redirects (default: enabled)",
)
def build(
    config,
    build_dir,
    site_dir,
    strict,
    copy_artifacts,
    create_404_redirect,
):
    """Build site and EPUB."""
    from text_forge.build import build_site_pipeline

    try:
        build_site_pipeline(
            config,
            build_dir,
            site_dir=site_dir,
            strict=strict,
            copy_artifacts=copy_artifacts,
            create_404_redirect=create_404_redirect,
        )
        click.echo("\n✓ Success! Full build complete.")
    except Exception as e:
        click.echo(f"\n✗ Failed: {e}", err=True)
        sys.exit(1)


@main.command()
def info():
    """Show text-forge version and configuration."""
    import sys

    from text_forge import __version__

    click.echo(f"text-forge version: {__version__}")
    click.echo(f"Python: {sys.version}")
    click.echo(f"Installed from: {Path(__file__).parent}")


@main.group()
def obsidian():
    """Obsidian vault setup commands."""
    pass


@obsidian.command("install")
@click.option(
    "--vault",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to Obsidian vault root (default: current directory)",
)
def obsidian_install(vault):
    """Install text-forge plugin, Templater scripts and templates into the vault.

    Run from the content repo root (the vault root).
    Requires Templater plugin to be installed first (handled by make obsidian).
    """
    import importlib.resources
    import json

    vault = vault.resolve()
    src = importlib.resources.files("text_forge.obsidian")

    def _copy(rel_src: str, rel_dst: str, skip_if_exists: bool = False) -> None:
        dst = vault / rel_dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        if skip_if_exists and dst.exists():
            click.echo(f"  skip  {rel_dst}")
            return
        dst.write_bytes((src / rel_src).read_bytes())
        click.echo(f"  wrote {rel_dst}")

    # Plugin (always overwrite — ensures latest version)
    click.echo("==> Installing text-forge plugin...")
    _copy("plugins/text-forge/main.js",      ".obsidian/plugins/text-forge/main.js")
    _copy("plugins/text-forge/manifest.json", ".obsidian/plugins/text-forge/manifest.json")

    # community-plugins.json — register text-forge
    plugins_file = vault / ".obsidian" / "community-plugins.json"
    if plugins_file.exists():
        plugins = json.loads(plugins_file.read_text())
        if "text-forge" not in plugins:
            plugins.append("text-forge")
            plugins_file.write_text(json.dumps(plugins, indent=2))
            click.echo("  added text-forge to .obsidian/community-plugins.json")
        else:
            click.echo("  skip  text-forge already in .obsidian/community-plugins.json")

    # Templater settings (skip if already configured)
    _copy("templater.json", ".obsidian/plugins/templater-obsidian/data.json", skip_if_exists=True)

    # Templater scripts + templates (skip if already present — user may have customised them)
    click.echo("==> Installing Templater scripts and templates...")
    for name in ("insert_block.js", "insert_image.js", "insert_link.js"):
        _copy(f"scripts/{name}", f"obsidian/scripts/{name}", skip_if_exists=True)
    for name in ("insert_block.md", "insert_image.md", "insert_link.md"):
        _copy(f"templates/{name}", f"obsidian/templates/{name}", skip_if_exists=True)

    # Hotkeys — merge (add missing keys, never remove existing)
    hotkeys_file = vault / ".obsidian" / "hotkeys.json"
    src_hotkeys = json.loads((src / "hotkeys.json").read_text(encoding="utf-8"))
    if hotkeys_file.exists():
        dst_hotkeys = json.loads(hotkeys_file.read_text(encoding="utf-8"))
        added = [k for k in src_hotkeys if k not in dst_hotkeys]
        dst_hotkeys.update({k: src_hotkeys[k] for k in added})
        hotkeys_file.write_text(json.dumps(dst_hotkeys, indent=2, ensure_ascii=False))
        click.echo(f"  hotkeys merged: {', '.join(added) if added else '(all present)'}")
    else:
        hotkeys_file.parent.mkdir(parents=True, exist_ok=True)
        hotkeys_file.write_text(json.dumps(src_hotkeys, indent=2, ensure_ascii=False))
        click.echo("  wrote .obsidian/hotkeys.json")

    click.echo("✓ Done. Restart Obsidian (or reload plugins) to apply.")


if __name__ == "__main__":
    main()
