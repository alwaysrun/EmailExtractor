# EmailExtractor Agent Rules

This document provides specific instructions for AI agents modifying the EmailExtractor project. These rules supplement the global engineering rules.

## Core Principles
- **Respect Medium Parsing Logic**: The parsing logic in `src/parser.py` is specifically tuned for Medium digests. Avoid making changes that break tracking parameter removal or article ID detection without thorough testing.
- **Gemini CLI Integration**: The `ArticleAnalyzer` in `src/analyzer.py` relies on the `gemini` CLI. When modifying analysis logic, ensure that `_NOISE_PATTERNS` are updated if the CLI output format changes.
- **Incremental Reporting**: Always maintain the incremental reporting feature in `main.py` and `src/reporter.py` to prevent data loss during long-running analysis sessions.
- **Feishu Upload Integration**: The `FeishuUploader` in `src/uploader.py` handles automatic upload and conversion of reports. Changes to this module require testing the full upload-convert workflow.

## Tooling & Environment
- **Environment**: Use `environment.yml` for dependency management with conda.
- **Config**: All configurable parameters (IMAP settings, filters, AI prompts, Gemini CLI path) must reside in `configures/config.toml`. Never hardcode these values.
- **Credentials**: Sensitive credentials (email password, Feishu APP_ID/APP_SECRET) must use environment variables via `configures/.env`. Never commit `.env` files.
- **Path Resolution**: Use `src/paths.py` utilities for all path resolution. This ensures correct behavior in both development mode and Nuitka-compiled executables.

## File Structure
- `src/`: Core logic (Config, Fetcher, Parser, Analyzer, Reporter, Uploader, Paths).
- `configures/`: Configuration files (`config.toml`, `.env`, `analyze_prompt.md`).
- `docs/`: Project documentation (`Architecture.md`, `Modules.md`).
- `scripts/`: Build scripts (`build.ps1` for Nuitka compilation).
- `Extracted/`: Output directory for generated reports (Markdown and JSON).

## Development Workflow
1.  **Configuration**: Load settings via `src/config.py`; resolve paths via `src/paths.py`.
2.  **Fetching**: Use `src/fetcher.py` for IMAP operations.
3.  **Parsing**: Use `src/parser.py` for content extraction.
4.  **Analysis**: Use `src/analyzer.py` for AI-powered processing.
5.  **Reporting**: Use `src/reporter.py` for final output generation.
6.  **Upload**: Use `src/uploader.py` for Feishu integration (optional, triggered after successful analysis).
