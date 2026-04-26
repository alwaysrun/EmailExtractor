"""Article analyzer module using Gemini CLI."""

import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from src.parser import ExtractedURL

logger = logging.getLogger(__name__)

# Regex patterns that identify gemini CLI startup/diagnostic noise lines.
# These appear in stdout before the actual LLM response and must be stripped.
_NOISE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^YOLO mode is enabled\."),
    re.compile(r"^Error authenticating:"),
    re.compile(r"^\s+at "),                         # JS stack trace frames
    re.compile(r"^\s+config:"),                      # Gaxios config dump
    re.compile(r"^\s+response:"),
    re.compile(r"^\s+error:"),
    re.compile(r"^\s+code:"),
    re.compile(r"^\s+Symbol\("),
    re.compile(r"^\s+retryConfig:"),
    re.compile(r"^\s+[\[{]"),                        # JS object/array dump lines
    re.compile(r"^Tool with name .* is already registered\."),
    re.compile(r"^Hook execution"),
    re.compile(r"^Hook\(s\)"),
    re.compile(r"^Hook execution error:"),
    re.compile(r"^ERROR: The process "),
    re.compile(r"^MCP issues detected\."),
    re.compile(r"^\[WebFetchTool\]"),
    re.compile(r"^Error executing tool"),
    re.compile(r"^I (will|'ll) "),
    re.compile(r"^Attempt \d+ failed\."),
]


@dataclass
class AnalysisResult:
    """Result of a single article analysis."""

    url: str
    title: str
    success: bool
    content: str
    error_message: Optional[str] = None


class ArticleAnalyzer:
    """Analyzes articles using Gemini CLI."""

    def __init__(
        self,
        prompt_template_path: Path,
        timeout_ms: int = 600000,
        max_retries: int = 3,
        min_interval_ms: int = 1000,
        gemini_path: str = "gemini",
    ) -> None:
        """Initialize ArticleAnalyzer.

        Args:
            prompt_template_path: Path to the prompt template file.
            timeout_ms: Timeout in milliseconds for each Gemini CLI call.
            max_retries: Maximum number of retries for failed requests.
            min_interval_ms: Minimum interval in milliseconds between requests.
                The actual interval is a random value between min_interval_ms
                and min_interval_ms * 1.5.
            gemini_path: Path to the Gemini CLI executable.
        """
        self._prompt_template_path = prompt_template_path
        self._timeout_s = timeout_ms / 1000.0
        self._max_retries = max_retries
        self._min_interval_s = min_interval_ms / 1000.0
        self._prompt_template: Optional[str] = None

        # Use the Gemini CLI path exactly as provided in the config.
        self._gemini_path = gemini_path
        logger.debug("Using Gemini CLI path from config: %s", self._gemini_path)

        # On Windows, .cmd/.ps1 wrappers require the shell to be the invoker.
        self._use_shell = sys.platform == "win32"

    def _load_prompt_template(self) -> str:
        """Load the prompt template from file.

        Returns:
            The prompt template content.

        Raises:
            FileNotFoundError: If prompt template file does not exist.
        """
        if self._prompt_template is None:
            if not self._prompt_template_path.exists():
                raise FileNotFoundError(
                    f"Prompt template not found: {self._prompt_template_path}"
                )
            self._prompt_template = self._prompt_template_path.read_text(
                encoding="utf-8"
            )
        return self._prompt_template

    def _build_prompt(self, url: str) -> str:
        """Build the full prompt for Gemini CLI.

        Replaces the ``{{url}}`` placeholder in the template with the real URL.

        Args:
            url: The article URL to analyze.

        Returns:
            The complete prompt string.
        """
        template = self._load_prompt_template()
        if "{{url}}" not in template:
            logger.warning(
                "Prompt template does not contain '{{url}}' placeholder; appending URL."
            )
            return f"{template}\n{url}"
        return template.replace("{{url}}", url)

    def analyze_article(self, url: str, title: str) -> AnalysisResult:
        """Analyze a single article using Gemini CLI with retries.

        Args:
            url: The article URL to analyze.
            title: The article title for logging.

        Returns:
            AnalysisResult containing the analysis or error information.
        """
        prompt = self._build_prompt(url)

        logger.info("Analyzing article: %s", title)
        logger.info("URL: %s", url)

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            if attempt > 1:
                logger.info("Retry attempt %d/%d for: %s", attempt, self._max_retries, title)
                time.sleep(2 * (attempt - 1))  # Exponential backoff for retries

            system_prompt = """You are an autonomous URL content analyzer agent.
The user has provided you with an Analysis Template and a URL in their prompt.
CRITICAL INSTRUCTIONS:
1. DO NOT reply with conversational filler, acknowledgments, or state that you are ready.
2. YOU MUST IMMEDIATELY use your web fetch tool to read the URL provided in the user's prompt.
3. AFTER fetching the content, IMMEDIATELY analyze it using the provided Analysis Template.
4. Your FINAL and ONLY output must be the Markdown report from the analysis. Do not ask the user for further input.
5. DO NOT use any file system tools (e.g., list_dir, view_file).
6. IGNORE the local workspace entirely. Do not analyze the local project."""

            try:
                # Use a temporary file for the system prompt
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tmp_sys:
                    tmp_sys.write(system_prompt)
                    tmp_sys_path = tmp_sys.name

                # Use a temporary file for the user prompt (contains the URL and template)
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tmp_user:
                    tmp_user.write(prompt)
                    tmp_user_path = tmp_user.name

                try:
                    use_shell = False
                    if self._gemini_path.lower().endswith(".ps1"):
                        # Use PowerShell to read the prompt from the file securely.
                        # This avoids all special character escaping and length issues.
                        ps_command = f'''
$userPrompt = Get-Content -Path "{tmp_user_path}" -Raw
& "{self._gemini_path}" -y -p $userPrompt
'''
                        cmd = [
                            "powershell.exe",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-Command",
                            ps_command,
                        ]
                    else:
                        # Fallback for non-PowerShell: try to pass as argument or @file if supported.
                        # For now, following tmp.py reference which uses @ prefix.
                        cmd = [self._gemini_path, "-y", "-p", f"@{tmp_user_path}"]

                    env = os.environ.copy()
                    env["GEMINI_SYSTEM_MD"] = tmp_sys_path

                    logger.debug("Executing command (file-based approach)")
                    logger.debug("System prompt file: %s", tmp_sys_path)
                    logger.debug("User prompt file: %s", tmp_user_path)
                    logger.debug("Timeout set to: %.2f seconds", self._timeout_s)

                    stop_event = threading.Event()

                    def progress_indicator():
                        prefix = "  Waiting for AI response"
                        print(prefix, end="", flush=True)
                        count = len(prefix)
                        while not stop_event.is_set():
                            print(".", end="", flush=True)
                            count += 1
                            if count >= 80:
                                print()
                                count = 0
                            stop_event.wait(1)
                        print()

                    t = threading.Thread(target=progress_indicator, daemon=True)
                    t.start()

                    try:
                        logger.debug("Final command: %s", cmd)
                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            shell=use_shell,
                            env=env,
                        )
                        try:
                            # Use a minimum timeout of 5 minutes as suggested in tmp.py
                            actual_timeout = max(self._timeout_s, 300)
                            stdout, stderr = proc.communicate(timeout=actual_timeout)
                        except subprocess.TimeoutExpired as e:
                            logger.error("Timeout after %.0f seconds", actual_timeout)
                            if sys.platform == "win32":
                                subprocess.run(
                                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                    capture_output=True,
                                )
                            else:
                                proc.kill()
                            
                            try:
                                proc.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                logger.warning("Process %d did not terminate", proc.pid)
                            raise

                        result = proc
                        result.stdout = stdout
                        result.stderr = stderr
                        result.returncode = proc.returncode

                    finally:
                        stop_event.set()
                        t.join(timeout=2)

                    if result.returncode != 0:
                        error_msg = result.stderr.strip() or f"Exit code: {result.returncode}"
                        logger.error("Gemini CLI failed for %s (attempt %d): %s", url, attempt, error_msg)
                        if result.stdout:
                            logger.debug("Partial stdout on failure: %s", result.stdout[:500])
                        last_error = f"Gemini CLI error: {error_msg}"
                        continue

                    raw_output = result.stdout
                    logger.debug("Raw Gemini output length: %d characters", len(raw_output))
                    
                    output = self._extract_llm_response(raw_output)
                    if not output:
                        logger.warning("Empty response from Gemini for %s (attempt %d)", url, attempt)
                        logger.debug("Raw output: %s", raw_output[:500])
                        last_error = "Empty response from Gemini CLI"
                        continue

                    logger.info("Successfully analyzed: %s", title)
                    return AnalysisResult(
                        url=url, title=title, success=True, content=output
                    )

                except subprocess.TimeoutExpired:
                    error_msg = f"Timeout after {actual_timeout} seconds"
                    logger.error("Timeout (attempt %d): %s", attempt, error_msg)
                    last_error = error_msg
                    continue
                except FileNotFoundError:
                    error_msg = f"Gemini CLI not found at '{self._gemini_path}'"
                    logger.error(error_msg)
                    return AnalysisResult(
                        url=url, title=title, success=False, content="", error_message=error_msg
                    )
                except Exception as e:
                    error_msg = f"Unexpected error: {str(e)}"
                    logger.error("Error (attempt %d): %s", attempt, error_msg)
                    logger.debug("Traceback: %s", traceback.format_exc())
                    last_error = error_msg
                    continue

                finally:
                    # Clean up temporary files
                    for tmp_path in [tmp_sys_path, tmp_user_path]:
                        try:
                            if os.path.exists(tmp_path):
                                os.unlink(tmp_path)
                        except Exception as e:
                            logger.debug("Failed to delete temp file %s: %s", tmp_path, e)

            except Exception as e:
                logger.error("Outer exception: %s", str(e))
                logger.debug("Traceback: %s", traceback.format_exc())
                last_error = str(e)

        return AnalysisResult(
            url=url,
            title=title,
            success=False,
            content="",
            error_message=f"Failed after {self._max_retries} attempts. Last error: {last_error}",
        )


    @staticmethod
    def _extract_llm_response(raw_output: str) -> str:
        """Strip gemini CLI startup noise and return only the LLM response.

        The CLI runs in ``--output-format text`` mode, so stdout contains
        diagnostic header lines (YOLO-mode banner, auth errors, hook output,
        JS stack traces, …) followed by the plain-text model reply.  This
        method discards every line that matches a known noise pattern and
        returns the remaining content.

        Args:
            raw_output: Full stdout captured from the gemini subprocess.

        Returns:
            The clean LLM response, or an empty string if nothing remains.
        """
        lines = raw_output.splitlines()

        # Phase 1: Skip leading noise and leading blank lines.
        start_idx = 0
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            if any(p.match(line) for p in _NOISE_PATTERNS):
                continue
            # Found the first line of real content.
            start_idx = i
            break
        else:
            # Entire output was noise or empty.
            return ""

        # Phase 2: Collect all remaining lines, but still filter out any mid-output 
        # tool logs or noise that might appear (though usually they are at the start).
        content_lines = []
        for line in lines[start_idx:]:
            if not any(p.match(line) for p in _NOISE_PATTERNS):
                content_lines.append(line)

        return "\n".join(content_lines).strip()

    def analyze_articles(
        self, grouped_urls: List[List[ExtractedURL]], progress_callback=None
    ) -> Iterator[AnalysisResult]:
        """Analyze multiple articles with progress reporting.

        Args:
            grouped_urls: List of URL groups from emails.
            progress_callback: Optional callback for progress updates.
                Signature: callback(current: int, total: int, title: str)

        Yields:
            AnalysisResult objects incrementally as they finish.
        """
        all_urls: List[Tuple[str, str]] = []

        for group in grouped_urls:
            for item in group:
                all_urls.append((item.url, item.title))

        total = len(all_urls)
        logger.info("Starting analysis of %d articles", total)

        for idx, (url, title) in enumerate(all_urls, start=1):
            if progress_callback:
                progress_callback(idx, total, title)
            else:
                logger.info("Progress: %d/%d - %s", idx, total, title)

            result = self.analyze_article(url, title)
            yield result

            if idx < total:
                actual_interval = random.uniform(self._min_interval_s, self._min_interval_s * 1.5)
                logger.debug("Waiting %.2f seconds before next request", actual_interval)
                time.sleep(actual_interval)
