"""
MkDocs plugin for text-forge pipeline.

Automatically configures Material theme overrides, editor, and build pipeline.
"""

import os
import sys
from mkdocs.plugins import BasePlugin
from mkdocs.config import config_options
from mkdocs.config.defaults import MkDocsConfig


class TextForgePlugin(BasePlugin):
    """
    text-forge MkDocs plugin.
    
    Provides:
    - Material theme overrides (editor, custom partials, assets)
    - Automatic hook registration (emoticon no-break)
    - Configuration for editor and build pipeline
    """
    
    config_scheme = (
        ('editor_enabled', config_options.Type(bool, default=True)),
        ('nobr_emoticons_enabled', config_options.Type(bool, default=True)),
        ('auto_configure_theme', config_options.Type(bool, default=True)),
        ('epub_title', config_options.Type(str, default='')),
        ('epub_subtitle', config_options.Type(str, default='')),
        ('epub_author', config_options.Type(str, default='')),
        ('epub_identifier', config_options.Type(str, default='')),
        ('epub_publisher', config_options.Type(str, default='')),
        ('epub_rights', config_options.Type(str, default='')),
        ('source_file_published_title', config_options.Type(str, default='Published')),
    )
    
    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        """
        Configure theme overrides and hooks from plugin package.
        
        If auto_configure_theme is enabled, sets theme.custom_dir to the
        theme directory bundled with this plugin. Also adds hooks directory
        to sys.path for hook imports.
        """
        if not self.config['auto_configure_theme']:
            return config
            
        # Find theme and hooks directories - check multiple locations:
        # 1. Installed via pip/uv: sys.prefix/share/text-forge/mkdocs/{overrides,hooks}
        # 2. Development mode: relative to package directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Try installed location first (shared-data from pyproject.toml)
        theme_dir = os.path.join(sys.prefix, 'share', 'text-forge', 'mkdocs', 'overrides')
        hooks_dir = os.path.join(sys.prefix, 'share', 'text-forge', 'mkdocs', 'hooks')
        
        # Fall back to development location if installed path doesn't exist
        if not os.path.exists(theme_dir):
            text_forge_root = os.path.dirname(plugin_dir)
            theme_dir = os.path.join(text_forge_root, 'mkdocs', 'overrides')
            hooks_dir = os.path.join(text_forge_root, 'mkdocs', 'hooks')
        
        # Store theme_dir for use in on_files
        self.theme_dir = theme_dir
        
        # Add hooks directory to sys.path so MkDocs can find hook modules
        if os.path.exists(hooks_dir) and hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        
        # Auto-register nobr_emoticons hook if enabled
        if self.config['nobr_emoticons_enabled']:
            import importlib.util
            hook_path = os.path.join(hooks_dir, 'nobr_emoticons.py')
            if os.path.exists(hook_path):
                spec = importlib.util.spec_from_file_location('nobr_emoticons', hook_path)
                hook_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(hook_module)
                # Register the hook function if it's defined
                if hasattr(hook_module, 'on_page_markdown'):
                    # Store reference to prevent garbage collection
                    self._nobr_hook = hook_module

        # If user already has custom_dir, warn but don't override
        import logging
        log = logging.getLogger('mkdocs.plugins.text-forge')
        
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
    
    def on_files(self, files, config):
        """Add CSS and JS files from plugin's custom_dir to the files collection."""
        from mkdocs.structure.files import File
        import logging
        log = logging.getLogger('mkdocs.plugins.text-forge')
        
        if not hasattr(self, 'theme_dir') or not self.theme_dir:
            return files
        
        # Add CSS files to the files collection so they get copied to site_dir
        css_files = ['assets/stylesheets/text-forge.css']
        if self.config['editor_enabled']:
            css_files.append('assets/stylesheets/editor.css')
        
        for css_path in css_files:
            full_path = os.path.join(self.theme_dir, css_path)
            if os.path.exists(full_path):
                # Create a File object for this CSS file
                file = File(
                    path=css_path,
                    src_dir=self.theme_dir,
                    dest_dir=config.site_dir,
                    use_directory_urls=config.use_directory_urls
                )
                files.append(file)
                log.info(f"text-forge: Added {css_path} to files collection")
        
        return files
    
    def on_page_markdown(self, markdown, page, config, files):
        """Proxy to nobr_emoticons hook if enabled."""
        if self.config['nobr_emoticons_enabled'] and hasattr(self, '_nobr_hook'):
            if hasattr(self._nobr_hook, 'on_page_markdown'):
                return self._nobr_hook.on_page_markdown(markdown, page, config, files)
        return markdown
    
    def on_env(self, env, config, files):
        """Add plugin config to Jinja globals."""
        env.globals['text_forge_editor_enabled'] = self.config['editor_enabled']
        env.globals['text_forge_source_file_published_title'] = self.config['source_file_published_title']
        # Expose EPUB config for templates that might need it
        env.globals['text_forge_epub'] = {
            'title': self.config['epub_title'],
            'subtitle': self.config['epub_subtitle'],
            'author': self.config['epub_author'],
            'identifier': self.config['epub_identifier'],
            'publisher': self.config['epub_publisher'],
            'rights': self.config['epub_rights'],
        }
        return env
