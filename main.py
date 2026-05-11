"""Main entry point for EmailExtractor."""

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

from dotenv import load_dotenv

from src.analyzer import AnalysisResult, ArticleAnalyzer
from src.config import Config, FilterConfig
from src.fetcher import EmailFetcher
from src.network_checker import check_network_connectivity
from src.parser import EmailParser, ExtractedURL
from src.paths import get_app_dir, get_config_path, get_env_path, get_prompt_path, resolve_path
from src.reporter import MarkdownReporter
from src.uploader import FeishuUploader

logger = logging.getLogger(__name__)


class TimeoutAttemptFilter(logging.Filter):
    """Filter that excludes 'Timeout (attempt 2)' errors from file logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR:
            msg = record.getMessage()
            if "Timeout (attempt 2)" in msg:
                return False
        return True


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, enable DEBUG level logging.
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    error_log_path = get_app_dir() / "logs" / "error.log"
    error_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_handler = logging.FileHandler(error_log_path, encoding="utf-8")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    file_handler.addFilter(TimeoutAttemptFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Extract URLs from filtered emails and generate a Markdown report."
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (default: configures/config.toml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging output",
    )
    parser.add_argument(
        "--fetch-url",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch URLs from emails (default: True)",
    )
    parser.add_argument(
        "--analyze-url",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Analyze URLs from the report (default: True)",
    )
    parser.add_argument(
        "--input-file",
        type=str,
        default=None,
        help="Path to the input JSON file for analysis (required if only --analyze-url is set)",
    )
    return parser.parse_args()


def load_config(config_path: Optional[Union[str, Path]]) -> Config:
    """Load configuration from file.

    Args:
        config_path: Path to configuration file (string or Path). If None, uses default path.

    Returns:
        Loaded Config instance.

    Raises:
        SystemExit: If configuration loading fails.
    """
    resolved_path = get_config_path(str(config_path) if config_path else None)
    try:
        return Config.from_file(resolved_path)
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", resolved_path)
        sys.exit(1)
    except KeyError as e:
        logger.error("Missing required configuration key: %s", e)
        sys.exit(1)


def fetch_and_parse_emails(fetcher: EmailFetcher, filter_config: FilterConfig) -> Tuple[List[List[ExtractedURL]], int]:
    """Fetch emails and extract URLs with progress output for a specific filter.

    Args:
        fetcher: EmailFetcher instance with active IMAP connection.
        filter_config: Specific filter configuration.

    Returns:
        Tuple of (List of URL groups where each group is from one email, total unread count).
    """
    grouped_urls: List[List[ExtractedURL]] = []
    parser = EmailParser(extract_format=filter_config.extract_format, filter_name=filter_config.name)
    total_unread = 0

    try:
        fetcher.ensure_connected()
        emails, total_unread = fetcher.fetch_unread_emails(filter_config)
        logger.info(
            "Filter '%s': Processing %d emails (total unread: %d)",
            filter_config.name, len(emails), total_unread
        )

        for idx, message in enumerate(emails, start=1):
            subject = fetcher._decode_header(message.get("Subject", "Unknown"))
            logger.info(
                "Filter '%s' [Email %d/%d] Extracting URLs from: %s",
                filter_config.name, idx, len(emails), subject
            )
            urls = parser.parse_email(message)
            if urls:
                grouped_urls.append(urls)
                logger.info(
                    "Filter '%s' [Email %d/%d] Found %d URLs",
                    filter_config.name, idx, len(emails), len(urls)
                )

    except ConnectionError as e:
        logger.error("Failed to connect to email server: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error during email processing: %s", e)
        sys.exit(1)

    return grouped_urls, total_unread


def progress_callback(current: int, total: int, title: str) -> None:
    """Display progress during article analysis.

    Args:
        current: Current article index.
        total: Total number of articles.
        title: Article title.
    """
    logger.info("[Analysis %d/%d] Processing: %s", current, total, title)


def load_urls_from_json(json_path: Union[str, Path]) -> Optional[List[List[ExtractedURL]]]:
    """Load grouped URLs from a JSON file.

    Args:
        json_path: Path to the input JSON file (string or Path).

    Returns:
        List of URL groups, or None if loading failed.
    """
    path = Path(json_path)
    if not path.exists():
        logger.error("File not found: %s", path)
        return None

    target_json = path
    if path.suffix == ".md":
        # If user provides .md file, try to find the corresponding .json file
        target_json = path.with_suffix(".json")
        if not target_json.exists():
            logger.error("Provided Markdown file, but corresponding JSON not found: %s", target_json)
            return None
        logger.info("Provided Markdown file, using corresponding JSON: %s", target_json)

    logger.info("Loading URLs from: %s", target_json)
    try:
        with open(target_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        grouped_urls: List[List[ExtractedURL]] = []
        for group_data in data:
            group = [ExtractedURL(**item) for item in group_data]
            grouped_urls.append(group)
        
        return grouped_urls
    except Exception as e:
        logger.error("Failed to load URLs from JSON: %s", e)
        return None


def find_latest_urls_json(output_dir: Path) -> Optional[Path]:
    """Find the most recent sub_urls JSON file in the output directory.

    Args:
        output_dir: Directory to search in.

    Returns:
        Path to the latest JSON file, or None if not found.
    """
    if not output_dir.exists():
        return None
    
    # Match patterns like YYYY-MM-DD-sub_urls.json or YYYY-MM-DD_sub-name_urls.json
    files = list(output_dir.glob("*-sub_urls.json")) + list(output_dir.glob("*_sub-*_urls.json"))
    if not files:
        return None
    
    # Sort by modification time (most recent first)
    return max(files, key=lambda p: p.stat().st_mtime)


def extract_base_name_from_path(file_path: Path) -> Optional[str]:
    """Extract base_name from a file path.

    The expected pattern is: YYYY-MM-DD-suffix.extension or YYYY-MM-DD_sub-name_suffix.extension
    For example: 2026-04-22-sub_urls.json -> 2026-04-22
    For example: 2026-04-24_sub-medium_urls.json -> 2026-04-24

    Args:
        file_path: Path to the input file.

    Returns:
        Extracted base_name (date prefix), or None if pattern doesn't match.
    """
    stem = file_path.stem
    if file_path.suffix == ".json" and stem.endswith("_json"):
        stem = stem[:-5]
    
    pattern = r"^(\d{4}-\d{2}-\d{2})[_-]"
    match = re.match(pattern, stem)
    if match:
        return match.group(1)
    return None


def run_analysis(
    grouped_urls: List[List[ExtractedURL]],
    prompt_path: Union[str, Path],
    reporter: MarkdownReporter,
    timeout_ms: int = 300000,
    min_interval_ms: int = 1000,
    max_retries: int = 3,
    gemini_path: str = "gemini",
) -> List[AnalysisResult]:
    """Run article analysis using Gemini CLI.

    Args:
        gemini_path:
        max_retries:
        min_interval_ms:
        grouped_urls: List of URL groups from emails.
        prompt_path: Path to the prompt template file.
        reporter: MarkdownReporter instance to save incremental progress.
        timeout_ms: Timeout in milliseconds for each analysis.

    Returns:
        List of AnalysisResult objects.
    """
    logger.info("Starting article analysis...")
    logger.info("Using prompt template: %s", prompt_path)

    analyzer = ArticleAnalyzer(
        prompt_path,
        timeout_ms=timeout_ms,
        min_interval_ms=min_interval_ms,
        max_retries=max_retries,
        gemini_path=gemini_path,
    )
    
    results = []
    for result in analyzer.analyze_articles(grouped_urls, progress_callback=progress_callback):
        results.append(result)
        # Store result incrementally to avoid data loss from unexpected interrupts
        reporter.generate_summaries_report(results, grouped_urls)

    success_count = sum(1 for r in results if r.success)
    logger.info("Analysis complete: %d/%d successful", success_count, len(results))

    return results


def cleanup_output_directory(output_dir: Path) -> None:
    """Move all Markdown and JSON files except today's summaries to a backup folder.

    Args:
        output_dir: Path to the output directory.
    """
    bak_dir = output_dir / "_bak"
    bak_dir.mkdir(exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    logger.info("Cleaning up old reports and data in %s (keeping today's summaries)", output_dir)

    moved_count = 0
    files_to_check = list(output_dir.glob("*.md")) + list(output_dir.glob("*.json"))
    for file_path in files_to_check:
        # Exception: today's summary files
        # We keep any file that starts with today's date AND contains "summaries"
        if file_path.name.startswith(today_str) and "summaries" in file_path.name.lower():
            continue

        target_path = bak_dir / file_path.name
        try:
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(file_path), str(target_path))
            moved_count += 1
        except Exception as e:
            logger.error("Failed to move %s to %s: %s", file_path.name, bak_dir.name, e)

    if moved_count > 0:
        logger.info("Moved %d old files to %s", moved_count, bak_dir)


def main(
    config_path: Optional[str] = None,
    verbose: bool = False,
    fetch_url: bool = True,
    analyze_url: bool = True,
    input_file: Optional[str] = None,
) -> None:
    """Main entry point for the EmailExtractor application.
    
    Args:
        config_path: Path to configuration file. If None, uses configures/config.toml.
        verbose: If True, enable verbose logging.
        fetch_url: If True, fetch URLs from emails.
        analyze_url: If True, analyze URLs.
        input_file: Optional path to input JSON file for analysis.
    """
    logger.info("Starting EmailExtractor")

    app_dir = get_app_dir()
    config = load_config(config_path)

    output_dir = resolve_path(config.analysis.output_dir, app_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if any action is requested
    if not fetch_url and not analyze_url:
        logger.error("Both --fetch-url and --analyze-url are false. Please specify at least one action.")
        return

    # If an input file is provided, we only analyze that specific file (ignoring filters)
    if input_file and analyze_url and not fetch_url:
        input_path = resolve_path(input_file, app_dir)
        base_name = extract_base_name_from_path(input_path) or datetime.now().strftime("%Y-%m-%d")
        urls = load_urls_from_json(input_path)
        if urls:
            reporter = MarkdownReporter(output_dir, base_name)
            prompt_path = get_prompt_path(config.analysis.prompt_file)
            results = run_analysis(
                urls,
                prompt_path,
                reporter=reporter,
                timeout_ms=config.analysis.analysis_timeout_ms,
                min_interval_ms=config.analysis.min_request_interval_ms,
                max_retries=config.analysis.max_retries,
                gemini_path=config.analysis.gemini_path,
            )
            if results and any(r.success for r in results):
                report_path = reporter.generate_summaries_report(results, urls)
                logger.info("Summary analysis successful, uploading and converting report...")
                uploader = FeishuUploader()
                result = uploader.upload_and_convert(report_path, convert=True)
                if result.success:
                    logger.info("Auto upload and convert to Feishu successful.")
                    if result.doc_url:
                        logger.info("Feishu Document URL: %s", result.doc_url)
                else:
                    logger.error("Auto upload to Feishu failed: %s", result.error_msg)
                cleanup_output_directory(output_dir)
        return

    # Otherwise, process each filter with a single IMAP connection
    try:
        with EmailFetcher(config) as fetcher:
            for filter_config in config.filters:
                logger.info("Processing filter: %s", filter_config.name)
                
                base_name = datetime.now().strftime("%Y-%m-%d")
                reporter = MarkdownReporter(output_dir, base_name, filter_name=filter_config.name)
                
                grouped_urls: List[List[ExtractedURL]] = []

                if fetch_url:
                    fetched_urls, total_unread = fetch_and_parse_emails(fetcher, filter_config)
                    if fetched_urls:
                        grouped_urls = fetched_urls
                        json_path = reporter.generate_urls_report(grouped_urls)
                        total_urls = sum(len(group) for group in grouped_urls)
                        logger.info(
                            "Filter '%s': Extraction complete. Found %d URLs across %d emails.",
                            filter_config.name, total_urls, len(grouped_urls)
                        )
                        logger.info("URLs JSON data saved to: %s", json_path)
                    else:
                        if total_unread == 0:
                            logger.info("Filter '%s': No unread emails found in inbox.", filter_config.name)
                        else:
                            logger.info(
                                "Filter '%s': No emails matched criteria (Total unread: %d).",
                                filter_config.name, total_unread
                            )
                        continue

                if analyze_url and grouped_urls:
                    prompt_path = get_prompt_path(config.analysis.prompt_file)
                    if not prompt_path.exists():
                        logger.error("Prompt template not found: %s. Skipping analysis.", prompt_path)
                        continue

                    results = run_analysis(
                        grouped_urls,
                        prompt_path,
                        reporter=reporter,
                        timeout_ms=config.analysis.analysis_timeout_ms,
                        min_interval_ms=config.analysis.min_request_interval_ms,
                        max_retries=config.analysis.max_retries,
                        gemini_path=config.analysis.gemini_path,
                    )
                    if results and any(r.success for r in results):
                        report_path = reporter.generate_summaries_report(results, grouped_urls)
                        logger.info("Summary analysis successful, uploading and converting report...")
                        uploader = FeishuUploader()
                        result = uploader.upload_and_convert(report_path, convert=True)
                        if result.success:
                            logger.info("Auto upload and convert to Feishu successful.")
                            if result.doc_url:
                                logger.info("Feishu Document URL: %s", result.doc_url)
                        else:
                            logger.error("Auto upload to Feishu failed: %s", result.error_msg)
                        cleanup_output_directory(output_dir)
    except ConnectionError as e:
        logger.error("Failed to connect to email server: %s", e)
        sys.exit(1)

    logger.info("All tasks completed.")


if __name__ == "__main__":
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
    args = parse_arguments()

    # for analyze test, do not remove it
    args.fetch_url = False
    args.input_file = './Extracted/2026-05-11_sub-bestblogs_urls.json'
    # args.verbose = True

    # args.analyze_url=False

    setup_logging(verbose=args.verbose)

    config = load_config(args.config)

    success, error_msg = check_network_connectivity(
        gemini_path=config.analysis.gemini_path,
        max_retries=config.network.network_check_retry_count,
        retry_interval_seconds=config.network.network_check_interval_seconds,
    )
    if not success:
        logger.error("Network connectivity check failed: %s", error_msg)
        logger.error("Please check your network connection and try again.")
        sys.exit(1)

    main(
        config_path=args.config,
        verbose=args.verbose,
        fetch_url=args.fetch_url,
        analyze_url=args.analyze_url,
        input_file=args.input_file,
    )
