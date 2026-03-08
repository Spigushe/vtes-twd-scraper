# vtes-twd-scraper

Scrape tournament winning decks (TWD) from the [VEKN forum](https://www.vekn.net/forum/event-reports-and-twd) and export them as YAML files.

## Data format

Each tournament produces one YAML file named `{event_id}.yaml` where `event_id` is the numeric id from the VEKN event calendar URL (e.g. `/event/8470` → `8470.yaml`).

This convention mirrors the [GiottoVerducci/TWD](https://github.com/GiottoVerducci/TWD) archive, which uses `decks/{event_id}.txt`.

## Installation

```bash
pip install -e ".[dev]"
```

Requires Python ≥ 3.11.

## Usage

### CLI

```bash
# Scrape all pages, write YAMLs to ./output/
vtes-scraper scrape

# Scrape first 3 pages only, overwrite existing files
vtes-scraper scrape --max-pages 3 --overwrite

# Parse a single local .txt file
vtes-scraper parse decks/8470.txt

# Parse and print to stdout (no file written)
vtes-scraper parse decks/8470.txt
```

### Python API

```python
from vtes_scraper import scrape_forum, write_tournament_yaml
from pathlib import Path

for tournament in scrape_forum(max_pages=2):
    write_tournament_yaml(tournament, output_dir=Path("output"))
```

## Development

```bash
# Run tests
pytest

# Lint + format
ruff check vtes_scraper/ tests/
ruff format vtes_scraper/ tests/
```

## GitHub Action

The workflow in `.github/workflows/scrape.yml`:
- Runs daily at 06:00 UTC
- Can be triggered manually with optional `max_pages` and `overwrite` inputs
- Commits new YAML files to the repository automatically

## YAML output example

```yaml
name: Conservative Agitation
location: Vila Velha, Brazil
date_start: October 1st 2016
rounds_format: 2R+F
players_count: 12
winner: Ravel Zorzal
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

```
vtes-twd-scraper/
├── src/vtes_scraper/
│   ├── models.py     # Pydantic data models
│   ├── parser.py     # TWD text format parser
│   ├── scraper.py    # Forum scraper (httpx + BeautifulSoup)
│   ├── output.py     # YAML serializer (ruamel.yaml)
│   └── cli.py        # Typer CLI
├── tests/
│   └── test_parser.py
├── .github/workflows/scrape.yml
└── pyproject.toml
```

## Notes

- The scraper respects a 1.5s delay between requests by default (`--delay`).
- The `User-Agent` header identifies the bot to the server.
- Always verify `robots.txt` and VEKN forum terms before large-scale scraping.
