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
    help="Copy EPUB and combined text to docs/assets",
)
@click.option(
    "--create-redirect/--no-create-redirect",
    default=True,
    help="Create root redirect HTML (public/index.html)",
)
@click.option(
    "--redirect-target",
    default="/ru/",
    help="Redirect target path (default: /ru/)",
)
def build(
    config,
    build_dir,
    site_dir,
    strict,
    copy_artifacts,
    create_redirect,
    redirect_target,
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
            create_redirect=create_redirect,
            redirect_target=redirect_target,
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


if __name__ == "__main__":
    main()
