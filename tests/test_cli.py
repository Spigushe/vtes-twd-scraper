"""Tests for CLI subcommands."""

import argparse
import logging
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import vtes_scraper.scraper as scraper_mod
from vtes_scraper import validator
from vtes_scraper.cli import _build_parser, _common
from vtes_scraper.cli import fix_dates as fix_dates_cmd
from vtes_scraper.cli import main
from vtes_scraper.cli import parse as parse_cmd
from vtes_scraper.cli import publish as publish_cmd
from vtes_scraper.cli import rescrape as rescrape_cmd
from vtes_scraper.cli import scrape as scrape_cmd
from vtes_scraper.cli import validate as validate_cmd
from vtes_scraper.cli._common import _reconfigure_windows_stdio, setup_logging
from vtes_scraper.models import CryptCard, Deck, LibraryCard, LibrarySection, Tournament
from vtes_scraper.publisher import BatchPRResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SIMPLE_TWD = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


def _make_tournament() -> Tournament:
    return Tournament(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=Deck(
            crypt=[
                CryptCard(
                    count=2,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO ani",
                    clan="Gangrel",
                    grouping=6,
                )
            ],
            crypt_count=2,
            crypt_min=4,
            crypt_max=4,
            crypt_avg=4.0,
            library_sections=[
                LibrarySection(
                    name="Master",
                    count=1,
                    cards=[LibraryCard(count=1, name="Blood Doll")],
                )
            ],
            library_count=1,
        ),
    )


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
        import io

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
        import io

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


# ---------------------------------------------------------------------------
# parse command
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        parse_cmd.register(sub)
        args = parser.parse_args(["parse", "input.txt"])
        assert args.command == "parse"

    def test_run_stdout(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(SIMPLE_TWD)
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            input_file=tmpfile,
            output_dir=None,
            overwrite=False,
            verbose=False,
        )
        ret = parse_cmd.run(args)
        assert ret == 0
        tmpfile.unlink()

    def test_run_with_output_dir(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(SIMPLE_TWD)
            tmpfile = Path(f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                input_file=tmpfile,
                output_dir=Path(tmpdir),
                overwrite=False,
                verbose=False,
            )
            ret = parse_cmd.run(args)
            assert ret == 0

        tmpfile.unlink()

    def test_run_parse_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Not a valid TWD file")
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            input_file=tmpfile,
            output_dir=None,
            overwrite=False,
            verbose=False,
        )
        ret = parse_cmd.run(args)
        assert ret == 1
        tmpfile.unlink()

    def test_run_file_exists_no_overwrite(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(SIMPLE_TWD)
            tmpfile = Path(f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                input_file=tmpfile,
                output_dir=Path(tmpdir),
                overwrite=False,
                verbose=False,
            )
            parse_cmd.run(args)  # first write
            ret = parse_cmd.run(args)  # second write — skipped
            assert ret == 0  # FileExistsError is caught, returns 0

        tmpfile.unlink()


# ---------------------------------------------------------------------------
# scrape command
# ---------------------------------------------------------------------------


def _scrape_namespace(**kwargs) -> argparse.Namespace:
    """Build a scrape Namespace with sensible defaults for tests."""
    defaults = dict(
        output_dir=Path("twds"),
        fast_check=True,
        slow_check=False,
        start_page=0,
        last_page=None,
        delay=0,
        overwrite=False,
        verbose=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestScrapeCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--fast-check"])
        assert args.command == "scrape"

    def test_register_requires_check_flag(self):
        """Omitting both --fast-check and --slow-check must be an error."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        with pytest.raises(SystemExit):
            parser.parse_args(["scrape"])

    def test_register_mutual_exclusion(self):
        """Using both --fast-check and --slow-check must be an error."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        with pytest.raises(SystemExit):
            parser.parse_args(["scrape", "--fast-check", "--slow-check"])

    def test_register_fast_check_sets_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--fast-check"])
        assert args.fast_check is True
        assert args.slow_check is False

    def test_register_slow_check_sets_flag(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--slow-check"])
        assert args.slow_check is True
        assert args.fast_check is False

    def test_register_last_page_default(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--fast-check"])
        assert args.last_page is None

    def test_register_last_page_set(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--fast-check", "--last-page", "5"])
        assert args.last_page == 5

    def test_register_start_and_last_page(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(
            ["scrape", "--fast-check", "--start-page", "2", "--last-page", "7"]
        )
        assert args.start_page == 2
        assert args.last_page == 7

    def test_run_no_tournaments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with patch("vtes_scraper.cli.scrape.scrape_forum", return_value=iter([])):
                ret = scrape_cmd.run(args)
            assert ret == 0

    def test_run_with_tournament_written(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player", return_value=None),
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0

    def test_run_with_file_exists_skipped(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player", return_value=None),
                patch(
                    "vtes_scraper.cli.scrape.write_tournament_yaml",
                    side_effect=FileExistsError("exists"),
                ),
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0

    def test_run_with_general_error(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player", return_value=None),
                patch(
                    "vtes_scraper.cli.scrape.write_tournament_yaml",
                    side_effect=Exception("error"),
                ),
            ):
                ret = scrape_cmd.run(args)
            assert ret == 1

    def test_run_fast_check_passes_true_to_scrape_forum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(
                output_dir=Path(tmpdir), fast_check=True, slow_check=False
            )
            with patch(
                "vtes_scraper.cli.scrape.scrape_forum", return_value=iter([])
            ) as mock_sf:
                scrape_cmd.run(args)
            _, kwargs = mock_sf.call_args
            assert kwargs["fast_check"] is True

    def test_run_slow_check_passes_false_to_scrape_forum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(
                output_dir=Path(tmpdir), fast_check=False, slow_check=True
            )
            with patch(
                "vtes_scraper.cli.scrape.scrape_forum", return_value=iter([])
            ) as mock_sf:
                scrape_cmd.run(args)
            _, kwargs = mock_sf.call_args
            assert kwargs["fast_check"] is False

    def test_run_last_page_computes_max_pages(self):
        """last_page=4, start_page=2 → max_pages=3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir), start_page=2, last_page=4)
            with patch(
                "vtes_scraper.cli.scrape.scrape_forum", return_value=iter([])
            ) as mock_sf:
                scrape_cmd.run(args)
            _, kwargs = mock_sf.call_args
            assert kwargs["max_pages"] == 3

    def test_run_no_last_page_passes_none_max_pages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir), last_page=None)
            with patch(
                "vtes_scraper.cli.scrape.scrape_forum", return_value=iter([])
            ) as mock_sf:
                scrape_cmd.run(args)
            _, kwargs = mock_sf.call_args
            assert kwargs["max_pages"] is None

    def test_run_enriches_winner_with_vekn_number(self):
        """Player lookup always runs; resolved name and vekn_number end up in the file."""
        t = _make_tournament()
        assert t.vekn_number is None

        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch(
                    "vtes_scraper.scraper.fetch_player",
                    return_value=("Jane Doe", 3940009),
                ),
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1
            content = written[0].read_text(encoding="utf-8")
            assert "vekn_number: 3940009" in content

    def test_run_unknown_winner_still_written(self):
        """Unresolvable winners are written without vekn_number (not blocked)."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player", return_value=None),
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1

    def test_run_coercions_saved_on_new_resolution(self):
        """coercions.json is created/updated when a new player name is resolved."""
        import json

        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch(
                    "vtes_scraper.scraper.fetch_player",
                    return_value=("Jane Doe", 3940009),
                ),
            ):
                scrape_cmd.run(args)
            coercions_path = Path(tmpdir) / "coercions.json"
            assert coercions_path.exists()
            data = json.loads(coercions_path.read_text())
            assert "Jane Doe" in data

    def test_run_skips_lookup_when_vekn_number_present(self):
        """Tournaments that already carry a vekn_number are not re-looked-up."""
        t = _make_tournament()
        t = t.model_copy(update={"vekn_number": 3940009})
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player") as mock_fp,
            ):
                scrape_cmd.run(args)
            mock_fp.assert_not_called()

    def test_run_uses_coercions_cache(self):
        """Pre-populated coercions.json is used without an HTTP request."""
        import json

        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            coercions_path = Path(tmpdir) / "coercions.json"
            coercions_path.write_text(
                json.dumps(
                    {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
                ),
                encoding="utf-8",
            )
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with (
                patch(
                    "vtes_scraper.cli.scrape.scrape_forum",
                    return_value=iter([(t, None)]),
                ),
                patch("vtes_scraper.scraper.fetch_player") as mock_fp,
            ):
                scrape_cmd.run(args)
            mock_fp.assert_not_called()
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1
            content = written[0].read_text(encoding="utf-8")
            assert "vekn_number: 3940009" in content


# ---------------------------------------------------------------------------
# resolve_winner
# ---------------------------------------------------------------------------


class TestResolveWinner:
    def test_direct_lookup_success(self):
        mock_client = MagicMock()
        with patch(
            "vtes_scraper.scraper.fetch_player", return_value=("Jane Doe", 3940009)
        ):
            result = scraper_mod.resolve_winner(mock_client, "Jane Doe", delay=0)
        assert result == ("Jane Doe", 3940009)

    def test_returns_none_when_all_steps_fail(self):
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper.fetch_player", return_value=None):
            result = scraper_mod.resolve_winner(mock_client, "Jane Doe", delay=0)
        assert result is None

    def test_bracket_stripped_fallback(self):
        def fake_fp(client, name, delay=0):
            return ("Jane Doe", 1234) if name == "Jane Doe" else None

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper.fetch_player", side_effect=fake_fp):
            result = scraper_mod.resolve_winner(mock_client, "Jane Doe (", delay=0)
        assert result == ("Jane Doe", 1234)

    def test_digit_stripped_fallback(self):
        def fake_fp(client, name, delay=0):
            return ("Jane Doe", 1234) if name == "Jane Doe" else None

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper.fetch_player", side_effect=fake_fp):
            result = scraper_mod.resolve_winner(
                mock_client, "Jane Doe 3200006", delay=0
            )
        assert result == ("Jane Doe", 1234)

    def test_accent_stripped_fallback(self):
        def fake_fp(client, name, delay=0):
            return ("Jane Doe", 1234) if name == "Jane Doe" else None

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper.fetch_player", side_effect=fake_fp):
            result = scraper_mod.resolve_winner(mock_client, "Jàne Döe", delay=0)
        assert result == ("Jane Doe", 1234)

    def test_winner_prefix_stripped(self):
        mock_client = MagicMock()
        with patch(
            "vtes_scraper.scraper.fetch_player", return_value=("Jane Doe", 1234)
        ) as mock_fp:
            scraper_mod.resolve_winner(mock_client, "Winner: Jane Doe", delay=0)
        mock_fp.assert_called_once_with(mock_client, "Jane Doe", delay=0)

    def test_coercions_cache_hit_skips_http(self):
        mock_client = MagicMock()
        coercions = {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
        with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
            result = scraper_mod.resolve_winner(
                mock_client, "Jane Doe", coercions=coercions, delay=0
            )
        mock_fp.assert_not_called()
        assert result == ("Jane Doe", 3940009)

    def test_coercions_stores_new_resolution(self):
        mock_client = MagicMock()
        coercions: dict = {}
        with patch(
            "vtes_scraper.scraper.fetch_player", return_value=("Jane Doe", 3940009)
        ):
            scraper_mod.resolve_winner(
                mock_client, "Jane Doe", coercions=coercions, delay=0
            )
        assert "Jane Doe" in coercions
        assert coercions["Jane Doe"]["vekn_number"] == 3940009

    def test_step1_exception_propagates(self):
        """Network errors on step 1 propagate so the caller can choose not to move files."""
        mock_client = MagicMock()
        with patch(
            "vtes_scraper.scraper.fetch_player", side_effect=Exception("network down")
        ):
            with pytest.raises(Exception, match="network down"):
                scraper_mod.resolve_winner(mock_client, "Jane Doe", delay=0)


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

VALID_YAML = """\
name: Test Event
location: Paris, France
date_start: 2023-03-25
rounds_format: 3R+F
players_count: 15
winner: Jane Doe
event_url: https://www.vekn.net/event-calendar/event/9999
deck:
  crypt:
    - count: 2
      name: Nathan Turner
      capacity: 4
      disciplines: PRO ani
      clan: Gangrel
      grouping: 6
  crypt_count: 2
  crypt_min: 4
  crypt_max: 4
  crypt_avg: 4.0
  library_count: 1
  library_sections:
    - name: Master
      count: 1
      cards:
        - count: 1
          name: Blood Doll
"""

INVALID_YAML = """\
name: ""
location: ""
date_start: null
rounds_format: ""
players_count: 0
winner: ""
event_url: ""
deck:
  crypt: []
  library_sections: []
"""


class TestValidateCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        validate_cmd.register(sub)
        args = parser.parse_args(["validate"])
        assert args.command == "validate"

    def test_run_no_dir(self):
        args = argparse.Namespace(
            output_dir=Path("/nonexistent/path"),
            check_dates=False,
            delay=0,
            verbose=False,
        )
        ret = validate_cmd.run(args)
        assert ret == 1

    def test_run_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                delay=0,
                verbose=False,
            )
            ret = validate_cmd.run(args)
            assert ret == 0

    def test_run_valid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                delay=0,
                verbose=False,
            )
            ret = validate_cmd.run(args)
            assert ret == 0

    def test_run_invalid_file_moved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "bad.yaml"
            yaml_file.write_text(INVALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                delay=0,
                verbose=False,
            )
            ret = validate_cmd.run(args)
            assert ret == 1

    def test_run_unreadable_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "bad.yaml"
            yaml_file.write_text(": : : invalid yaml {{{{", encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                delay=0,
                verbose=False,
            )
            ret = validate_cmd.run(args)
            assert ret == 1

    def test_error_types_all_missing(self):
        errors = validator.error_types({})
        assert "missing_name" in errors
        assert "missing_location" in errors
        assert "missing_date_start" in errors
        assert "missing_rounds_format" in errors
        assert "missing_players_count" in errors
        assert "missing_winner" in errors
        assert "missing_event_url" in errors
        assert "empty_crypt" in errors
        assert "empty_library" in errors

    def test_error_types_incoherent_date(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 10,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data, calendar_date=date(2023, 2, 2))
        assert "incoherent_date" in errors

    def test_error_types_coherent_date(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 10,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data, calendar_date=date(2023, 1, 1))
        assert "incoherent_date" not in errors

    def test_error_types_too_few_players(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 9,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data)
        assert "too_few_players" in errors

    def test_error_types_not_too_few_players_at_minimum(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data)
        assert "too_few_players" not in errors

    def test_error_types_limited_format(self):
        data = {
            "name": "Belgian Limited National Championship 2022",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 14,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data)
        assert "limited_format" in errors

    def test_error_types_not_limited_format(self):
        data = {
            "name": "Test Event",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 14,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {"crypt": [1], "library_sections": [1]},
        }
        errors = validator.error_types(data)
        assert "limited_format" not in errors

    def _make_crypt_card(self, grouping):
        return {
            "count": 1,
            "name": "Test Vampire",
            "capacity": 5,
            "disciplines": "cel",
            "clan": "Brujah",
            "grouping": grouping,
        }

    def test_error_types_illegal_crypt_three_groups(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {
                "crypt": [
                    self._make_crypt_card(3),
                    self._make_crypt_card(4),
                    self._make_crypt_card(5),
                ],
                "library_sections": [1],
            },
        }
        errors = validator.error_types(data)
        assert "illegal_crypt" in errors

    def test_error_types_illegal_crypt_non_consecutive(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {
                "crypt": [
                    self._make_crypt_card(1),
                    self._make_crypt_card(6),
                ],
                "library_sections": [1],
            },
        }
        errors = validator.error_types(data)
        assert "illegal_crypt" in errors

    def test_error_types_legal_crypt_consecutive_pair(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {
                "crypt": [
                    self._make_crypt_card(4),
                    self._make_crypt_card(5),
                ],
                "library_sections": [1],
            },
        }
        errors = validator.error_types(data)
        assert "illegal_crypt" not in errors

    def test_error_types_legal_crypt_single_group(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {
                "crypt": [
                    self._make_crypt_card(4),
                    self._make_crypt_card(4),
                ],
                "library_sections": [1],
            },
        }
        errors = validator.error_types(data)
        assert "illegal_crypt" not in errors

    def test_error_types_illegal_crypt_ignores_any(self):
        data = {
            "name": "Test",
            "location": "Loc",
            "date_start": "2023-01-01",
            "rounds_format": "2R+F",
            "players_count": 12,
            "winner": "W",
            "event_url": "https://www.vekn.net/event-calendar/event/1",
            "deck": {
                "crypt": [
                    self._make_crypt_card(4),
                    self._make_crypt_card(5),
                    self._make_crypt_card("ANY"),
                ],
                "library_sections": [1],
            },
        }
        errors = validator.error_types(data)
        assert "illegal_crypt" not in errors

    def test_parse_date_field_none(self):
        result = validator.parse_date_field(None)
        assert result is None

    def test_parse_date_field_date_object(self):
        d = date(2023, 1, 1)
        result = validator.parse_date_field(d)
        assert result == d

    def test_parse_date_field_string(self):
        result = validator.parse_date_field("2023-01-01")
        assert result == date(2023, 1, 1)

    def test_parse_date_field_invalid(self):
        result = validator.parse_date_field("not-a-date")
        assert result is None

    def test_move_to_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.yaml"
            src.write_text("name: test", encoding="utf-8")
            dest = validate_cmd._move_to_error(src, Path(tmpdir), "missing_name")
            assert dest.exists()
            assert "missing_name" in str(dest)
            assert not src.exists()

    # ------------------------------------------------------------------
    # _name_without_digits
    # ------------------------------------------------------------------

    def test_name_without_digits_plain_name(self):
        assert scraper_mod._name_without_digits("Jane Doe") == "Jane Doe"

    def test_name_without_digits_name_with_number(self):
        assert (
            scraper_mod._name_without_digits("Frederic Pin 3200006") == "Frederic Pin"
        )

    def test_name_without_digits_only_digits(self):
        assert scraper_mod._name_without_digits("12345") == ""

    def test_name_without_digits_mixed(self):
        assert scraper_mod._name_without_digits("John 42 Smith") == "John Smith"

    # ------------------------------------------------------------------
    # _name_without_accents helper
    # ------------------------------------------------------------------

    def test_name_without_accents_plain(self):
        assert scraper_mod._name_without_accents("Jane Doe") == "Jane Doe"

    def test_name_without_accents_with_diacritics(self):
        assert scraper_mod._name_without_accents("Frédéric Pïn") == "Frederic Pin"

    def test_name_without_accents_with_non_word_chars(self):
        assert scraper_mod._name_without_accents("O'Brien") == "OBrien"

    def test_name_without_accents_already_ascii(self):
        assert scraper_mod._name_without_accents("John Smith") == "John Smith"

    # ------------------------------------------------------------------
    # --check-players argument registered
    # ------------------------------------------------------------------

    def test_register_check_players_arg(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        validate_cmd.register(sub)
        args = parser.parse_args(["validate", "--check-players"])
        assert args.check_players is True

    def test_register_check_players_default_false(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        validate_cmd.register(sub)
        args = parser.parse_args(["validate"])
        assert args.check_players is False

    # ------------------------------------------------------------------
    # _check_player logic
    # ------------------------------------------------------------------

    def test_check_player_found_exact_name(self):
        """When fetch_player returns a match with the same name, vekn_number is added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is True
            assert moved is False
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert updated["winner"] == "Jane Doe"

    def test_check_player_found_after_digit_strip(self):
        """When initial search fails but digit-stripped name succeeds, winner is updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            dirty_yaml = VALID_YAML.replace(
                "winner: Jane Doe", "winner: Jane Doe 3940009"
            )
            yaml_file.write_text(dirty_yaml, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)

            def fake_fetch_player(client, name, delay=0):
                if "3940009" in name:
                    return None
                return ("Jane Doe", 3940009)

            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player", side_effect=fake_fetch_player
            ):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is True
            assert moved is False
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert updated["winner"] == "Jane Doe"

    def test_check_player_found_after_winner_prefix_strip(self):
        """When winner field starts with 'Winner:' label, the prefix is stripped first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            prefixed_yaml = VALID_YAML.replace(
                "winner: Jane Doe", "winner: 'Winner: Jane Doe'"
            )
            yaml_file.write_text(prefixed_yaml, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ) as mock_fetch:
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is True
            assert moved is False
            # fetch_player must have been called with the clean name, not the prefixed one
            mock_fetch.assert_called_once_with(mock_client, "Jane Doe", delay=0)
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert updated["winner"] == "Jane Doe"

    def test_check_player_found_after_accent_strip(self):
        """When original and digit-stripped searches fail, accent-stripped name succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            accented_yaml = VALID_YAML.replace("winner: Jane Doe", "winner: Jàne Döe")
            yaml_file.write_text(accented_yaml, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)

            def fake_fetch_player(client, name, delay=0):
                # Only the plain ASCII form matches
                if name == "Jane Doe":
                    return ("Jane Doe", 3940009)
                return None

            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player", side_effect=fake_fetch_player
            ):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is True
            assert moved is False
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert updated["winner"] == "Jane Doe"

    def test_check_player_found_after_bracket_and_accent_strip(self):
        """Bracket-stripped form fails but accent-stripped bracket-stripped form succeeds.

        Regression for "David Vallès Gómez (" where the accented+bracket form is
        not in VEKN but the plain ASCII form "David Valles Gomez" is.  The bracket
        must be stripped from *winner* before the accent step runs.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            raw = "David Vallès Gómez ("
            yaml_file.write_text(
                VALID_YAML.replace("winner: Jane Doe", f"winner: '{raw}'"),
                encoding="utf-8",
            )
            data = validate_cmd._load_yaml(yaml_file)

            def fake_fetch_player(client, name, delay=0):
                # Only the plain ASCII form (no bracket, no accents) matches.
                if name == "David Valles Gomez":
                    return ("David Valles Gomez", 1234567)
                return None

            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player", side_effect=fake_fetch_player
            ):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is True
            assert moved is False
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["winner"] == "David Valles Gomez"
            assert updated["vekn_number"] == 1234567

    def test_check_player_not_found_moves_to_unknown_winner(self):
        """When fetch_player returns None for both attempts, file is moved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            with patch("vtes_scraper.scraper.fetch_player", return_value=None):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is False
            assert moved is True
            assert not yaml_file.exists()
            assert (Path(tmpdir) / "errors" / "unknown_winner" / "test.yaml").exists()

    def test_check_player_skips_when_winner_empty(self):
        """An empty winner field is skipped gracefully without network calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            data["winner"] = ""
            mock_client = MagicMock()
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            mock_fp.assert_not_called()
            assert found is False
            assert moved is False

    def test_check_player_network_error_is_non_fatal(self):
        """A network exception during player lookup does not move the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            with patch(
                "vtes_scraper.scraper.fetch_player",
                side_effect=Exception("network error"),
            ):
                found, moved = validate_cmd._check_player(
                    mock_client, yaml_file, data, Path(tmpdir), 0, logging.getLogger()
                )
            assert found is False
            assert moved is False
            assert yaml_file.exists()

    # ------------------------------------------------------------------
    # run() with --check-players
    # ------------------------------------------------------------------

    def test_run_check_players_skips_when_vekn_number_present(self):
        """Files that already have a vekn_number are not re-checked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_with_vekn = VALID_YAML + "vekn_number: 1234567\n"
            yaml_file.write_text(yaml_with_vekn, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                ret = validate_cmd.run(args)
            mock_fp.assert_not_called()
            assert ret == 0

    def test_run_check_players_found(self):
        """run() with --check-players writes vekn_number on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ):
                ret = validate_cmd.run(args)
            assert ret == 0
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009

    def test_run_check_unknowns_recovers_unknown_winner_file(self):
        """--check-unknowns retries errors/unknown_winner/ files and moves them back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            error_dir = Path(tmpdir) / "errors" / "unknown_winner"
            error_dir.mkdir(parents=True)
            yaml_file = error_dir / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=False,
                check_unknowns=True,
                delay=0,
                verbose=False,
            )
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ):
                ret = validate_cmd.run(args)
            assert ret == 0
            # File should have been moved back to its canonical YYYY/MM/ location.
            # VALID_YAML has date_start: 2023-03-25
            recovered = Path(tmpdir) / "2023" / "03" / "test.yaml"
            assert (
                recovered.exists()
            ), "file was not moved back from errors/unknown_winner/"
            assert not yaml_file.exists(), "original error file should be gone"

    def test_run_check_players_does_not_include_unknown_winner_files(self):
        """--check-players alone does not pick up files from errors/unknown_winner/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            error_dir = Path(tmpdir) / "errors" / "unknown_winner"
            error_dir.mkdir(parents=True)
            yaml_file = error_dir / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                check_unknowns=False,
                delay=0,
                verbose=False,
            )
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                ret = validate_cmd.run(args)
            mock_fp.assert_not_called()
            assert yaml_file.exists(), "error file should not have been touched"

    def test_run_check_players_not_found_moves_file(self):
        """run() with --check-players moves unknown winners to errors/unknown_winner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch("vtes_scraper.scraper.fetch_player", return_value=None):
                ret = validate_cmd.run(args)
            assert ret == 1
            assert not yaml_file.exists()
            assert (Path(tmpdir) / "errors" / "unknown_winner" / "test.yaml").exists()

    def test_run_check_players_invalid_file_not_checked(self):
        """Invalid files are moved by schema validation before player check runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "bad.yaml"
            yaml_file.write_text(INVALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                ret = validate_cmd.run(args)
            mock_fp.assert_not_called()
            assert ret == 1

    # ------------------------------------------------------------------
    # coercions cache
    # ------------------------------------------------------------------

    def test_check_player_stores_resolution_in_coercions(self):
        """A successful lookup is recorded in the coercions dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            coercions: dict = {}
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ):
                validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            assert "Jane Doe" in coercions
            assert coercions["Jane Doe"]["winner"] == "Jane Doe"
            assert coercions["Jane Doe"]["vekn_number"] == 3940009

    def test_check_player_uses_coercions_cache_skips_http(self):
        """When the winner is in the coercions cache no HTTP request is made."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            coercions = {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            mock_fp.assert_not_called()
            assert found is True
            assert moved is False
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009

    def test_check_player_coercions_corrects_winner_name(self):
        """A cached coercion with a different canonical name updates the YAML winner field."""
        raw_name = "Jane Doe ("
        yaml_with_bracket = VALID_YAML.replace(
            "winner: Jane Doe", f"winner: {raw_name}"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(yaml_with_bracket, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            coercions = {raw_name: {"winner": "Jane Doe", "vekn_number": 3940009}}
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            mock_fp.assert_not_called()
            assert found is True
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["winner"] == "Jane Doe"
            assert updated["vekn_number"] == 3940009

    def test_check_player_coercions_hit_at_bracket_strip_step_skips_http(self):
        """Cache hit on the bracket-stripped variant skips the bracket-step HTTP call.

        Step 1 (exact match) still makes one HTTP call because the raw name is not
        in the cache.  Only the bracket-stripped fallback is short-circuited.
        """
        raw_name = "Jane Doe ("
        yaml_with_bracket = VALID_YAML.replace(
            "winner: Jane Doe", f"winner: '{raw_name}'"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(yaml_with_bracket, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            # "Jane Doe" (bracket-stripped form) is already in the cache.
            coercions = {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
            with patch(
                "vtes_scraper.scraper.fetch_player", return_value=None
            ) as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            # Only the step-1 exact-match call is made; bracket-strip step hits cache.
            mock_fp.assert_called_once()
            assert found is True
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["winner"] == "Jane Doe"
            assert updated["vekn_number"] == 3940009
            # Both the raw name and the canonical name are stored.
            assert raw_name in coercions
            assert "Jane Doe" in coercions

    def test_check_player_coercions_hit_at_digit_strip_step_skips_http(self):
        """Cache hit on the digit-stripped variant avoids the HTTP call."""
        raw_name = "Jane Doe 1234"
        yaml_with_digits = VALID_YAML.replace(
            "winner: Jane Doe", f"winner: '{raw_name}'"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(yaml_with_digits, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            # Step 1 (exact match) returns None; "Jane Doe" (digit-stripped) is in cache.
            coercions = {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
            with patch(
                "vtes_scraper.scraper.fetch_player", return_value=None
            ) as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            # Only step 1 (exact) makes an HTTP call; digit-stripped step hits cache.
            mock_fp.assert_called_once()
            assert found is True
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert raw_name in coercions
            assert "Jane Doe" in coercions

    def test_check_player_coercions_hit_at_accent_strip_step_skips_http(self):
        """Cache hit on the accent-stripped variant skips the accent-step HTTP call.

        For "Jàne Döe" the digit-strip step produces the same string (no digits),
        so only one HTTP call is made for step 1 (exact match) before the
        accent-stripped form "Jane Doe" is found in the cache.
        """
        raw_name = "Jàne Döe"
        yaml_accented = VALID_YAML.replace("winner: Jane Doe", f"winner: '{raw_name}'")
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(yaml_accented, encoding="utf-8")
            data = validate_cmd._load_yaml(yaml_file)
            mock_client = MagicMock()
            # "Jane Doe" (accent-stripped form) is already in the cache.
            coercions = {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
            with patch(
                "vtes_scraper.scraper.fetch_player", return_value=None
            ) as mock_fp:
                found, moved = validate_cmd._check_player(
                    mock_client,
                    yaml_file,
                    data,
                    Path(tmpdir),
                    0,
                    logging.getLogger(),
                    coercions=coercions,
                )
            # Only step 1 (exact match) makes an HTTP call; accent-strip step hits cache.
            mock_fp.assert_called_once()
            assert found is True
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009
            assert raw_name in coercions
            assert "Jane Doe" in coercions

    def test_run_creates_coercions_file(self):
        """run() with --check-players creates coercions.json when a lookup succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch(
                "vtes_scraper.scraper.fetch_player",
                return_value=("Jane Doe", 3940009),
            ):
                validate_cmd.run(args)
            coercions_path = Path(tmpdir) / "coercions.json"
            assert coercions_path.exists()
            import json

            data = json.loads(coercions_path.read_text())
            assert "Jane Doe" in data
            assert data["Jane Doe"]["vekn_number"] == 3940009

    def test_run_reuses_coercions_file_skips_http(self):
        """run() loads an existing coercions.json and skips HTTP for known winners."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-populate the coercions cache.
            coercions_path = Path(tmpdir) / "coercions.json"
            coercions_path.write_text(
                json.dumps(
                    {"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}
                ),
                encoding="utf-8",
            )
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(VALID_YAML, encoding="utf-8")
            args = argparse.Namespace(
                output_dir=Path(tmpdir),
                check_dates=False,
                check_players=True,
                delay=0,
                verbose=False,
            )
            with patch("vtes_scraper.scraper.fetch_player") as mock_fp:
                ret = validate_cmd.run(args)
            mock_fp.assert_not_called()
            assert ret == 0
            updated = validate_cmd._load_yaml(yaml_file)
            assert updated["vekn_number"] == 3940009


# ---------------------------------------------------------------------------
# fix_dates command
# ---------------------------------------------------------------------------


class TestFixDatesCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        fix_dates_cmd.register(sub)
        args = parser.parse_args(["fix-date", "file.yaml"])
        assert args.command == "fix-date"

    def test_run_file_not_found(self):
        args = argparse.Namespace(
            files=[Path("/nonexistent/file.yaml")],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        with patch(
            "vtes_scraper.cli.fix_dates.fetch_event_date", return_value=date(2023, 1, 1)
        ):
            ret = fix_dates_cmd.run(args)
        assert ret == 1

    def test_run_no_event_url(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: Test\n")
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        ret = fix_dates_cmd.run(args)
        assert ret == 0
        tmpfile.unlink()

    def test_run_date_already_correct(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "date_start: 2023-03-25\nevent_url: https://www.vekn.net/event-calendar/event/1\n"
            )
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        with patch(
            "vtes_scraper.cli.fix_dates.fetch_event_date",
            return_value=date(2023, 3, 25),
        ):
            ret = fix_dates_cmd.run(args)
        assert ret == 0
        tmpfile.unlink()

    def test_run_updates_date(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "date_start: 2023-01-01\nevent_url: https://www.vekn.net/event-calendar/event/1\n"
            )
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        with patch(
            "vtes_scraper.cli.fix_dates.fetch_event_date",
            return_value=date(2023, 3, 25),
        ):
            ret = fix_dates_cmd.run(args)
        assert ret == 0
        content = tmpfile.read_text()
        assert "2023-03-25" in content
        tmpfile.unlink()

    def test_run_dry_run_does_not_write(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "date_start: 2023-01-01\nevent_url: https://www.vekn.net/event-calendar/event/1\n"
            )
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=True,
            verbose=False,
        )
        with patch(
            "vtes_scraper.cli.fix_dates.fetch_event_date",
            return_value=date(2023, 3, 25),
        ):
            ret = fix_dates_cmd.run(args)
        assert ret == 0
        content = tmpfile.read_text()
        assert "2023-01-01" in content  # unchanged
        tmpfile.unlink()

    def test_run_fetch_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "date_start: 2023-01-01\nevent_url: https://www.vekn.net/event-calendar/event/1\n"
            )
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        with patch(
            "vtes_scraper.cli.fix_dates.fetch_event_date",
            side_effect=Exception("network error"),
        ):
            ret = fix_dates_cmd.run(args)
        assert ret == 1
        tmpfile.unlink()

    def test_run_calendar_date_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "date_start: 2023-01-01\nevent_url: https://www.vekn.net/event-calendar/event/1\n"
            )
            tmpfile = Path(f.name)

        args = argparse.Namespace(
            files=[tmpfile],
            delay=0,
            dry_run=False,
            verbose=False,
        )
        with patch("vtes_scraper.cli.fix_dates.fetch_event_date", return_value=None):
            ret = fix_dates_cmd.run(args)
        assert ret == 0
        tmpfile.unlink()

    def test_current_date_start_none(self):
        result = fix_dates_cmd._current_date_start({})
        assert result is None

    def test_current_date_start_date_obj(self):
        d = date(2023, 1, 1)
        result = fix_dates_cmd._current_date_start({"date_start": d})
        assert result == d

    def test_current_date_start_string(self):
        result = fix_dates_cmd._current_date_start({"date_start": "2023-01-01"})
        assert result == date(2023, 1, 1)


# ---------------------------------------------------------------------------
# rescrape command
# ---------------------------------------------------------------------------


class TestRescrapeCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        rescrape_cmd.register(sub)
        args = parser.parse_args(["rescrape"])
        assert args.command == "rescrape"

    def test_run_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            ret = rescrape_cmd.run(args)
            assert ret == 0

    def test_run_file_with_no_forum_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text("name: test\n", encoding="utf-8")
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            ret = rescrape_cmd.run(args)
            assert ret == 0

    def test_run_file_with_forum_url_parse_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(
                "forum_post_url: https://www.vekn.net/forum/twd/123\n", encoding="utf-8"
            )
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.rescrape.extract_twd_from_thread", return_value=None
            ):
                ret = rescrape_cmd.run(args)
            assert ret == 1

    def test_run_file_with_forum_url_success(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(
                "forum_post_url: https://www.vekn.net/forum/twd/123\n", encoding="utf-8"
            )
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            with (
                patch(
                    "vtes_scraper.cli.rescrape.extract_twd_from_thread", return_value=t
                ),
                patch(
                    "vtes_scraper.cli.rescrape.write_tournament_yaml",
                    return_value=Path(tmpdir) / "9999.yaml",
                ),
            ):
                ret = rescrape_cmd.run(args)
            assert ret == 0

    def test_run_file_with_forum_url_write_error(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(
                "forum_post_url: https://www.vekn.net/forum/twd/123\n", encoding="utf-8"
            )
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            with (
                patch(
                    "vtes_scraper.cli.rescrape.extract_twd_from_thread", return_value=t
                ),
                patch(
                    "vtes_scraper.cli.rescrape.write_tournament_yaml",
                    side_effect=Exception("write failed"),
                ),
            ):
                ret = rescrape_cmd.run(args)
            assert ret == 1

    def test_run_forum_url_on_next_line(self):
        """Test parsing multi-line YAML with URL on next line after key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "test.yaml"
            yaml_file.write_text(
                "forum_post_url:\n  https://www.vekn.net/forum/twd/456\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                errors_dir=Path(tmpdir),
                output_dir=Path(tmpdir),
                delay=0,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.rescrape.extract_twd_from_thread", return_value=None
            ):
                ret = rescrape_cmd.run(args)
            assert ret == 1  # parse failed


# ---------------------------------------------------------------------------
# publish command
# ---------------------------------------------------------------------------


class TestPublishCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        publish_cmd.register(sub)
        args = parser.parse_args(["publish"])
        assert args.command == "publish"

    def test_run_no_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=1.0,
                github_token=None,
                publish_dir=Path(tmpdir) / "publish",
                verbose=False,
            )
            with patch.dict("os.environ", {}, clear=True):
                with patch("vtes_scraper.cli.publish.os.environ.get", return_value=""):
                    ret = publish_cmd.run(args)
            assert ret == 1

    def test_run_no_yaml_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=1.0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                verbose=False,
            )
            ret = publish_cmd.run(args)
            assert ret == 0

    def test_run_with_yaml_files(self):
        t = _make_tournament()
        result = BatchPRResult(pr_url="https://github.com/pr/1", published=["9999"])

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a valid YAML file
            from vtes_scraper.output.yaml import write_tournament_yaml

            write_tournament_yaml(t, Path(tmpdir), overwrite=True)

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                include_pre_2020=False,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.publish.publish_all_as_single_pr", return_value=result
            ):
                ret = publish_cmd.run(args)
            assert ret == 0

    def test_run_skipped_all(self):
        t = _make_tournament()
        result = BatchPRResult(skipped_all=True, skipped=["9999"])

        with tempfile.TemporaryDirectory() as tmpdir:
            from vtes_scraper.output.yaml import write_tournament_yaml

            write_tournament_yaml(t, Path(tmpdir), overwrite=True)

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                include_pre_2020=False,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.publish.publish_all_as_single_pr", return_value=result
            ):
                ret = publish_cmd.run(args)
            assert ret == 0

    def test_run_with_errors(self):
        t = _make_tournament()
        result = BatchPRResult(
            pr_url="https://github.com/pr/2",
            published=["9999"],
            errors=[("bad_id", "some error")],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            from vtes_scraper.output.yaml import write_tournament_yaml

            write_tournament_yaml(t, Path(tmpdir), overwrite=True)

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                include_pre_2020=False,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.publish.publish_all_as_single_pr", return_value=result
            ):
                ret = publish_cmd.run(args)
            assert ret == 1

    def test_run_no_pr_url(self):
        t = _make_tournament()
        result = BatchPRResult(published=["9999"])  # no pr_url

        with tempfile.TemporaryDirectory() as tmpdir:
            from vtes_scraper.output.yaml import write_tournament_yaml

            write_tournament_yaml(t, Path(tmpdir), overwrite=True)

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                include_pre_2020=False,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.publish.publish_all_as_single_pr", return_value=result
            ):
                ret = publish_cmd.run(args)
            assert ret == 0

    def test_run_nothing_to_publish_after_load(self):
        """Test when all YAML files fail to load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_yaml = Path(tmpdir) / "bad.yaml"
            bad_yaml.write_text(": : : invalid yaml {{{{", encoding="utf-8")

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                verbose=False,
            )
            ret = publish_cmd.run(args)
            # No valid tournaments loaded
            assert ret == 0

    def test_write_publish_report_with_pr_url(self):
        t = _make_tournament()
        result = BatchPRResult(pr_url="https://github.com/pr/1", published=["9999"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(
                result, Path(tmpdir), "2023-03-25", [t]
            )
            assert path.exists()
            content = path.read_text()
            assert "https://github.com/pr/1" in content

    def test_write_publish_report_skipped_all(self):
        result = BatchPRResult(skipped_all=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(
                result, Path(tmpdir), "2023-03-25", []
            )
            content = path.read_text()
            assert "already present on master" in content

    def test_write_publish_report_no_pr(self):
        result = BatchPRResult()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(
                result, Path(tmpdir), "2023-03-25", []
            )
            content = path.read_text()
            assert "No PR opened" in content

    def test_write_publish_report_with_errors(self):
        result = BatchPRResult(
            published=["9999"],
            errors=[("bad_id", "Failed to commit")],
        )
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(
                result, Path(tmpdir), "2023-03-25", [t]
            )
            content = path.read_text()
            assert "bad_id" in content

    def test_write_publish_report_with_skipped(self):
        result = BatchPRResult(skipped=["8888"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(
                result, Path(tmpdir), "2023-03-25", []
            )
            content = path.read_text()
            assert "8888" in content
