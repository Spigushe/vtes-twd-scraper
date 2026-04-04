"""
CLI for VTES TWD scraper.

Usage examples in README file
"""

import argparse
import sys

from vtes_scraper.cli import parse, publish, scrape, validate
from vtes_scraper.cli._common import SubParsersAction, reconfigure_windows_stdio


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtes-scraper",
        description="Scrape VTES tournament winning decks from vekn.net and export to YAML.",
    )
    sub: SubParsersAction = parser.add_subparsers(dest="command", required=True)
    scrape.register(sub)
    parse.register(sub)
    publish.register(sub)
    validate.register(sub)
    return parser


def main() -> None:
    reconfigure_windows_stdio()
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
