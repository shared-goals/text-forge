"""
text-forge: Reusable build/publish pipeline for Markdown chapter collections.

Provides MkDocs plugin with Material theme overrides, live editor, and EPUB generation.
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:  # an installed dist knows the real version — the one that was released
    __version__ = _dist_version("sg-text-forge")
except PackageNotFoundError:  # dev checkout that was never installed
    __version__ = "0.0.0.dev0"
