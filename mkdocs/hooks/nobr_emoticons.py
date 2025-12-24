"""
MkDocs hook to wrap emoticons in <span class="nobr"> to prevent line breaks.
"""
import re
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

# List of emoticons to wrap (add more as needed)
EMOTICONS = [
    r':-\)',   # :-)
    r':-\(',   # :-(
    r';-\)',   # ;-)
    r':-D',    # :-D
    r':-P',    # :-P
    r':\)',    # :)
    r':\(',    # :(
    r';\)',    # ;)
]

# Build regex pattern: match emoticons not already in HTML tags
pattern = re.compile(
    r'(?<!<span class="md-nobr">)(' + '|'.join(EMOTICONS) + r')(?!</span>)',
    re.IGNORECASE
)

def on_page_markdown(markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str:
    def replace_emoticon(match):
        emoticon = match.group(1)
        return f'<span class="md-nobr">{emoticon}</span>'

    return pattern.sub(replace_emoticon, markdown)
