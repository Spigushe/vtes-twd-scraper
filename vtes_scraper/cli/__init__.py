"""
CLI for VTES TWD scraper.

Usage examples in README file
"""

from __future__ import annotations

import argparse
import sys

from vtes_scraper.cli import fix_dates, parse, publish, scrape, validate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtes-scraper",
        description="Scrape VTES tournament winning decks from vekn.net and export to YAML.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scrape.register(sub)
    parse.register(sub)
    publish.register(sub)
    validate.register(sub)
    fix_dates.register(sub)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
