"""Markdown reporter module for generating output."""

import dataclasses
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.analyzer import AnalysisResult
from src.parser import ExtractedURL

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """Generates Markdown reports from extracted URLs and analysis results."""

    def __init__(self, output_dir: Path, base_name: Optional[str] = None, filter_name: str = "") -> None:
        """Initialize MarkdownReporter.

        Args:
            output_dir: Directory for output files.
            base_name: Base name for output files (usually date). If None, uses current date.
            filter_name: Name of the filter being processed.
        """
        self._output_dir = output_dir
        self._base_name = base_name or datetime.now().strftime("%Y-%m-%d")
        self._filter_name = filter_name
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _get_output_path(self, suffix: str) -> Path:
        """Get the full output path for a given suffix.

        Args:
            suffix: File suffix (e.g., 'urls', 'summaries').

        Returns:
            Full path to the output file.
        """
        extension = "json" if suffix.endswith("_json") else "md"
        actual_suffix = suffix.replace("_json", "")
        
        # New format: {date}_sub-{name}_{result}
        # Result here corresponds to 'urls' or 'summaries'
        if self._filter_name:
            filename = f"{self._base_name}_sub-{self._filter_name}_{actual_suffix}.{extension}"
        else:
            filename = f"{self._base_name}-{actual_suffix}.{extension}"
            
        return self._output_dir / filename

    def generate_urls_report(self, grouped_urls: List[List[ExtractedURL]]) -> Path:
        """Generate a Markdown report of extracted URLs.

        Args:
            grouped_urls: List of URL groups, each from a single email.

        Returns:
            Path to the generated file.
        """
        content = self._build_urls_content(grouped_urls)
        output_path = self._get_output_path("urls")
        self._write_report(output_path, content)
        logger.info("URLs report generated: %s", output_path)
        
        # Also save as JSON for standalone analysis
        json_path = self._get_output_path("urls_json")
        self.save_to_json(grouped_urls, json_path)
        
        return output_path

    def save_to_json(self, grouped_urls: List[List[ExtractedURL]], output_path: Path) -> Path:
        """Save grouped URLs to a JSON file.

        Args:
            grouped_urls: List of URL groups.
            output_path: Path to the output JSON file.

        Returns:
            Path to the generated file.
        """
        data = [
            [dataclasses.asdict(url) for url in group]
            for group in grouped_urls
        ]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info("URLs JSON data saved: %s", output_path)
        return output_path

    def generate_summaries_report(
        self,
        results: List[AnalysisResult],
        grouped_urls: List[List[ExtractedURL]],
    ) -> Path:
        """Generate a Markdown report of article summaries.

        Args:
            results: List of analysis results.
            grouped_urls: Original grouped URLs for grouping context.

        Returns:
            Path to the generated file.
        """
        content = self._build_summaries_content(results, grouped_urls)
        output_path = self._get_output_path("summaries")
        self._write_report(output_path, content)
        logger.info("Summaries report generated: %s", output_path)
        return output_path

    def _build_urls_content(self, grouped_urls: List[List[ExtractedURL]]) -> str:
        """Build the Markdown content from grouped URLs.

        Args:
            grouped_urls: List of URL groups.

        Returns:
            Formatted Markdown content string.
        """
        lines: List[str] = []

        total_articles = sum(len(group) for group in grouped_urls)

        lines.append("# Extracted Medium Articles\n")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**Total Articles:** {total_articles}\n")
        lines.append("\n---\n\n")

        if grouped_urls:
            for group in grouped_urls:
                if not group:
                    continue

                first = group[0]
                lines.append(f"## {self._sanitize_cell(first.email_subject)}\n")
                lines.append(f"- **Date:** {self._sanitize_cell(first.email_date)}\n")
                lines.append(f"- **Sender:** {self._sanitize_cell(first.email_sender)}\n\n")

                lines.append("| # | Title | URL |\n")
                lines.append("| :---: | :--- | :--- |\n")

                for idx, item in enumerate(group, start=1):
                    title = self._sanitize_cell(item.title)
                    url = item.url
                    lines.append(f"| {idx} | {title} | [Open]({url}) |\n")

                lines.append("\n---\n\n")
        else:
            lines.append("No Medium articles were extracted from the filtered emails.\n")

        return "".join(lines)

    def _build_summaries_content(
        self,
        results: List[AnalysisResult],
        grouped_urls: List[List[ExtractedURL]],
    ) -> str:
        """Build the Markdown content from analysis results, grouped by email.

        Args:
            results: List of analysis results.
            grouped_urls: Original grouped URLs for grouping context.

        Returns:
            Formatted Markdown content string.
        """
        lines: List[str] = []

        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        lines.append("---\n")
        lines.append("Analysis Summary:\n")
        lines.append(f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"- **Total Analyzed:** {len(results)}\n")
        lines.append(f"- **Successful:** {success_count}\n")
        lines.append(f"- **Failed:** {fail_count}\n")
        lines.append("\n---\n")

        url_to_result = {r.url: r for r in results}

        for group in grouped_urls:
            if not group:
                continue

            first = group[0]
            lines.append("Article Info:\n")
            lines.append(f"- **Date:** {self._sanitize_cell(first.email_date)}\n")
            lines.append(f"- **Sender:** {self._sanitize_cell(first.email_sender)}\n")
            lines.append("\n---\n\n")

            for idx, item in enumerate(group, start=1):
                result = url_to_result.get(item.url)
                if result is None:
                    continue

                lines.append(f"# {idx}. {self._sanitize_cell(item.title)}\n")
                lines.append(f"> **URL:** `{item.url}`\n\n")

                if result.success:
                    normalized_content = self._normalize_headings(result.content, shift=1)
                    lines.append(f"{normalized_content}\n")
                else:
                    lines.append(f"**Analysis Failed:** {result.error_message}\n")

                lines.append("\n---\n\n")

        return "".join(lines)

    @staticmethod
    def _sanitize_cell(text: str) -> str:
        """Sanitize a string for safe use inside a Markdown table cell.

        Removes embedded newlines (CR/LF) and escapes pipe characters that
        would otherwise break the table column boundaries.

        Args:
            text: Raw cell content.

        Returns:
            Single-line, pipe-escaped string.
        """
        sanitized = " ".join(text.split())
        return sanitized.replace("|", "\\|")

    @staticmethod
    def _normalize_headings(content: str, shift: int = 1) -> str:
        """Normalize heading levels in markdown content.

        First normalizes all "Step X" headings to level 1, then shifts all headings.
        This ensures consistent heading levels regardless of LLM output variation.

        Args:
            content: Markdown content to process.
            shift: Number of levels to shift headings (default: 1).

        Returns:
            Content with normalized heading levels.
        """
        MAX_HEADING_LEVEL = 6
        lines = content.split("\n")
        result_lines = []

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        step_pattern = re.compile(r"^Step\s+\d+\s+.+$")

        for line in lines:
            match = heading_pattern.match(line)
            if match:
                heading_text = match.group(2)
                if step_pattern.match(heading_text):
                    result_lines.append(f"# {heading_text}")
                else:
                    result_lines.append(line)
            else:
                result_lines.append(line)

        final_lines = []
        for line in result_lines:
            match = heading_pattern.match(line)
            if match:
                current_level = len(match.group(1))
                new_level = min(current_level + shift, MAX_HEADING_LEVEL)
                heading_text = match.group(2)
                final_lines.append(f"{'#' * new_level} {heading_text}")
            else:
                final_lines.append(line)

        return "\n".join(final_lines)

    def _write_report(self, output_path: Path, content: str) -> None:
        """Write the report content to the output file.

        Args:
            output_path: Path to the output file.
            content: Markdown content to write.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    def generate_report(self, grouped_urls: List[List[ExtractedURL]]) -> None:
        """Generate a Markdown report from extracted URLs (legacy interface).

        Args:
            grouped_urls: List of URL groups, each from a single email.
        """
        self.generate_urls_report(grouped_urls)
