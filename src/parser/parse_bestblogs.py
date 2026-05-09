"""Parser for BestBlogs.dev subscription emails (Gino)."""

import re
from typing import List, Set
from bs4 import BeautifulSoup
from .base import BaseEmailParser, ExtractedURL, logger

class BestBlogsParser(BaseEmailParser):
    """Parser for BestBlogs.dev subscription emails (Gino)."""

    def parse_email(self, message) -> List[ExtractedURL]:
        subject = self._get_header(message, "Subject")
        sender = self._get_header(message, "From")
        date = self._get_header(message, "Date")

        text_body, is_qp_encoded = self._extract_text_body_with_encoding(message)
        if text_body and is_qp_encoded:
            text_body = self._decode_quoted_printable(text_body)

        results: List[ExtractedURL] = []
        seen_urls: Set[str] = set()

        if text_body:
            # Pattern: [Number]Title URL
            # Example: 1KARPATHY 最新访谈... https://bestblogs.dev/article/87929773...
            # Supports /article/, /video/, and /podcast/ paths.
            text_matches = re.finditer(r"(?:^|\n)\s*(\d+)?(.*?)(https?://bestblogs\.dev/(?:article|video|podcast)/[^\s?]+)", text_body)
            for match in text_matches:
                title = match.group(2).strip()
                url = match.group(3).strip()
                
                # Clean title: remove leading non-alphanumeric chars if they look like bullets/emojis
                # but keep Chinese characters.
                title = re.sub(r"^[^\w\u4e00-\u9fa5]+", "", title).strip()
                
                if url not in seen_urls:
                    seen_urls.add(url)
                    results.append(ExtractedURL(
                        url=url,
                        title=title or self._extract_title_from_url(url),
                        email_subject=subject,
                        email_sender=sender,
                        email_date=date
                    ))

        # If text parsing didn't find everything or as a fallback
        html_body = self._extract_html_body(message)
        if html_body:
            soup = BeautifulSoup(html_body, "lxml")
            for anchor in soup.find_all("a", href=True):
                url = anchor["href"].strip()
                
                # We care about articles, videos, and podcasts from bestblogs
                if any(path in url for path in ("bestblogs.dev/article/", "bestblogs.dev/video/", "bestblogs.dev/podcast/")):
                    # Clean the URL to remove tracking params for deduplication
                    clean_url = self._get_base_url(url)
                    if clean_url in seen_urls:
                        continue
                        
                    title = self._clean_anchor_title(anchor.get_text(strip=True))
                    
                    # BestBlogs HTML emails often have a picture/title link and a "Read More" link
                    # If the current link text is generic, look for a heading nearby
                    if not title or title.lower() in ("read more", "view article", "full text", "read online"):
                        heading = anchor.find_previous(["h1", "h2", "h3", "h4", "strong", "b"])
                        if heading:
                            title = heading.get_text(strip=True)
                    
                    if not title:
                        title = self._extract_title_from_url(clean_url)

                    seen_urls.add(clean_url)
                    results.append(ExtractedURL(
                        url=clean_url,
                        title=title,
                        email_subject=subject,
                        email_sender=sender,
                        email_date=date
                    ))

        logger.debug("Extracted %d URLs from BestBlogs email: %s", len(results), subject)
        return results
