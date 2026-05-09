"""Network connectivity checker for Gmail IMAP and Gemini CLI."""

import logging
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass
class ConnectivityResult:
    """Result of a connectivity check."""

    service_name: str
    success: bool
    error_message: str = ""


def check_gmail_imap(timeout_seconds: int = 10) -> ConnectivityResult:
    """Check connectivity to Gmail IMAP server.

    Args:
        timeout_seconds: Socket connection timeout in seconds.

    Returns:
        ConnectivityResult indicating success or failure.
    """
    service_name = "Gmail IMAP"
    host = "imap.gmail.com"
    port = 993

    logger.info("Checking connectivity to %s (%s:%d)...", service_name, host, port)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_seconds)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            logger.info("%s connectivity check passed.", service_name)
            return ConnectivityResult(service_name=service_name, success=True)
        else:
            error_msg = f"Connection failed with error code: {result}"
            logger.error("%s connectivity check failed: %s", service_name, error_msg)
            return ConnectivityResult(
                service_name=service_name, success=False, error_message=error_msg
            )

    except socket.timeout:
        error_msg = f"Connection timed out after {timeout_seconds} seconds"
        logger.error("%s connectivity check failed: %s", service_name, error_msg)
        return ConnectivityResult(
            service_name=service_name, success=False, error_message=error_msg
        )
    except socket.gaierror as e:
        error_msg = f"DNS resolution failed: {e}"
        logger.error("%s connectivity check failed: %s", service_name, error_msg)
        return ConnectivityResult(
            service_name=service_name, success=False, error_message=error_msg
        )
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error("%s connectivity check failed: %s", service_name, error_msg)
        return ConnectivityResult(
            service_name=service_name, success=False, error_message=error_msg
        )


def check_gemini_cli(gemini_path: str, timeout_seconds: int = 30) -> ConnectivityResult:
    """Check if Gemini CLI is available and can connect to Gemini API.

    Args:
        gemini_path: Path to the Gemini CLI executable.
        timeout_seconds: Command execution timeout in seconds.

    Returns:
        ConnectivityResult indicating success or failure.
    """
    service_name = "Gemini CLI"

    logger.info("Checking connectivity to %s (path: %s)...", service_name, gemini_path)

    try:
        if gemini_path.lower().endswith(".ps1"):
            ps_command = f'& "{gemini_path}" --version'
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_command,
            ]
            use_shell = False
        else:
            use_shell = sys.platform == "win32"
            cmd = [gemini_path, "--version"]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=use_shell,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.wait(timeout=5)

            error_msg = f"Command timed out after {timeout_seconds} seconds"
            logger.error("%s connectivity check failed: %s", service_name, error_msg)
            return ConnectivityResult(
                service_name=service_name, success=False, error_message=error_msg
            )

        if proc.returncode == 0:
            version_info = stdout.strip() if stdout else "unknown version"
            logger.info("%s connectivity check passed. Version: %s", service_name, version_info)
            return ConnectivityResult(service_name=service_name, success=True)
        else:
            error_msg = f"Command failed with exit code {proc.returncode}"
            if stderr:
                error_msg += f": {stderr.strip()}"
            logger.error("%s connectivity check failed: %s", service_name, error_msg)
            return ConnectivityResult(
                service_name=service_name, success=False, error_message=error_msg
            )

    except FileNotFoundError:
        error_msg = f"Gemini CLI executable not found at '{gemini_path}'"
        logger.error("%s connectivity check failed: %s", service_name, error_msg)
        return ConnectivityResult(
            service_name=service_name, success=False, error_message=error_msg
        )
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error("%s connectivity check failed: %s", service_name, error_msg)
        return ConnectivityResult(
            service_name=service_name, success=False, error_message=error_msg
        )


def check_network_connectivity(
    gemini_path: str,
    max_retries: int = 3,
    retry_interval_seconds: int = 15,
) -> Tuple[bool, str]:
    """Check both Gmail IMAP and Gemini CLI connectivity with retries.

    Args:
        gemini_path: Path to the Gemini CLI executable.
        max_retries: Maximum number of retry attempts (default: 3).
        retry_interval_seconds: Interval between retries in seconds (default: 15).

    Returns:
        Tuple of (success: bool, error_message: str).
        If success is True, error_message will be empty.
        If success is False, error_message will contain details of the failure.
    """
    logger.info("Starting network connectivity checks...")

    for attempt in range(1, max_retries + 1):
        logger.info("Connectivity check attempt %d/%d", attempt, max_retries)

        gmail_result = check_gmail_imap()
        gemini_result = check_gemini_cli(gemini_path)

        if gmail_result.success and gemini_result.success:
            logger.info("All connectivity checks passed.")
            return True, ""

        error_messages = []
        if not gmail_result.success:
            error_messages.append(f"{gmail_result.service_name}: {gmail_result.error_message}")
        if not gemini_result.success:
            error_messages.append(f"{gemini_result.service_name}: {gemini_result.error_message}")

        combined_error = "; ".join(error_messages)

        if attempt < max_retries:
            logger.warning(
                "Connectivity checks failed (attempt %d/%d): %s. Retrying in %d seconds...",
                attempt, max_retries, combined_error, retry_interval_seconds
            )
            time.sleep(retry_interval_seconds)
        else:
            logger.error("Connectivity checks failed after %d attempts: %s", max_retries, combined_error)
            return False, combined_error

    return False, "Unexpected error in connectivity check logic"
