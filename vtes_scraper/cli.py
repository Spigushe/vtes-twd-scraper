"""
CLI for VTES TWD scraper.

Usage examples:
  # Scrape all pages and write YAMLs to ./output/
  python -m vtes_scraper scrape

  # Scrape only first 2 pages, overwrite existing files
  python -m vtes_scraper scrape --max-pages 2 --overwrite

  # Parse a single local .txt file
  python -m vtes_scraper parse my_deck.txt

  # Print result to stdout (no file written)
  python -m vtes_scraper parse my_deck.txt --stdout
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler

from vtes_scraper.output import tournament_to_yaml_str, write_tournament_yaml
from vtes_scraper.parser import parse_twd_text
from vtes_scraper.scraper import scrape_forum

# On Windows, stdout/stderr default to cp1252 which cannot encode Rich's
# box-drawing characters (─, —, etc.) or accented names from non-Latin locales.
# Reconfigure both streams to UTF-8 before any Rich output.
if sys.platform == "win32":
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )

app = typer.Typer(
    name="vtes-scraper",
    help="Scrape VTES tournament winning decks from vekn.net and export to YAML.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


# ---------------------------------------------------------------------------
# Command: scrape
# ---------------------------------------------------------------------------


@app.command()
def scrape(
    output_dir: Path = typer.Option(
        Path("output"),
        "--output-dir",
        "-o",
        help="Directory where YAML files will be written.",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="Limit the number of forum index pages to scrape (default: all).",
    ),
    delay: float = typer.Option(
        1.5,
        "--delay",
        help="Seconds between HTTP requests (be polite to the server).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing YAML files.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Scrape the VEKN forum and export each TWD as a YAML file."""
    _setup_logging(verbose)
    logger = logging.getLogger(__name__)

    written = skipped = failed = 0

    for tournament in scrape_forum(max_pages=max_pages, delay=delay):
        try:
            path = write_tournament_yaml(tournament, output_dir, overwrite=overwrite)
            console.print(f"[green]✓[/green] {path.name}  {tournament.name}")
            written += 1
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")
            skipped += 1
        except Exception as exc:
            console.print(f"[red]✗[/red] {tournament.event_id}: {exc}")
            logger.debug("Stack trace:", exc_info=True)
            failed += 1

    console.rule()
    console.print(
        f"Done — [green]{written} written[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red]"
    )
    if failed:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Command: parse (single file, useful for testing)
# ---------------------------------------------------------------------------


@app.command()
def parse(
    input_file: Path = typer.Argument(..., help="Path to a TWD .txt file."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to write the YAML file. If omitted, prints to stdout.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Parse a single local TWD .txt file into YAML."""
    _setup_logging(verbose)

    raw = input_file.read_text(encoding="utf-8")
    try:
        tournament = parse_twd_text(raw)
    except ValueError as exc:
        console.print(f"[red]Parse error:[/red] {exc}")
        raise typer.Exit(code=1)

    if output_dir is None:
        # Print YAML to stdout
        console.print(tournament_to_yaml_str(tournament))
    else:
        try:
            path = write_tournament_yaml(tournament, output_dir, overwrite=overwrite)
            console.print(f"[green]✓[/green] Written to {path}")
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
