"""Parser for 'Name ( URL )' format."""

import logging
from email.message import Message
from typing import List, Set
from bs4 import BeautifulSoup
from .base import BaseEmailParser, ExtractedURL, NAME_URL_PATTERN, logger

class NameUrlParser(BaseEmailParser):
    """Parser for 'Name ( URL )' format, common in Medium text digests."""

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
            # Clean up "In Title..." patterns
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
