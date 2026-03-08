"""CLI subcommand: parse."""

from __future__ import annotations

import argparse
from pathlib import Path

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.output import tournament_to_yaml_str, write_tournament_yaml
from vtes_scraper.parser import parse_twd_text


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("parse", help="Parse a single local TWD .txt file into YAML.")
    p.add_argument("input_file", type=Path, help="Path to a TWD .txt file.")
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        dest="output_dir",
        help="Directory to write the YAML file. If omitted, prints to stdout.",
    )
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Parse a single local TWD .txt file into YAML."""
    setup_logging(args.verbose)

    raw = args.input_file.read_text(encoding="utf-8")
    try:
        tournament = parse_twd_text(raw)
    except ValueError as exc:
        console.print(f"[red]Parse error:[/red] {exc}")
        return 1

    if args.output_dir is None:
        console.print(tournament_to_yaml_str(tournament))
    else:
        try:
            path = write_tournament_yaml(
                tournament,
                args.output_dir,
                overwrite=args.overwrite,
            )
            console.print(f"[green]✓[/green] Written to {path}")
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")
    return 0
