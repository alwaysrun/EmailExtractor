# EmailExtractor Module Responsibilities

This document defines the roles and boundaries for each module in the project.

## Core Modules (`src/`)

| Module | Responsibility | Key Symbols |
| :--- | :--- | :--- |
| **`src/config.py`** | Manages application settings loaded from `config.toml`. | `Config`, `EmailConfig`, `FilterConfig`, `OutputConfig` |
| **`src/fetcher.py`** | Handles IMAP connection and retrieval of unread emails. | `EmailFetcher` |
| **`src/parser.py`** | Extracts URLs from email bodies, focusing on Medium articles. Resolves redirects and cleans tracking parameters. | `EmailParser`, `ExtractedURL` |
| **`src/analyzer.py`** | Orchestrates analysis of extracted URLs using Gemini CLI. Manages subprocess execution and filters output noise. | `ArticleAnalyzer`, `AnalysisResult` |
| **`src/reporter.py`** | Formats and saves data into Markdown and JSON reports. Supports incremental saving. | `MarkdownReporter` |

## Entry Point

- **`main.py`**: Orchestrates the full pipeline. It uses `argparse` to provide a CLI interface and connects all core modules to perform fetching, parsing, analysis, and reporting.

## Support Files

- **`analyze_prompt.md`**: Contains the system prompt used by `ArticleAnalyzer` for deep technical deconstruction of article content.
- **`config.toml`**: Stores user-specific settings such as IMAP credentials and filters.
- **`environment.yml`**: Defines the project's dependencies for development and runtime.

## Test Suite (`tests/`)

- **`tests/test_config.py`**: Tests configuration loading and validation.
- **`tests/test_fetcher.py`**: Tests IMAP fetching logic (using mocks).
- **`tests/test_parser.py`**: Validates URL extraction and resolution logic for various email formats.
- **`tests/test_reporter.py`**: Ensures report files are generated correctly.
