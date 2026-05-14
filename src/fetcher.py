"""Email fetcher module for IMAP operations."""

import imaplib
import logging
import time
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from typing import List, Optional, Tuple

from src.config import Config, FilterConfig

logger = logging.getLogger(__name__)

DEFAULT_RECONNECT_DELAY_SECONDS = 5
DEFAULT_MAX_RECONNECT_RETRIES = 3
# Gmail closes connections mid-FETCH on large emails (Medium newsletters can be
# 200-600 KB). A 30-second socket timeout converts a silent TCP EOF into a clean
# IMAP4.abort so the retry logic fires promptly instead of hanging indefinitely.
IMAP_SOCKET_TIMEOUT_SECONDS = 30


class EmailFetcher:
    """Handles IMAP connection and email fetching operations."""

    def __init__(self, config: Config) -> None:
        """Initialize EmailFetcher with configuration.

        Args:
            config: Configuration instance containing IMAP settings.
        """
        self._config = config
        self._connection: Optional[imaplib.IMAP4_SSL] = None
        # Track the last selected mailbox to skip redundant SELECT round-trips
        # between consecutive filter calls (each SELECT pushes EXISTS/RECENT
        # for the entire mailbox, which is noisy on large inboxes).
        self._selected_mailbox: Optional[str] = None

    def connect(self) -> None:
        """Establish IMAP connection and authenticate.

        Raises:
            ConnectionError: If connection or authentication fails.
        """
        try:
            self._connection = imaplib.IMAP4_SSL(
                host=self._config.email.imap_server,
                port=self._config.email.imap_port,
            )
            # Apply socket timeout BEFORE login so all subsequent commands
            # (including the TLS handshake responses) honour it.
            self._connection.sock.settimeout(IMAP_SOCKET_TIMEOUT_SECONDS)
            self._connection.login(
                user=self._config.email.username,
                password=self._config.email.password,
            )
            self._selected_mailbox = None
            logger.info("Successfully connected to IMAP server")
        except imaplib.IMAP4.error as e:
            self._connection = None
            raise ConnectionError(f"IMAP connection failed: {e}") from e

    def disconnect(self) -> None:
        """Close IMAP connection gracefully."""
        if self._connection:
            try:
                self._connection.close()
            except imaplib.IMAP4.error:
                pass
            try:
                self._connection.logout()
            except imaplib.IMAP4.error:
                pass
            self._connection = None
            self._selected_mailbox = None
            logger.info("Disconnected from IMAP server")

    def is_connected(self) -> bool:
        """Check if IMAP connection is still alive.

        Returns:
            True if connection is alive, False otherwise.
        """
        if not self._connection:
            return False
        try:
            status, _ = self._connection.noop()
            return status == "OK"
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, ConnectionError):
            # IMAP4.abort covers socket-level EOF / server-side session close
            self._connection = None
            return False

    def ensure_connected(
        self,
        max_retries: int = DEFAULT_MAX_RECONNECT_RETRIES,
        retry_delay: float = DEFAULT_RECONNECT_DELAY_SECONDS,
    ) -> None:
        """Ensure IMAP connection is alive, reconnect if necessary.

        Args:
            max_retries: Maximum number of reconnection attempts.
            retry_delay: Delay in seconds between retry attempts.

        Raises:
            ConnectionError: If connection cannot be established after retries.
        """
        if self.is_connected():
            return

        logger.warning("IMAP connection lost, attempting to reconnect...")
        self._connection = None

        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                self.connect()
                logger.info("Reconnection successful on attempt %d/%d", attempt, max_retries)
                return
            except ConnectionError as e:
                last_error = e
                logger.warning(
                    "Reconnection attempt %d/%d failed: %s",
                    attempt, max_retries, e
                )
                if attempt < max_retries:
                    logger.info("Waiting %.1f seconds before next attempt...", retry_delay)
                    time.sleep(retry_delay)

        raise ConnectionError(
            f"Failed to reconnect after {max_retries} attempts: {last_error}"
        )

    def __enter__(self) -> "EmailFetcher":
        """Context manager entry - establishes connection."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes connection."""
        self.disconnect()

    def count_total_unread_emails(self) -> int:
        """Count total unread emails in inbox.

        Returns:
            Total number of unread emails.

        Raises:
            RuntimeError: If not connected to IMAP server.
        """
        if not self._connection:
            raise RuntimeError("Not connected to IMAP server")

        self._connection.select("INBOX")
        status, email_ids = self._connection.search(None, "UNSEEN")

        if status != "OK":
            logger.warning("Failed to count unread emails")
            return 0

        return len(email_ids[0].split())

    def fetch_unread_emails(self, filter_config: "FilterConfig") -> Tuple[List[Message], int]:
        """Fetch unread emails matching filter criteria.

        Args:
            filter_config: Specific filter configuration to apply.

        Returns:
            Tuple of (List of email Message objects matching the criteria, total unread count).

        Raises:
            RuntimeError: If not connected to IMAP server.
            ConnectionError: If reconnection after session drop fails.
        """
        # Attempt the operation; on abort (server-side EOF / session close between
        # filters) reconnect once and retry before propagating the error.
        for attempt in range(2):
            try:
                return self._do_fetch_unread_emails(filter_config)
            except imaplib.IMAP4.abort as exc:
                if attempt == 0:
                    logger.warning(
                        "Filter '%s': IMAP session dropped (EOF), reconnecting... [%s]",
                        filter_config.name, exc,
                    )
                    self._connection = None
                    # Reset mailbox state: after reconnect the new session has no
                    # selected mailbox, so _do_fetch_unread_emails must re-issue SELECT.
                    self._selected_mailbox = None
                    self.ensure_connected()
                else:
                    raise ConnectionError(
                        f"Filter '{filter_config.name}': IMAP session dropped and reconnect failed: {exc}"
                    ) from exc
        # Unreachable; satisfies type checker.
        raise RuntimeError("Unexpected execution path in fetch_unread_emails")

    def _do_fetch_unread_emails(self, filter_config: "FilterConfig") -> Tuple[List[Message], int]:
        """Internal implementation of fetch_unread_emails (single attempt).

        Separated so that fetch_unread_emails can transparently retry on abort.

        Raises:
            RuntimeError: If not connected to IMAP server.
            imaplib.IMAP4.abort: On socket-level session close (EOF).
        """
        if not self._connection:
            raise RuntimeError("Not connected to IMAP server")

        # Skip SELECT if INBOX is already selected: every SELECT causes Gmail to
        # push EXISTS/RECENT counts for the entire mailbox, which is expensive
        # and contributes to the connection instability on large inboxes.
        if self._selected_mailbox != "INBOX":
            self._connection.select("INBOX")
            self._selected_mailbox = "INBOX"

        # Single SEARCH for all UNSEEN emails to count total unread.
        status, total_email_ids = self._connection.search(None, "UNSEEN")
        total_unread = len(total_email_ids[0].split()) if status == "OK" else 0

        # Build filtered search criteria (UNSEEN + optional FROM filter).
        search_criteria = ["UNSEEN"]
        if filter_config.sender:
            search_criteria.extend(["FROM", filter_config.sender])

        # Re-use the already-fetched list when no sender filter is active to
        # avoid an extra round-trip; otherwise issue a narrowed search.
        if filter_config.sender:
            status, email_ids = self._connection.search(None, *search_criteria)
            if status != "OK":
                logger.warning("Failed to search emails for filter: %s", filter_config.name)
                return [], total_unread
            email_id_list = email_ids[0].split()
            # When the server-side FROM search returns nothing but there are unread
            # emails, the configured sender address likely doesn't match the actual
            # From header.  Log all UNSEEN senders at WARNING level so the user can
            # verify and correct config.toml without resorting to a mail client.
            if not email_id_list and total_unread > 0:
                self._log_unseen_senders(
                    total_email_ids[0].split(), filter_config.name, filter_config.sender
                )
        else:
            email_id_list = total_email_ids[0].split() if status == "OK" else []

        max_emails = filter_config.max_emails
        email_id_list = email_id_list[-max_emails:] if len(email_id_list) > max_emails else email_id_list

        emails: List[Message] = []
        # Track IDs of emails that pass the filter so we can mark them \Seen
        # only after the entire fetch+filter pass succeeds.  Emails that do NOT
        # match the filter remain UNSEEN on the server.
        matched_ids: List[bytes] = []

        for email_id in email_id_list:
            # Use BODY.PEEK[] instead of RFC822: both return the full RFC 822
            # message, but PEEK does NOT set the \Seen flag.  This is critical
            # for retry-after-reconnect: if the session drops mid-fetch, the
            # second attempt's SEARCH UNSEEN will still find these emails.
            status, email_data = self._connection.fetch(email_id, "(BODY.PEEK[])")
            if status != "OK" or not email_data:
                logger.debug("Filter '%s': FETCH returned non-OK for id %s, skipping", filter_config.name, email_id)
                continue
            # imaplib may return plain bytes (e.g. b'1 (BODY[] NIL)') for
            # deleted/empty messages instead of the expected (header, body) tuple.
            # Indexing plain bytes with [1] yields an int, which breaks message_from_bytes.
            first_part = email_data[0]
            if not isinstance(first_part, tuple) or len(first_part) < 2 or not isinstance(first_part[1], (bytes, bytearray)):
                logger.debug("Filter '%s': Unexpected FETCH response structure for id %s, skipping", filter_config.name, email_id)
                continue
            raw_email = first_part[1]
            message = message_from_bytes(raw_email)
            if self._matches_filters(message, filter_config):
                emails.append(message)
                matched_ids.append(email_id)

        # Mark all matched emails as \Seen in a single STORE round-trip.
        # Unmatched emails remain UNSEEN so other filters or future runs can
        # still discover them.
        if matched_ids:
            self._mark_as_seen(matched_ids, filter_config.name)

        logger.info(
            "Filter '%s': Fetched %d emails matching criteria (total unread: %d)",
            filter_config.name, len(emails), total_unread
        )
        return emails, total_unread

    def _log_unseen_senders(
        self,
        all_unseen_ids: "List[bytes]",
        filter_name: str,
        configured_sender: str,
    ) -> None:
        """Fetch From headers of all UNSEEN emails and log them as a diagnostic.

        Called exclusively when the server-side FROM search returns no results
        despite there being unread emails, indicating a sender address mismatch
        between config.toml and the actual message header.

        Args:
            all_unseen_ids: All UNSEEN message IDs (bytes) from the prior SEARCH.
            filter_name: Filter name for log context.
            configured_sender: The sender value from FilterConfig for comparison.
        """
        if not all_unseen_ids or not self._connection:
            return

        logger.warning(
            "Filter '%s': IMAP FROM search for '%s' matched 0/%d unread emails. "
            "Configured sender likely doesn't match the actual From header. "
            "Fetching From headers of all %d UNSEEN emails for diagnosis...",
            filter_name, configured_sender, len(all_unseen_ids), len(all_unseen_ids),
        )

        # Fetch only the From header to minimise bandwidth.  BODY.PEEK does NOT
        # set \Seen, so unmatched emails remain eligible for future runs.
        # Limit to 5 messages to keep latency low in diagnostic mode.
        sample_ids = all_unseen_ids[:5]
        id_set = b",".join(sample_ids)
        try:
            status, data = self._connection.fetch(id_set, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError) as exc:
            logger.warning(
                "Filter '%s': Could not fetch senders for diagnosis: %s", filter_name, exc
            )
            return

        if status != "OK" or not data:
            return

        seen_values: set = set()
        for item in data:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            raw: bytes = item[1] if isinstance(item[1], bytes) else b""
            for line in raw.splitlines():
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.lower().startswith("from:"):
                    from_value = decoded[5:].strip()
                    if from_value not in seen_values:
                        seen_values.add(from_value)
                        logger.warning(
                            "Filter '%s': UNSEEN From → '%s'  (configured: '%s')",
                            filter_name, from_value, configured_sender,
                        )

    def _mark_as_seen(self, email_ids: "List[bytes]", filter_name: str) -> None:
        """Mark the given email IDs as \\Seen on the IMAP server.

        Uses a single STORE command with a comma-separated ID set for efficiency.
        A failure here is logged but never re-raised: the caller already has the
        message data and must not lose it over a flag-update error.

        Args:
            email_ids: List of IMAP message IDs (as bytes) to mark as seen.
            filter_name: Filter name used only for log context.
        """
        if not self._connection:
            logger.warning(
                "Filter '%s': Cannot mark %d email(s) as seen - not connected",
                filter_name, len(email_ids)
            )
            return

        # Build a comma-separated sequence set (e.g. b"3,7,12").
        id_set = b",".join(email_ids)
        try:
            status, _ = self._connection.store(id_set, "+FLAGS", r"(\Seen)")
            if status == "OK":
                logger.info(
                    "Filter '%s': Marked %d email(s) as seen",
                    filter_name, len(email_ids)
                )
            else:
                logger.warning(
                    "Filter '%s': STORE +FLAGS returned non-OK status for %d email(s)",
                    filter_name, len(email_ids)
                )
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError) as exc:
            logger.warning(
                "Filter '%s': Failed to mark %d email(s) as seen: %s",
                filter_name, len(email_ids), exc
            )

    def _matches_filters(self, message: Message, filter_config: "FilterConfig") -> bool:
        """Check if email matches configured filters.

        Args:
            message: Email message to check.
            filter_config: Filter configuration to apply.

        Returns:
            True if email matches all filter criteria.
        """
        sender = self._decode_header(message.get("From", ""))
        subject = self._decode_header(message.get("Subject", ""))
        logger.debug("Checking email - Sender: '%s', Subject: '%s'", sender, subject)

        # Sender check (already done by IMAP search but double check for safety/flexibility)
        sender_match = True
        if filter_config.sender:
            sender_match = filter_config.sender.lower() in sender.lower()
        
        if not sender_match:
            return False

        # Title keywords check
        # "if title_keywords, only the email from the sender, that include any of the title_keywords in title"
        # "if title_keywords is empty, all email from the sender is accept"
        if not filter_config.title_keywords:
            return True
        
        keyword_match = any(
            keyword.lower() in subject.lower()
            for keyword in filter_config.title_keywords
        )
        
        return keyword_match

    @staticmethod
    def _decode_header(header_value: str) -> str:
        """Decode email header value.

        Args:
            header_value: Raw header value to decode.

        Returns:
            Decoded header string.
        """
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(part)

        return "".join(decoded_parts)
