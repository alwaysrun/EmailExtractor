"""Email parser module for URL extraction."""

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

URL_PATTERN = re.compile(
    r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.?=%&\-+#@!$'()*+,;:\[\]]*"
)

NAME_URL_PATTERN = re.compile(r"([^\n()]+?)\s*\(\s*(https://[^\s)]+)\s*\)")

_ARTICLE_ID_RE = re.compile(r"[0-9a-f]{10,12}$", re.IGNORECASE)
_TITLE_TRAILING_ID_RE = re.compile(r"\s+[0-9A-Fa-f]{10,12}\s*$")

_NOISY_TITLE_KEYWORDS: frozenset = frozenset({
    "unsubscribe", "help center", "privacy policy", "terms of service",
    "careers", "sent by medium", "control your recommendations",
    "manage subscriptions", "manage your subscription", "manage preferences", 
    "update preferences", "subscription preferences", "sign in", "get the app", 
    "membership", "view in browser", "follow", "more from",
})

_NOISY_PATH_PREFIXES: tuple = (
    "/me/", "/jobs-at-medium", "/tag/", "/about",
    "/creators", "/business", "/help", "/policy",
)

_MEDIUM_REDIRECT_PATHS: frozenset = frozenset({
    "/m/global-identity",
    "/m/global-identity-2",
    "/email/fetch",
})


@dataclasses.dataclass
class ExtractedURL:
    """Represents an extracted URL with its title."""
    url: str
    title: str
    email_subject: str
    email_sender: str
    email_date: str


class BaseEmailParser(ABC):
    """Base class for email parsers."""

    @abstractmethod
    def parse_email(self, message: Message) -> List[ExtractedURL]:
        """Parse an email message and extract URLs."""
        pass

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
        from urllib.parse import unquote, parse_qs
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

        path_lower = parsed.path.lower()
        is_medium_redirect = "medium.com" in netloc and any(path_lower.startswith(p) for p in _MEDIUM_REDIRECT_PATHS)
        if is_medium_redirect:
            redirect_targets = qs.get("redirectUrl") or qs.get("url") or []
            if redirect_targets:
                real_url = unquote(redirect_targets[0])
                real_parsed = urlparse(real_url)
                return urlunparse((
                    real_parsed.scheme,
                    real_parsed.netloc.lower(),
                    real_parsed.path.lower(),
                    "", "", "",
                ))
            return None

        if "medium.com" in netloc:
            return urlunparse((parsed.scheme, netloc, parsed.path.lower(), "", "", ""))

        return urlunparse((parsed.scheme, netloc, parsed.path, "", parsed.query, ""))

    def _is_article_url(self, url: str, title: str) -> bool:
        lower_title = title.lower()
        if any(keyword in lower_title for keyword in _NOISY_TITLE_KEYWORDS):
            return False

        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.strip("/")
        if not path:
            return False

        if "medium.com" in netloc:
            if any(path.startswith(prefix.lstrip("/")) for prefix in _NOISY_PATH_PREFIXES):
                return False

        if "medium.com" not in netloc:
            return True

        parts = path.split("/")
        last_part = parts[-1]

        if len(parts) >= 2 and parts[0] == "p" and _ARTICLE_ID_RE.match(parts[1]):
            return True

        if "-" in last_part:
            slug_id_part = last_part.split("-")[-1]
            if _ARTICLE_ID_RE.match(slug_id_part):
                if len(parts) == 1 and parts[0].startswith("@"):
                    return False
                return True

        return False

    @staticmethod
    def _extract_title_from_url(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            return path.split("/")[-1].replace("-", " ").replace("_", " ").title()
        return parsed.netloc


class MediumParser(BaseEmailParser):
    """Parser specifically for Medium's Name ( URL ) format."""

    def parse_email(self, message: Message) -> List[ExtractedURL]:
        subject = self._get_header(message, "Subject")
        sender = self._get_header(message, "From")
        date = self._get_header(message, "Date")

        text_body, is_qp_encoded = self._extract_text_body_with_encoding(message)
        if text_body:
            if is_qp_encoded:
                text_body = self._decode_quoted_printable(text_body)

            results = self._extract_from_text_name_url(text_body, subject, sender, date)
            if results:
                logger.debug(
                    "Extracted %d unique URLs via text/plain from email: %s",
                    len(results), subject,
                )
                return results
            logger.debug(
                "No matches from text/plain for '%s', falling back to HTML body.", subject
            )

        html_body = self._extract_html_body(message)
        if not html_body:
            logger.warning("No usable body content found in email: %s", subject)
            return []

        results = self._extract_from_html_anchors(html_body, subject, sender, date)
        logger.debug(
            "Extracted %d unique URLs via HTML body from email: %s", len(results), subject
        )
        return results

    def _extract_from_text_name_url(
        self, text_body: str, subject: str, sender: str, date: str
    ) -> List[ExtractedURL]:
        matches = NAME_URL_PATTERN.findall(text_body)
        seen_base_urls: Set[str] = set()
        results: List[ExtractedURL] = []

        for name, url in matches:
            name = name.strip()
            if name.lower().startswith("in") and len(name) > 2 and name[2].isupper():
                name = name[2:].strip()

            article_url = self._resolve_article_url(url)
            if not article_url or not self._is_article_url(article_url, name):
                continue

            base_url = self._get_base_url(article_url)
            if base_url not in seen_base_urls:
                seen_base_urls.add(base_url)
                results.append(
                    ExtractedURL(
                        url=article_url,
                        title=name,
                        email_subject=subject,
                        email_sender=sender,
                        email_date=date,
                    )
                )
        return results

    def _extract_from_html_anchors(
        self, html_body: str, subject: str, sender: str, date: str
    ) -> List[ExtractedURL]:
        soup = BeautifulSoup(html_body, "lxml")
        seen_base_urls: Set[str] = set()
        results: List[ExtractedURL] = []

        for anchor in soup.find_all("a", href=True):
            raw_url = anchor["href"].strip()
            if not self._is_valid_url(raw_url):
                continue

            article_url = self._resolve_article_url(raw_url)
            if not article_url:
                continue

            title = self._clean_anchor_title(
                anchor.get_text(separator=" ", strip=True)
                or anchor.get("title", "")
                or self._extract_title_from_url(article_url)
            )

            if not self._is_article_url(article_url, title):
                continue

            base_url = self._get_base_url(article_url)
            if base_url not in seen_base_urls:
                seen_base_urls.add(base_url)
                results.append(
                    ExtractedURL(
                        url=article_url,
                        title=title,
                        email_subject=subject,
                        email_sender=sender,
                        email_date=date,
                    )
                )
        return results


class AbstractHtmlTextParser(BaseEmailParser):
    """Base class for parsers that extract URLs from generic HTML and Text bodies."""

    def parse_email(self, message: Message) -> List[ExtractedURL]:
        subject = self._get_header(message, "Subject")
        sender = self._get_header(message, "From")
        date = self._get_header(message, "Date")

        body = self._extract_body(message)
        if not body:
            logger.warning("No body content found in email: %s", subject)
            return []

        urls = []
        seen_urls = set()

        if self._is_html_content(body):
            urls.extend(self._extract_urls_from_html(body, seen_urls))
        else:
            urls.extend(self._extract_urls_from_text(body, seen_urls))

        extracted_urls: List[ExtractedURL] = []
        for url, title in urls:
            if not self._is_article_url(url, title):
                continue
            extracted_urls.append(
                ExtractedURL(
                    url=url,
                    title=title or self._extract_title_from_url(url),
                    email_subject=subject,
                    email_sender=sender,
                    email_date=date,
                )
            )

        logger.debug("Extracted %d URLs from email: %s", len(extracted_urls), subject)
        return extracted_urls

    def _extract_urls_from_html(self, content: str, seen_urls: set) -> List[tuple]:
        urls = []
        soup = BeautifulSoup(content, "lxml")
        for anchor in soup.find_all("a", href=True):
            url = anchor["href"].strip()
            if not self._is_valid_url(url) or url in seen_urls:
                continue

            title = self._process_anchor(anchor)
            if title is not None:
                seen_urls.add(url)
                urls.append((url, title))
        return urls

    def _extract_urls_from_text(self, content: str, seen_urls: set) -> List[tuple]:
        urls = []
        for match in URL_PATTERN.finditer(content):
            url = match.group(0)
            if not self._is_valid_url(url) or url in seen_urls:
                continue

            if self._accept_text_match(content, match):
                seen_urls.add(url)
                urls.append((url, ""))
        return urls

    @abstractmethod
    def _process_anchor(self, anchor) -> Optional[str]:
        pass

    @abstractmethod
    def _accept_text_match(self, content: str, match) -> bool:
        pass


class AllUrlsParser(AbstractHtmlTextParser):
    """Parser that extracts all valid URLs found in the email."""

    def _process_anchor(self, anchor) -> Optional[str]:
        title = anchor.get_text(strip=True)
        if not title:
            title = anchor.get("title", "")
        return title

    def _accept_text_match(self, content: str, match) -> bool:
        return True


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


class ParserFactory:
    """Factory to create the appropriate EmailParser strategy."""

    @staticmethod
    def create(extract_format: str) -> BaseEmailParser:
        if extract_format == "name_url":
            return MediumParser()
        elif extract_format == "all_urls":
            return AllUrlsParser()
        elif extract_format == "source_link":
            return SourceLinkParser()
        else:
            logger.warning("Unknown extract_format '%s', falling back to 'name_url'", extract_format)
            return MediumParser()

# For backwards compatibility if any other module imports EmailParser directly
# We can make EmailParser behave like a factory or alias to ParserFactory
class EmailParser:
    def __new__(cls, extract_format: str = "name_url"):
        return ParserFactory.create(extract_format)
