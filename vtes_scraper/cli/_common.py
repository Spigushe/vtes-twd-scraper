"""Shared helpers for all CLI subcommands."""

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler


# On Windows, stdout/stderr default to cp1252 which cannot encode Rich's
# box-drawing characters (─, —, etc.) or accented names from non-Latin locales.
# Reconfigure both streams to UTF-8 before any Rich output.
#
# IMPORTANT: this must NOT run at import time when pytest is active — replacing
# sys.stdout/stderr mid-capture closes the underlying tempfile that pytest owns,
# which causes a "ValueError: I/O operation on closed file" crash on Python 3.14
# (which now closes the underlying buffer when a TextIOWrapper is GC'd).
def _reconfigure_windows_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows. Call once from main()."""
    if sys.platform == "win32":
        import io

        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
            )
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
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
