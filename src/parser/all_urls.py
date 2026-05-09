"""Parser for extracting all URLs."""

from typing import Optional
from .html_text import AbstractHtmlTextParser

class AllUrlsParser(AbstractHtmlTextParser):
    """Parser that extracts all valid URLs found in the email."""

    def _process_anchor(self, anchor) -> Optional[str]:
        title = anchor.get_text(strip=True)
        if not title:
            title = anchor.get("title", "")
        return title

    def _accept_text_match(self, content: str, match) -> bool:
        return True
