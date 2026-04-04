"""Tests for the ``scrape`` CLI subcommand."""

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vtes_scraper.cli import scrape as scrape_cmd
from vtes_scraper.models import (
    Crypt_Card_Dict,
    Deck_Dict,
    Library_Card_Dict,
    Library_Section_Dict,
    Tournament,
    Tournament_Dict,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_tournament(**overrides) -> Tournament:
    defaults = Tournament_Dict(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=Deck_Dict(
            crypt=[
                Crypt_Card_Dict(
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
                Library_Section_Dict(
                    name="Master",
                    count=1,
                    cards=[Library_Card_Dict(count=1, name="Blood Doll")],
                )
            ],
            library_count=1,
        ),
    )
    for k, v in overrides.items():
        if k in defaults:
            defaults[k] = v
    return Tournament.model_validate(defaults)


def _scrape_namespace(**kwargs) -> argparse.Namespace:
    """Build a scrape Namespace with sensible defaults for tests."""
    defaults = dict(
        output_dir=Path("twds"),
        start_page=0,
        last_page=None,
        delay=0,
        overwrite=False,
        verbose=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _patch_pipeline(**overrides):
    """Return a context manager that patches all pipeline externals.

    By default every step is a no-op:
      - scrape_forum yields nothing
      - fetch_event_winner returns None
      - fetch_player returns None
      - enrich_crypt_cards / fix_card_sections return []
    """
    import contextlib

    patches = {
        "scrape_forum": iter([]),
        "fetch_event_winner": None,
        "fetch_event_date": None,
        "fetch_player": None,
        "enrich_crypt_cards": [],
        "fix_card_sections": [],
        "error_types": [],
    }
    patches.update(overrides)

    mgrs = []
    for name, rv in patches.items():
        p = patch(f"vtes_scraper.cli.scrape.{name}", return_value=rv)
        mgrs.append(p)

    @contextlib.contextmanager
    def combined():
        started = []
        try:
            for m in mgrs:
                started.append(m.start())
            names = list(patches.keys())
            result = {n: s for n, s in zip(names, started)}
            yield result
        finally:
            for m in mgrs:
                m.stop()

    return combined()


# ---------------------------------------------------------------------------
# Argument parsing tests
# ---------------------------------------------------------------------------


class TestScrapeCommand:
    def test_register(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape"])
        assert args.command == "scrape"

    def test_register_last_page_default(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape"])
        assert args.last_page is None

    def test_register_last_page_set(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--last-page", "5"])
        assert args.last_page == 5

    def test_register_start_and_last_page(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        scrape_cmd.register(sub)
        args = parser.parse_args(["scrape", "--start-page", "2", "--last-page", "7"])
        assert args.start_page == 2
        assert args.last_page == 7


# ---------------------------------------------------------------------------
# Pipeline run tests
# ---------------------------------------------------------------------------


class TestScrapeRun:
    def test_run_no_tournaments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline():
                ret = scrape_cmd.run(args)
            assert ret == 0

    def test_run_with_tournament_written(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)])):
                ret = scrape_cmd.run(args)
            assert ret == 0
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1

    def test_run_with_file_exists_skipped(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)])):
                with patch(
                    "vtes_scraper.cli.scrape.write_tournament_yaml",
                    side_effect=FileExistsError("exists"),
                ):
                    ret = scrape_cmd.run(args)
            assert ret == 0

    def test_run_with_general_error(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner="Jane Doe",
            ):
                with patch(
                    "vtes_scraper.cli.scrape.write_tournament_yaml",
                    side_effect=Exception("error"),
                ):
                    ret = scrape_cmd.run(args)
            assert ret == 1

    def test_run_last_page_computes_max_pages(self):
        """last_page=4, start_page=2 → max_pages=3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir), start_page=2, last_page=4)
            with _patch_pipeline() as mocks:
                scrape_cmd.run(args)
            _, kwargs = mocks["scrape_forum"].call_args
            assert kwargs["max_pages"] == 3

    def test_run_no_last_page_passes_none_max_pages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir), last_page=None)
            with _patch_pipeline() as mocks:
                scrape_cmd.run(args)
            _, kwargs = mocks["scrape_forum"].call_args
            assert kwargs["max_pages"] is None

    def test_run_enriches_winner_with_vekn_number(self):
        """Player lookup resolves; vekn_number ends up in the written file."""
        t = _make_tournament()
        assert t.vekn_number is None

        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_player=("Jane Doe", 3940009),
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
            with _patch_pipeline(scrape_forum=iter([(t, None)])):
                ret = scrape_cmd.run(args)
            assert ret == 0
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1

    def test_run_no_calendar_results_routes_to_unknown_winner(self):
        """When the event page has no results, the file is routed to errors/unknown_winner/."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner=None,
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            error_file = Path(tmpdir) / "errors" / "unknown_winner" / "9999.yaml"
            assert error_file.exists()

    def test_run_coercions_saved_on_new_resolution(self):
        """coercions.json is created when a new player name is resolved."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_player=("Jane Doe", 3940009),
            ):
                scrape_cmd.run(args)
            coercions_path = Path(tmpdir) / "coercions.json"
            assert coercions_path.exists()
            data = json.loads(coercions_path.read_text())
            assert "Jane Doe" in data

    def test_run_skips_lookup_when_vekn_number_present(self):
        """Tournaments with a vekn_number are not re-looked-up."""
        t = _make_tournament().model_copy(update={"vekn_number": 3940009})
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)])) as mocks:
                scrape_cmd.run(args)
            mocks["fetch_player"].assert_not_called()

    def test_run_uses_coercions_cache(self):
        """Pre-populated coercions.json is used without an HTTP request."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            coercions_path = Path(tmpdir) / "coercions.json"
            coercions_path.write_text(
                json.dumps({"Jane Doe": {"winner": "Jane Doe", "vekn_number": 3940009}}),
                encoding="utf-8",
            )
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)])) as mocks:
                scrape_cmd.run(args)
            mocks["fetch_player"].assert_not_called()
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1
            content = written[0].read_text(encoding="utf-8")
            assert "vekn_number: 3940009" in content

    def test_calendar_winner_override(self):
        """Step 3: calendar winner overrides the forum winner."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner="Calendar Winner",
            ):
                scrape_cmd.run(args)
            written = list(Path(tmpdir).rglob("*.yaml"))
            content = written[0].read_text(encoding="utf-8")
            assert "Calendar Winner" in content

    def test_validation_errors_route_to_errors_dir(self):
        """Step 6: tournaments with validation errors are saved under errors/<type>/."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                error_types=["too_few_players"],
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            error_file = Path(tmpdir) / "errors" / "too_few_players" / "9999.yaml"
            assert error_file.exists()
            # Should NOT be written to normal output dir
            normal = list((Path(tmpdir)).glob("202*/**/*.yaml"))
            assert len(normal) == 0

    def test_validation_errors_use_first_error_for_dir(self):
        """When multiple errors exist, the first one determines the subdirectory."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                error_types=["missing_name", "empty_crypt"],
            ):
                scrape_cmd.run(args)
            error_file = Path(tmpdir) / "errors" / "missing_name" / "9999.yaml"
            assert error_file.exists()

    def test_no_validation_errors_writes_normally(self):
        """Step 6: no errors means the file is written to the normal directory."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner="Jane Doe",
                error_types=[],
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            written = list(Path(tmpdir).rglob("*.yaml"))
            assert len(written) == 1
            # Should not be under errors/
            assert "errors" not in str(written[0])

    def test_validation_date_coherence_with_calendar_date(self):
        """Step 6: fetch_event_date is called and passed to error_types."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_date=date(2023, 3, 25),
            ) as mocks:
                scrape_cmd.run(args)
            _, kwargs = mocks["error_types"].call_args
            assert kwargs["calendar_date"] == date(2023, 3, 25)
