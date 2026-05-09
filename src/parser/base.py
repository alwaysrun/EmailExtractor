"""Base classes and core parsing logic for EmailExtractor."""

import dataclasses
import logging
import quopri
import re
from abc import ABC, abstractmethod
from email.message import Message
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse, parse_qs
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# --- Core Constants ---

URL_PATTERN = re.compile(
    r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.?=%&\-+#@!$'()*+,;:\[\]]*"
)

NAME_URL_PATTERN = re.compile(r"([^\n()]+?)\s*\(\s*(https://[^\s)]+)\s*\)")

_TITLE_TRAILING_ID_RE = re.compile(r"\s+[0-9A-Fa-f]{10,12}\s*$")


@dataclasses.dataclass
class ExtractedURL:
    """Represents an extracted URL with its title."""
    url: str
    title: str
    email_subject: str
    email_sender: str
    email_date: str


# --- URL Filter Hierarchy ---

class URLFilter(ABC):
    """Base interface for URL filters."""

    @abstractmethod
    def is_article_url(self, url: str, title: str) -> bool:
        """Return True if the URL and title represent a valid article to extract."""
        pass


class BaseURLFilter(URLFilter):
    """Common filtering logic for all sources."""

    def is_article_url(self, url: str, title: str) -> bool:
        # Basic check: empty path usually means not an article
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return False

        return True


# --- Email Parser Hierarchy ---

class BaseEmailParser(ABC):
    """Base class for email parsers."""

    def __init__(self, url_filter: Optional[URLFilter] = None):
        self.url_filter = url_filter or BaseURLFilter()

    @abstractmethod
    def parse_email(self, message: Message) -> List[ExtractedURL]:
        """Parse an email message and extract URLs."""
        pass

    def _is_article_url(self, url: str, title: str) -> bool:
        """Delegate to the injected URL filter."""
        return self.url_filter.is_article_url(url, title)

    def _extract_text_body(self, message: Message) -> Optional[str]:
        text_body, _ = self._extract_text_body_with_encoding(message)
        return text_body

    def _extract_html_body(self, message: Message) -> Optional[str]:
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/html":
                    content_disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in content_disposition:
                        continue
                    return self._decode_payload(part)
            return None
        if message.get_content_type() == "text/html":
            return self._decode_payload(message)
        return None

    def _extract_text_body_with_encoding(
        self, message: Message
    ) -> Tuple[Optional[str], bool]:
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                transfer_encoding = str(part.get("Content-Transfer-Encoding", "")).lower()

                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    body = self._decode_payload(part)
                    is_qp = transfer_encoding == "quoted-printable"
                    return body, is_qp
            return None, False
        else:
            transfer_encoding = str(message.get("Content-Transfer-Encoding", "")).lower()
            body = self._decode_payload(message)
            is_qp = transfer_encoding == "quoted-printable"
            return body, is_qp

    @staticmethod
    def _decode_quoted_printable(content: str) -> str:
        try:
            encoded = content.encode("utf-8")
            decoded = quopri.decodestring(encoded)
            return decoded.decode("utf-8", errors="replace")
        except Exception:
            return content

    @staticmethod
    def _get_base_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _get_header(self, message: Message, header_name: str) -> str:
        from email.header import decode_header
        header_value = message.get(header_name, "")
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(part)
        return "".join(decoded_parts)

    def _extract_body(self, message: Message) -> Optional[str]:
        if message.is_multipart():
            html_body = None
            text_body = None
            for part in message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in content_disposition:
                    continue
                if content_type == "text/html":
                    html_body = self._decode_payload(part)
                elif content_type == "text/plain" and text_body is None:
                    text_body = self._decode_payload(part)
            return html_body or text_body
        else:
            return self._decode_payload(message)

    @staticmethod
    def _decode_payload(part: Message) -> Optional[str]:
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return None
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        except Exception as e:
            logger.warning("Failed to decode payload: %s", e)
            return None

    @staticmethod
    def _is_html_content(content: str) -> bool:
        html_indicators = ["<html", "<body", "<div", "<a ", "<p>"]
        return any(indicator in content.lower() for indicator in html_indicators)

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            result = urlparse(url)
            return result.scheme in ("http", "https") and bool(result.netloc)
        except Exception:
            return False

    @staticmethod
    def _clean_anchor_title(raw_title: str) -> str:
        title = " ".join(raw_title.split())
        title = _TITLE_TRAILING_ID_RE.sub("", title).strip()
        return title

    def _resolve_article_url(self, url: str) -> Optional[str]:
        from urllib.parse import unquote
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc:
            return None

        qs = parse_qs(parsed.query)
        redirect_params = ["redirectUrl", "url", "target", "link", "goto"]
        for param in redirect_params:
            if param in qs:
                target = unquote(qs[param][0])
                if self._is_valid_url(target):
                    target_parsed = urlparse(target)
                    return urlunparse((
                        target_parsed.scheme,
                        target_parsed.netloc.lower(),
                        target_parsed.path.lower(),
                        "", "", "",
                    ))

        # Note: Medium-specific redirect handling removed here and moved to MediumURLFilter if needed,
        # but the core resolver remains generic.
        return urlunparse((parsed.scheme, netloc, parsed.path, "", parsed.query, ""))

    @staticmethod
    def _extract_title_from_url(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            return path.split("/")[-1].replace("-", " ").replace("_", " ").title()
        return parsed.netloc
