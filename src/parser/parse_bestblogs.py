"""Parser for BestBlogs.dev subscription emails (Gino)."""

import re
from typing import List, Set, Optional
from urllib.parse import unquote
from bs4 import BeautifulSoup
from .base import BaseEmailParser, ExtractedURL, logger

AWSTRACK_PATTERN = re.compile(r"https?://[a-z0-9\-]+\.r\.[a-z0-9\-]+\.awstrack\.me/L0/([^/]+)/")
BESTBLOGS_PATH_PATTERN = re.compile(r"bestblogs\.dev/(article|video|podcast)/")


class BestBlogsParser(BaseEmailParser):
    """Parser for BestBlogs.dev subscription emails (Gino)."""

    def _extract_bestblogs_url_from_awstrack(self, url: str) -> Optional[str]:
        """Extract the actual bestblogs.dev URL from an AWS tracking link.
        
        AWS tracking links have the format:
        https://xxx.r.us-west-2.awstrack.me/L0/<url-encoded-target>/...tracking-id...
        
        Args:
            url: The awstrack.me tracking URL.
            
        Returns:
            The decoded bestblogs.dev URL, or None if not a valid tracking link.
        """
        match = AWSTRACK_PATTERN.match(url)
        if not match:
            return None
        
        encoded_target = match.group(1)
        try:
            decoded_url = unquote(encoded_target)
            if BESTBLOGS_PATH_PATTERN.search(decoded_url):
                return self._get_base_url(decoded_url)
        except Exception as e:
            logger.debug("Failed to decode awstrack URL: %s", e)
        
        return None

    def _extract_url_from_anchor(self, anchor, seen_urls: Set[str]) -> Optional[str]:
        """Extract a bestblogs.dev URL from an anchor element.
        
        Handles both direct bestblogs.dev links and awstrack.me tracking links.
        
        Args:
            anchor: BeautifulSoup anchor element.
            seen_urls: Set of already seen URLs for deduplication.
            
        Returns:
            The clean bestblogs.dev URL, or None if not valid/already seen.
        """
        url = anchor.get("href", "").strip()
        if not url:
            return None
        
        clean_url = None
        
        if "awstrack.me" in url:
            clean_url = self._extract_bestblogs_url_from_awstrack(url)
        elif BESTBLOGS_PATH_PATTERN.search(url):
            clean_url = self._get_base_url(url)
        
        if clean_url and clean_url not in seen_urls:
            return clean_url
        
        return None

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
            text_matches = re.finditer(
                r"(?:^|\n)\s*(\d+)?(.*?)(https?://bestblogs\.dev/(?:article|video|podcast)/[^\s?]+)",
                text_body
            )
            for match in text_matches:
                title = match.group(2).strip()
                url = match.group(3).strip()
                
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

        html_body = self._extract_html_body(message)
        if html_body:
            soup = BeautifulSoup(html_body, "lxml")
            for anchor in soup.find_all("a", href=True):
                clean_url = self._extract_url_from_anchor(anchor, seen_urls)
                if not clean_url:
                    continue
                
                title = self._clean_anchor_title(anchor.get_text(strip=True))
                
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

        if not results:
            logger.warning(
                "BestBlogs parser found 0 URLs for email: %s. "
                "text_body=%s, html_body=%s",
                subject,
                "present" if text_body else "missing",
                "present" if html_body else "missing"
            )
            if html_body:
                soup = BeautifulSoup(html_body, "lxml")
                all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
                awstrack_hrefs = [h for h in all_hrefs if "awstrack.me" in h]
                logger.debug(
                    "Total anchors: %d, awstrack.me anchors: %d",
                    len(all_hrefs), len(awstrack_hrefs)
                )
                if awstrack_hrefs:
                    logger.debug("Sample awstrack hrefs: %s", awstrack_hrefs[:3])
        else:
            logger.info("Extracted %d URLs from BestBlogs email: %s", len(results), subject)
        return results
