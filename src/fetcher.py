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


class EmailFetcher:
    """Handles IMAP connection and email fetching operations."""

    def __init__(self, config: Config) -> None:
        """Initialize EmailFetcher with configuration.

        Args:
            config: Configuration instance containing IMAP settings.
        """
        self._config = config
        self._connection: Optional[imaplib.IMAP4_SSL] = None

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
            self._connection.login(
                user=self._config.email.username,
                password=self._config.email.password,
            )
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
        except (imaplib.IMAP4.error, OSError, ConnectionError):
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
        """
        if not self._connection:
            raise RuntimeError("Not connected to IMAP server")

        self._connection.select("INBOX")

        status, total_email_ids = self._connection.search(None, "UNSEEN")
        total_unread = len(total_email_ids[0].split()) if status == "OK" else 0

        # We search for UNSEEN and FROM if possible, or just UNSEEN
        search_criteria = ["UNSEEN"]
        if filter_config.sender:
            search_criteria.extend(["FROM", filter_config.sender])

        status, email_ids = self._connection.search(None, *search_criteria)

        if status != "OK":
            logger.warning("Failed to search emails for filter: %s", filter_config.name)
            return [], total_unread

        email_id_list = email_ids[0].split()
        max_emails = filter_config.max_emails
        email_id_list = email_id_list[-max_emails:] if len(email_id_list) > max_emails else email_id_list

        emails: List[Message] = []
        for email_id in email_id_list:
            status, email_data = self._connection.fetch(email_id, "(RFC822)")
            if status == "OK":
                raw_email = email_data[0][1]
                message = message_from_bytes(raw_email)
                if self._matches_filters(message, filter_config):
                    emails.append(message)

        logger.info(
            "Filter '%s': Fetched %d emails matching criteria (total unread: %d)",
            filter_config.name, len(emails), total_unread
        )
        return emails, total_unread

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
