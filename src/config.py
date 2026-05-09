"""Configuration loader for EmailExtractor."""

import dataclasses
import os
from pathlib import Path
from typing import List, Optional

import toml


@dataclasses.dataclass
class EmailConfig:
    """IMAP email configuration."""

    imap_server: str
    imap_port: int
    username: str
    password: str


@dataclasses.dataclass
class FilterConfig:
    """Email filter configuration."""

    name: str
    sender: str
    title_keywords: List[str]
    max_emails: int
    extract_format: str = "name_url"



@dataclasses.dataclass
class AnalysisConfig:
    """Analysis configuration."""

    output_dir: str
    prompt_file: str
    analysis_timeout_ms: int
    min_request_interval_ms: int
    max_retries: int
    gemini_path: str


@dataclasses.dataclass
class NetworkConfig:
    """Network configuration."""

    network_check_retry_count: int = 3
    network_check_interval_seconds: int = 15


@dataclasses.dataclass
class Config:
    """Main configuration container."""

    email: EmailConfig
    filters: List[FilterConfig]
    analysis: AnalysisConfig
    network: NetworkConfig

    @classmethod
    def from_file(cls, config_path: Path) -> "Config":
        """Load configuration from a TOML file.

        Args:
            config_path: Path to the configuration file.

        Returns:
            Config instance with loaded settings.

        Raises:
            FileNotFoundError: If config file does not exist.
            KeyError: If required configuration keys are missing.
            ValueError: If duplicate filter names are found.
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        raw_config = toml.load(config_path)

        email_config = EmailConfig(
            imap_server=raw_config["email"]["imap_server"],
            imap_port=raw_config["email"]["imap_port"],
            username=raw_config["email"]["username"],
            password=os.environ.get("EMAIL_PASSWORD", raw_config["email"]["password"]),
        )

        filters_data = raw_config.get("filters", [])
        if not isinstance(filters_data, list):
            # Support legacy single filter format if needed, but the user requested new format
            # Let's stick to the new format as requested
            filters_data = []

        filters: List[FilterConfig] = []
        names = set()
        for f in filters_data:
            name = f.get("name")
            if not name:
                raise KeyError("Filter entry missing 'name' field")
            
            if name in names:
                import logging
                logger = logging.getLogger(__name__)
                logger.error("Duplicate filter name found: %s", name)
                raise ValueError(f"Duplicate filter name found: {name}")
            
            names.add(name)
            filters.append(FilterConfig(
                name=name,
                sender=f.get("sender", ""),
                title_keywords=f.get("title_keywords", []),
                max_emails=f.get("max_emails", 50),
                extract_format=f.get("extract_format", "name_url"),
            ))

        analysis_config = AnalysisConfig(
            output_dir=raw_config["analysis"].get("output_dir", "Extracted"),
            prompt_file=raw_config["analysis"].get("prompt_file", "analyze_prompt.md"),
            analysis_timeout_ms=raw_config["analysis"].get("analysis_timeout_ms", 300000),
            min_request_interval_ms=raw_config["analysis"].get("min_request_interval_ms", 1000),
            max_retries=raw_config["analysis"].get("max_retries", 3),
            gemini_path=raw_config["analysis"].get("gemini_path", "gemini"),
        )

        network_config = NetworkConfig(
            network_check_retry_count=raw_config["network"].get("network_check_retry_count", 3),
            network_check_interval_seconds=raw_config["network"].get("network_check_interval_seconds", 15),
        )

        return cls(email=email_config, filters=filters, analysis=analysis_config, network=network_config)
