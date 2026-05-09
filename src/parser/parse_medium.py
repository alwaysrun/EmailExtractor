"""Medium specific parsing logic."""

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, unquote
from .base import BaseURLFilter, _TITLE_TRAILING_ID_RE
from .name_url import NameUrlParser

# --- Medium Specific Constants ---

_ARTICLE_ID_RE = re.compile(r"[0-9a-f]{10,12}$", re.IGNORECASE)

_NOISY_TITLE_KEYWORDS: frozenset = frozenset({
    "unsubscribe", "help center", "privacy policy", "terms of service",
    "careers", "sent by medium", "control your recommendations",
    "manage subscriptions", "manage your subscription", "manage preferences", 
    "update preferences", "subscription preferences", "sign in", "get the app", 
    "membership", "view in browser", "follow", "more from", "details",
})

_IGNORED_URL_PATTERNS: tuple = (
    re.compile(r"itunes\.apple\.com/.*medium.*id\d+", re.IGNORECASE),
    re.compile(r"play\.google\.com/store/apps/details\?id=com\.medium\.reader", re.IGNORECASE),
)

_NOISY_PATH_PREFIXES: tuple = (
    "/me/", "/jobs-at-medium", "/tag/", "/about",
    "/creators", "/business", "/help", "/policy",
)

_MEDIUM_REDIRECT_PATHS: frozenset = frozenset({
    "/m/global-identity",
    "/m/global-identity-2",
    "/email/fetch",
})


class MediumURLFilter(BaseURLFilter):
    """Specific filtering logic for Medium articles."""

    def is_article_url(self, url: str, title: str) -> bool:
        # First, apply the generic base filtering
        if not super().is_article_url(url, title):
            return False

        # Apply Medium-specific noise filtering
        lower_title = title.lower()
        if any(keyword in lower_title for keyword in _NOISY_TITLE_KEYWORDS):
            return False

        if any(pattern.search(url) for pattern in _IGNORED_URL_PATTERNS):
            return False

        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.strip("/")

        # If it's a medium URL, apply strict rules
        if "medium.com" in netloc:
            if any(path.startswith(prefix.lstrip("/")) for prefix in _NOISY_PATH_PREFIXES):
                return False

            parts = path.split("/")
            if len(parts) >= 2 and parts[0] == "p" and _ARTICLE_ID_RE.match(parts[1]):
                return True

            last_part = parts[-1]
            if "-" in last_part:
                slug_id_part = last_part.split("-")[-1]
                if _ARTICLE_ID_RE.match(slug_id_part):
                    # Exclude profile URLs that look like articles but are just @username
                    if len(parts) == 1 and parts[0].startswith("@"):
                        return False
                    return True
            return False

        # Non-medium URLs are accepted by the base logic
        return True


class MediumParser(NameUrlParser):
    """Parser for Medium emails."""
    def __init__(self):
        super().__init__(url_filter=MediumURLFilter())

    def _resolve_article_url(self, url: str) -> Optional[str]:
        """Override to handle Medium-specific redirect paths."""
        # First call the base resolver for generic redirects
        resolved = super()._resolve_article_url(url)
        if not resolved:
            return None

        parsed = urlparse(resolved)
        netloc = parsed.netloc.lower()
        path_lower = parsed.path.lower()

        # Handle Medium-specific redirect endpoints
        if "medium.com" in netloc and any(path_lower.startswith(p) for p in _MEDIUM_REDIRECT_PATHS):
            qs = parse_qs(parsed.query)
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
        
        # If it's a medium URL, normalize it
        if "medium.com" in netloc:
            return urlunparse((parsed.scheme, netloc, parsed.path.lower(), "", "", ""))

        return resolved
