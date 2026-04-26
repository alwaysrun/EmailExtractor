# EmailExtractor Agent Rules

This document provides specific instructions for AI agents modifying the EmailExtractor project. These rules supplement the global engineering rules.

## Core Principles
- **Respect Medium Parsing Logic**: The parsing logic in `src/parser.py` is specifically tuned for Medium digests. Avoid making changes that break tracking parameter removal or article ID detection without thorough testing.
- **Gemini CLI Integration**: The `ArticleAnalyzer` in `src/analyzer.py` relies on the `gemini` CLI. When modifying analysis logic, ensure that `_NOISE_PATTERNS` are updated if the CLI output format changes.
- **Incremental Reporting**: Always maintain the incremental reporting feature in `main.py` and `src/reporter.py` to prevent data loss during long-running analysis sessions.

## Tooling & Environment
- **Environment**: Use `environment.yml` for dependency management.
- **Config**: All configurable parameters (IMAP settings, filters, AI prompts) must reside in `config.toml`. Never hardcode these values.
- **Testing**: New features in `src/` should have corresponding tests in `tests/`. Run tests using `pytest` before submitting changes.

## File Structure
- `src/`: Core logic (Fetcher, Parser, Analyzer, Reporter, Config).
- `Extracted/`: Output directory for generated reports (Markdown and JSON).
- `analyze_prompt.md`: The system prompt for article analysis.

## Development Workflow
1.  **Configuration**: Load settings via `src/config.py`.
2.  **Fetching**: Use `src/fetcher.py` for IMAP operations.
3.  **Parsing**: Use `src/parser.py` for content extraction.
4.  **Analysis**: Use `src/analyzer.py` for AI-powered processing.
5.  **Reporting**: Use `src/reporter.py` for final output generation.
