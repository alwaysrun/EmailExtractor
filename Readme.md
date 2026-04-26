# EmailExtractor

Automated pipeline that fetches technical article digests from emails, extracts URLs, and performs AI-powered analysis using Gemini CLI.

## Features

- **Email Fetching**: Connect to IMAP servers and filter unread emails by sender/subject
- **URL Extraction**: Extract and clean article URLs from email bodies (optimized for Medium digests)
- **AI Analysis**: Deep technical analysis of articles via Gemini CLI
- **Incremental Reporting**: Generate Markdown and JSON reports with auto-save

## Quick Start

```bash
# Create conda environment
conda env create -f environment.yml
conda activate emailextractor

# Configure credentials
cp .env.example .env
# Edit .env with your email app password

# Edit config.toml with your IMAP settings and filters

# Run
python main.py
```

## Configuration

Edit `config.toml` to configure:

- **IMAP settings**: Server, port, username
- **Filters**: Email sender, subject keywords, max emails per source
- **Output**: Directory, prompt file, analysis timeout

Use `.env` for sensitive credentials (`EMAIL_PASSWORD`).

## CLI Options

```bash
python main.py --help

python main.py --fetch-url --analyze-url    # Full pipeline (default)
python main.py --no-analyze-url             # Fetch only
python main.py --analyze-url --input-file report.json  # Analyze existing report
```

## Project Structure

```
src/
├── config.py    # Configuration management
├── fetcher.py   # IMAP email fetching
├── parser.py    # URL extraction
├── analyzer.py  # Gemini CLI integration
└── reporter.py  # Report generation
```

## Requirements

- Python 3.10+
- Gemini CLI installed and configured
- IMAP access to email account
