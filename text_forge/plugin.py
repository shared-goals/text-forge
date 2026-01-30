"""
MkDocs plugin for text-forge pipeline.

Automatically configures Material theme overrides, editor, and build pipeline.
"""

import json
import os
import sys
from pathlib import Path

from mkdocs.config import config_options
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin


class TextForgePlugin(BasePlugin):
    """
    text-forge MkDocs plugin.

    Provides:
    - Material theme overrides (editor, custom partials, assets)
    - Automatic hook registration (emoticon no-break)
    - Configuration for editor and build pipeline
    """

    config_scheme = (
        ("editor_enabled", config_options.Type(bool, default=True)),
        ("nobr_emoticons_enabled", config_options.Type(bool, default=True)),
        ("downloads_enabled", config_options.Type(bool, default=False)),
        ("auto_configure_theme", config_options.Type(bool, default=True)),
        ("epub_title", config_options.Type(str, default="")),
        ("epub_subtitle", config_options.Type(str, default="")),
        ("epub_author", config_options.Type(str, default="")),
        ("epub_identifier", config_options.Type(str, default="")),
        ("epub_publisher", config_options.Type(str, default="")),
        ("epub_rights", config_options.Type(str, default="")),
        ("source_file_published_title", config_options.Type(str, default="Published")),
    )

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        """
        Configure theme overrides and hooks from plugin package.

        If auto_configure_theme is enabled, sets theme.custom_dir to the
        theme directory bundled with this plugin. Also adds hooks directory
        to sys.path for hook imports.
        """
        if not self.config["auto_configure_theme"]:
            return config

        # Find theme and hooks directories - check multiple locations:
        # 1. Installed via pip/uv: sys.prefix/share/text-forge/mkdocs/{overrides,hooks}
        # 2. Development mode: relative to package directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))

        # Try installed location first (shared-data from pyproject.toml)
        theme_dir = os.path.join(
            sys.prefix, "share", "text-forge", "mkdocs", "overrides"
        )
        hooks_dir = os.path.join(sys.prefix, "share", "text-forge", "mkdocs", "hooks")

        # Fall back to development location if installed path doesn't exist
        if not os.path.exists(theme_dir):
            text_forge_root = os.path.dirname(plugin_dir)
            theme_dir = os.path.join(text_forge_root, "mkdocs", "overrides")
            hooks_dir = os.path.join(text_forge_root, "mkdocs", "hooks")

        # Store theme_dir for use in on_files
        self.theme_dir = theme_dir

        # Add hooks directory to sys.path so MkDocs can find hook modules
        if os.path.exists(hooks_dir) and hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)

        # Auto-register nobr_emoticons hook if enabled
        if self.config["nobr_emoticons_enabled"]:
            import importlib.util

            hook_path = os.path.join(hooks_dir, "nobr_emoticons.py")
            if os.path.exists(hook_path):
                spec = importlib.util.spec_from_file_location(
                    "nobr_emoticons", hook_path
                )
                hook_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(hook_module)
                # Register the hook function if it's defined
                if hasattr(hook_module, "on_page_markdown"):
                    # Store reference to prevent garbage collection
                    self._nobr_hook = hook_module

        # If user already has custom_dir, warn but don't override
        import logging

        log = logging.getLogger("mkdocs.plugins.text-forge")

        if config.theme.custom_dir:
            log.warning(
                f"theme.custom_dir is already set to '{config.theme.custom_dir}'. "
                f"text-forge plugin theme overrides will not be applied. "
                f"Set 'auto_configure_theme: false' in plugin config to suppress this warning."
            )
        else:
            # Add our theme directory to the theme's template search paths
            # This allows our templates to override Material theme templates
            if theme_dir not in config.theme.dirs:
                config.theme.dirs.insert(0, theme_dir)
                log.info(f"text-forge: Added '{theme_dir}' to theme.dirs")
            # CSS files are included via main.html template override in styles block

        return config

    def on_page_read_source(self, page, config):
        """Capture original source with frontmatter before parsing (for editor)."""
        # Read the actual file to get original content including frontmatter
        import os

        if page.file.abs_src_path and os.path.exists(page.file.abs_src_path):
            with open(page.file.abs_src_path, "r", encoding="utf-8") as f:
                original_source = f.read()
                # Store in page meta for later use by editor template
                if not hasattr(page, "_text_forge_original_source"):
                    page._text_forge_original_source = original_source
        return None  # Don't modify the source

    def on_files(self, files, config):
        """Add CSS, JS, and config files from plugin's custom_dir to the files collection."""
        import logging

        from mkdocs.structure.files import File

        log = logging.getLogger("mkdocs.plugins.text-forge")

        if not hasattr(self, "theme_dir") or not self.theme_dir:
            return files

        # Add CSS and JS assets to the files collection so they get copied to site_dir
        asset_files = ["assets/stylesheets/text-forge.css"]
        if self.config["editor_enabled"]:
            asset_files.append("assets/stylesheets/editor.css")
            asset_files.append("assets/js/editor.js")
            asset_files.append("assets/js/translations.json")

        for asset_path in asset_files:
            full_path = os.path.join(self.theme_dir, asset_path)
            if os.path.exists(full_path):
                # Remove existing file if present to avoid deprecation warning
                existing = files.get_file_from_path(asset_path)
                if existing:
                    files.remove(existing)

                # Create a File object for this asset file
                file = File(
                    path=asset_path,
                    src_dir=self.theme_dir,
                    dest_dir=config.site_dir,
                    use_directory_urls=config.use_directory_urls,
                )
                files.append(file)
                log.info(f"text-forge: Added {asset_path} to files collection")

        return files

    def on_page_markdown(self, markdown, page, config, files):
        """Apply nobr_emoticons hook if enabled."""
        # Apply nobr_emoticons hook if enabled
        if self.config["nobr_emoticons_enabled"] and hasattr(self, "_nobr_hook"):
            if hasattr(self._nobr_hook, "on_page_markdown"):
                return self._nobr_hook.on_page_markdown(markdown, page, config, files)
        return markdown

    def on_env(self, env, config, files):
        """Add plugin config to Jinja globals."""
        env.globals["text_forge_editor_enabled"] = self.config["editor_enabled"]
        env.globals["text_forge_downloads_enabled"] = self.config["downloads_enabled"]
        env.globals["text_forge_source_file_published_title"] = self.config[
            "source_file_published_title"
        ]
        # Expose EPUB config for templates that might need it
        env.globals["text_forge_epub"] = {
            "title": self.config["epub_title"],
            "subtitle": self.config["epub_subtitle"],
            "author": self.config["epub_author"],
            "identifier": self.config["epub_identifier"],
            "publisher": self.config["epub_publisher"],
            "rights": self.config["epub_rights"],
        }
        return env

    def on_serve(self, server, config, builder):
        """Add custom endpoint for saving files during development."""

        # Store docs_dir for the handler
        docs_dir = Path(config["docs_dir"]).resolve()

        # Get the original WSGI app that was set via set_app()
        original_app = server.get_app()

        def custom_app(environ, start_response):
            """Wrapped WSGI handler that intercepts save endpoint."""
            path = environ.get("PATH_INFO", "")

            # Handle our custom save endpoint
            if path == "/_text_forge/save" and environ["REQUEST_METHOD"] == "POST":
                try:
                    # Read request body
                    content_length = int(environ.get("CONTENT_LENGTH", 0))
                    body = environ["wsgi.input"].read(content_length)
                    data = json.loads(body)

                    file_path = data.get("filePath")
                    content = data.get("content")

                    if not file_path or content is None:
                        start_response(
                            "400 Bad Request",
                            [
                                ("Content-Type", "application/json"),
                                ("Access-Control-Allow-Origin", "*"),
                            ],
                        )
                        return [
                            json.dumps(
                                {"error": "Missing filePath or content"}
                            ).encode()
                        ]

                    # Security: ensure path is within docs_dir
                    target_path = (docs_dir / file_path).resolve()

                    if not str(target_path).startswith(str(docs_dir)):
                        start_response(
                            "403 Forbidden",
                            [
                                ("Content-Type", "application/json"),
                                ("Access-Control-Allow-Origin", "*"),
                            ],
                        )
                        return [json.dumps({"error": "Invalid file path"}).encode()]

                    # Write file
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(content, encoding="utf-8")

                    start_response(
                        "200 OK",
                        [
                            ("Content-Type", "application/json"),
                            ("Access-Control-Allow-Origin", "*"),
                        ],
                    )
                    return [
                        json.dumps({"success": True, "path": str(target_path)}).encode()
                    ]

                except Exception as e:
                    start_response(
                        "500 Internal Server Error",
                        [
                            ("Content-Type", "application/json"),
                            ("Access-Control-Allow-Origin", "*"),
                        ],
                    )
                    return [json.dumps({"error": str(e)}).encode()]

            # Not our endpoint, use original handler
            return original_app(environ, start_response)

        # Replace the WSGI app
        server.set_app(custom_app)

        return server
