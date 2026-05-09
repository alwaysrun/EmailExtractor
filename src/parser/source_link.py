"""Parser for 'source' links."""

from typing import Optional
from .html_text import AbstractHtmlTextParser

class SourceLinkParser(AbstractHtmlTextParser):
    """Parser that specifically extracts URLs marked as 'source' and attempts to find their heading."""

    def _process_anchor(self, anchor) -> Optional[str]:
        title = anchor.get_text(strip=True)
        if title.lower().strip("[]") not in ("source", "read more", "link"):
            return None
        heading = anchor.find_previous(["h1", "h2", "h3", "h4", "strong", "b"])
        if heading:
            return heading.get_text(separator=" ", strip=True)
        return "Unknown Article Title"

    def _accept_text_match(self, content: str, match) -> bool:
        start = match.start()
        context = content[max(0, start-30):start].lower()
        return "source" in context
