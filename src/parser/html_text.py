"""Base class for HTML and Text based parsers."""

import logging
from abc import abstractmethod
from email.message import Message
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseEmailParser, ExtractedURL, URL_PATTERN, logger

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
