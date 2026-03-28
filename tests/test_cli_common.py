"""Tests for CLI entry point and shared utilities (_build_parser, main, _common)."""

import io
import logging
from unittest.mock import patch

import pytest

from vtes_scraper.cli import _build_parser, main
from vtes_scraper.cli._common import _reconfigure_windows_stdio, setup_logging

# ---------------------------------------------------------------------------
# _build_parser / main
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_parser_created(self):
        parser = _build_parser()
        assert parser is not None

    def test_subcommands_registered(self):
        parser = _build_parser()
        # Parse known subcommands — should not raise
        args = parser.parse_args(["parse", "somefile.txt"])
        assert args.command == "parse"

    def test_scrape_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["scrape", "--fast-check"])
        assert args.command == "scrape"

    def test_validate_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["validate"])
        assert args.command == "validate"


class TestMain:
    def test_main_dispatches_and_exits(self):
        with (
            patch("sys.argv", ["vtes-scraper", "scrape", "--fast-check"]),
            patch("vtes_scraper.cli._reconfigure_windows_stdio"),
            patch("vtes_scraper.cli.scrape.run", return_value=0) as mock_run,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# _reconfigure_windows_stdio
# ---------------------------------------------------------------------------


class TestReconfigureWindowsStdio:
    def test_noop_on_non_windows(self):
        import sys as real_sys

        original_stdout = real_sys.stdout
        with patch("vtes_scraper.cli._common.sys") as mock_sys:
            mock_sys.platform = "linux"
            _reconfigure_windows_stdio()
        # Real sys.stdout must be untouched
        assert real_sys.stdout is original_stdout

    def test_reconfigures_on_windows(self):
        fake_buffer = io.BytesIO(b"")
        fake_stdout = io.TextIOWrapper(fake_buffer)
        fake_stderr_buffer = io.BytesIO(b"")
        fake_stderr = io.TextIOWrapper(fake_stderr_buffer)
        with patch("vtes_scraper.cli._common.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.stdout = fake_stdout
            mock_sys.stderr = fake_stderr
            _reconfigure_windows_stdio()
            # After reconfiguration, mock_sys.stdout should be a new TextIOWrapper
            assert isinstance(mock_sys.stdout, io.TextIOWrapper)
            assert mock_sys.stdout is not fake_stdout

    def test_skips_when_no_buffer(self):
        no_buffer_stdout = io.StringIO()
        no_buffer_stderr = io.StringIO()
        with patch("vtes_scraper.cli._common.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.stdout = no_buffer_stdout
            mock_sys.stderr = no_buffer_stderr
            # Should not raise even without .buffer
            _reconfigure_windows_stdio()
            assert isinstance(mock_sys.stdout, io.StringIO)


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_verbose_false(self):
        setup_logging(False)
        logger = logging.getLogger("vtes_scraper")
        # In non-verbose mode, vtes_scraper logger should NOT be at DEBUG
        assert logger.level != logging.DEBUG

    def test_verbose_true(self):
        setup_logging(True)
        logger = logging.getLogger("vtes_scraper")
        assert logger.level == logging.DEBUG
