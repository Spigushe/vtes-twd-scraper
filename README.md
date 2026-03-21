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
# Scrape all pages, write YAMLs to ./twds/YYYY/MM/
vtes-scraper scrape

# Scrape first 3 pages only, overwrite existing files
vtes-scraper scrape --max-pages 3 --overwrite

# Start scraping from page 5 (skip pages 0–4)
vtes-scraper scrape --start-page 5

# Scrape pages 5 and 6 only (useful to resume or target a range)
vtes-scraper scrape --start-page 5 --max-pages 2

# Parse a single local .txt file
vtes-scraper parse decks/8470.txt

# Validate scraped decks and move invalid ones to twds/errors/
vtes-scraper validate

# Also cross-reference dates against the VEKN event calendar
vtes-scraper validate --check-dates

# Also verify winners against the VEKN member database (writes vekn_number to files)
vtes-scraper validate --check-players

# Fix date_start in one or more YAML files to match the VEKN calendar
vtes-scraper fix-date twds/2026/01/12957.yaml
vtes-scraper fix-date twds/2026/01/*.yaml --dry-run

# Re-fetch decks that ended up in twds/errors/ and rewrite them
vtes-scraper rescrape

# Publish new decks as a single PR to GiottoVerducci/TWD
GITHUB_TOKEN=ghp_xxx vtes-scraper publish

# Publish including pre-2020 decks (skipped by default)
GITHUB_TOKEN=ghp_xxx vtes-scraper publish --include-pre-2020
```

### Python API

```python
from vtes_scraper.scraper import scrape_forum
from vtes_scraper.output import write_tournament_yaml
from pathlib import Path

for tournament, icon in scrape_forum(max_pages=2, start_page=5):
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
- Can be triggered manually with optional `max_pages` and `overwrite` inputs
- Runs tests, scrapes the forum, validates the results, and commits new YAML files automatically

The workflow in `.github/workflows/publish.yml`:

- Runs every Monday at 08:00 UTC
- Can be triggered manually
- Runs `validate --check-players` to enrich files with VEKN numbers before publishing
- Creates a single PR to the GiottoVerducci/TWD repository with all new decks
- Commits a Markdown publish report to `publish/YYYY/MM/`

## YAML output example

```yaml
name: Conservative Agitation
location: Vila Velha, Brazil
date_start: October 1st 2016
rounds_format: 2R+F
players_count: 12
winner: Ravel Zorzal
vekn_number: '3200001'
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
│   │   ├── __init__.py   # CLI entry point and shared argparse instance
│   │   ├── _common.py    # CLI shared utilities
│   │   ├── fix_dates.py  # CLI command for fixing date_start fields
│   │   ├── parse.py      # CLI command for parsing local .txt files
│   │   ├── publish.py    # CLI command for publishing to GitHub
│   │   ├── rescrape.py   # CLI command for re-fetching errored decks
│   │   ├── scrape.py     # CLI command for scraping the VEKN forum
│   │   └── validate.py   # CLI command for validating scraped YAML files
│   ├── output/
│   │   ├── __init__.py
│   │   ├── _common.py    # Output shared utilities
│   │   ├── txt.py        # TXT serializer
│   │   └── yaml.py       # YAML serializer
│   ├── models.py         # Pydantic data models
│   ├── parser.py         # TWD text format parser
│   ├── publisher.py      # GitHub PR publisher
│   ├── scraper.py        # Forum scraper (httpx + BeautifulSoup)
│   └── validator.py      # YAML validation logic
├── tests/
│   ├── test_cli.py
│   ├── test_models.py
│   ├── test_output.py
│   ├── test_parser.py
│   ├── test_parser_extras.py
│   ├── test_publisher.py
│   ├── test_scraper.py
│   └── test_scraper_icons.py
├── twds/                 # Scraped YAML files (YYYY/MM/<event_id>.yaml)
├── publish/              # Markdown publish reports (YYYY/MM/<date>.md)
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
- Use `--start-page` to resume an interrupted run or target a specific page range. Pages are 0-indexed (page 0 = `limitstart=0`, page 1 = `limitstart=20`, etc.).
- Forum posts marked with the "merged" icon are written to `twds/changes_required/` instead of the normal date tree, so they can be reviewed before merging.
- `validate --check-players` writes a `vekn_number` field to each file and caches resolved name mappings in `twds/coercions.json` to avoid repeated HTTP requests.
- The `User-Agent` header identifies the bot to the server.
- Always verify `robots.txt` and VEKN forum terms before large-scale scraping.
