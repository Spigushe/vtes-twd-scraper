"""Shared helpers for all CLI subcommands."""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

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

console = Console()


def setup_logging(verbose: bool) -> None:
    handler = RichHandler(rich_tracebacks=True, show_path=False)
    logging.basicConfig(
        level=logging.ERROR,
        format="%(message)s",
        handlers=[handler],
    )
    if verbose:
        logging.getLogger("vtes_scraper").setLevel(logging.DEBUG)
