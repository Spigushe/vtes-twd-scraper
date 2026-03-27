"""Tests for the ``scrape`` CLI subcommand."""

import argparse
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import vtes_scraper.scraper as scraper_mod
from vtes_scraper.cli import scrape as scrape_cmd
from vtes_scraper.models import CryptCard, Deck, LibraryCard, LibrarySection, Tournament

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# scrape command
# ---------------------------------------------------------------------------


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
