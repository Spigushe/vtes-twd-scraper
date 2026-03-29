# vtes-twd-scraper

Scrape tournament winning decks (TWD) from the [VEKN forum](https://www.vekn.net/forum/event-reports-and-twd) and export them as YAML files.

## Data format

Each tournament produces one YAML file named `{event_id}.yaml` where `event_id` is the numeric id from the VEKN event calendar URL (e.g. `/event/8470` → `8470.yaml`). Files are stored under `twds/YYYY/MM/` by default.

This convention mirrors the [GiottoVerducci/TWD](https://github.com/GiottoVerducci/TWD) archive, which uses `decks/{event_id}.txt`.

## Installation

```bash
git clone https://github.com/Spigushe/vtes-twd-scraper.git
cd vtes-twd-scraper
python3 -m venv .venv
source .venv/bin/activate      # UNIX
& .\.venv\Scripts\Activate.ps1 # Windows PowerShell
pip install -e ".[dev]"
```

Requires Python ≥ 3.14.

## Usage

### CLI

```bash
# Scrape all pages (starting from page 0)
vtes-scraper scrape

# Scrape pages 0–4 only (--last-page is inclusive, 0-indexed)
vtes-scraper scrape --last-page 4

# Start scraping from page 5 and stop at page 6
vtes-scraper scrape --start-page 5 --last-page 6

# Overwrite existing YAML files
vtes-scraper scrape --overwrite

# Write output to a custom directory
vtes-scraper scrape --output-dir path/to/dir

# Parse a single local .txt file to YAML (prints to stdout)
vtes-scraper parse decks/8470.txt

# Parse a .txt file and write YAML to a directory
vtes-scraper parse decks/8470.txt --output-dir twds

# Convert a YAML file back to .txt (prints to stdout)
vtes-scraper parse twds/2023/03/9999.yaml

# Publish new decks as a single PR to GiottoVerducci/TWD
GITHUB_TOKEN=ghp_xxx vtes-scraper publish

# Publish including pre-2020 decks (skipped by default)
GITHUB_TOKEN=ghp_xxx vtes-scraper publish --include-pre-2020

# Simulate publish without opening a PR (branch is deleted afterwards)
GITHUB_TOKEN=ghp_xxx vtes-scraper publish --dry-run
```

### Python API

```python
import httpx
from vtes_scraper.scraper import scrape_forum
from vtes_scraper.output import write_tournament_yaml
from pathlib import Path

with httpx.Client() as client:
    for tournament, icon in scrape_forum(client, max_pages=2, start_page=5):
        write_tournament_yaml(tournament, output_dir=Path("twds"))
```

## Development

```bash
# Run tests
pytest

# Lint + format
ruff check vtes_scraper/ tests/
ruff format vtes_scraper/ tests/
```

## GitHub Actions

The workflow in `.github/workflows/scrape.yml`:

- Runs daily at 06:00 UTC
- Also triggered on push to `main` when source files change
- Can be triggered manually with optional `start_page`, `last_page`, and `overwrite` inputs
- Runs tests, scrapes the forum, and commits new YAML files automatically

The workflow in `.github/workflows/publish.yml`:

- Runs every Monday at 08:00 UTC
- Can be triggered manually
- Runs tests, then publishes all new decks to the GiottoVerducci/TWD repository as a single PR
- Commits a Markdown publish report to `publish/YYYY/MM/`

## YAML output example

```yaml
name: Conservative Agitation
location: Vila Velha, Brazil
date_start: October 1st 2016
rounds_format: 2R+F
players_count: 12
winner: Ravel Zorzal
vekn_number: 3200001
event_url: https://www.vekn.net/event-calendar/event/8470
event_id: '8470'
vp_comment: 5VP in final
deck:
  name: Eyes of the Insane
  created_by: Bobby Lemon
  description: A great deck that wins all the time.
  crypt_count: 12
  crypt:
    - count: 2
      name: Nathan Turner
      capacity: 4
      disciplines: PRO ani
      clan_set: Gangrel:6
  library_count: 89
  library_sections:
    - name: Master
      count: 14
      cards:
        - count: 1
          name: Anarch Free Press, The
          comment: does not provide a free press!
```

## Project structure

```txt
vtes-twd-scraper/
├── vtes_scraper/
│   ├── cli/
│   │   ├── __init__.py        # CLI entry point (vtes-scraper) and argparse setup
│   │   ├── _common.py         # CLI shared utilities
│   │   ├── parse.py           # CLI command: parse .txt ↔ .yaml
│   │   ├── publish.py         # CLI command: publish decks to GitHub
│   │   └── scrape.py          # CLI command: scrape the VEKN forum
│   ├── output/
│   │   ├── __init__.py
│   │   ├── _common.py         # Output shared utilities
│   │   ├── txt.py             # TXT serializer
│   │   └── yaml.py            # YAML serializer
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── _deck.py           # Deck section parser
│   │   ├── _header.py         # Tournament header parser
│   │   ├── _helpers.py        # Parser utilities
│   │   └── _twd.py            # Top-level TWD text format parser
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── _forum.py          # Forum index traversal and TWD extraction
│   │   ├── _http.py           # Low-level HTTP helpers and constants
│   │   ├── _icons.py          # Topic icon detection
│   │   └── _vekn.py           # VEKN event calendar and player registry lookups
│   ├── models.py              # Pydantic data models
│   ├── publisher.py           # GitHub PR publisher
│   └── validator.py           # YAML validation logic
├── tests/
│   ├── test_cli_common.py
│   ├── test_cli_parse.py
│   ├── test_cli_publish.py
│   ├── test_cli_scrape.py
│   ├── test_models.py
│   ├── test_output.py
│   ├── test_parser.py
│   ├── test_parser_extras.py
│   ├── test_publisher.py
│   ├── test_scraper.py
│   ├── test_scraper_icons.py
│   └── test_validator.py
├── twds/                      # Scraped YAML files (YYYY/MM/<event_id>.yaml)
├── publish/                   # Markdown publish reports (YYYY/MM/<date>.md)
├── .github/
│   └── workflows/
│       ├── scrape.yml         # CRON scrape at 06:00 UTC every day
│       ├── publish.yml        # CRON publish at 08:00 UTC every Monday
│       └── feature-review.yml # Automated feature-request review
├── pyproject.toml
└── .env.example
```

## Notes

- The scraper respects a 1.5s delay between requests by default (`--delay`).
- Use `--start-page` / `--last-page` to target a specific page range. Both are 0-indexed; `--last-page` is inclusive (page 0 = `limitstart=0`, page 1 = `limitstart=20`, etc.).
- Winner lookup against the VEKN member database is applied automatically during scraping. `vekn_number` is written to the file. Unresolvable names are flagged but not blocked.
- Content validation routes tournaments with errors to `twds/errors/<error_type>/` automatically.
- Forum posts marked with the "merged" icon are written to `twds/changes_required/` instead of the normal date tree, so they can be reviewed before merging.
- `publish --dry-run` commits all files to a temporary branch to verify behaviour, then deletes the branch without opening a PR. A dry-run report is saved to `publish/YYYY/MM/dry-run-{date}-{HH-MM-SS}.md`.
- The `User-Agent` header identifies the bot to the server.
- Always verify `robots.txt` and VEKN forum terms before large-scale scraping.
