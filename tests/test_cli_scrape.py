"""Tests for the ``scrape`` CLI subcommand."""

import argparse
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
        "fetch_event_name": None,
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

    def test_run_no_calendar_results_routes_to_unconfirmed_winner(self):
        """When the event page has no results, the file is routed to errors/unconfirmed_winner/."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner=None,
            ):
                ret = scrape_cmd.run(args)
            assert ret == 0
            error_file = Path(tmpdir) / "errors" / "unconfirmed_winner" / "9999.yaml"
            assert error_file.exists()

    def test_run_skips_lookup_when_vekn_number_present(self):
        """Tournaments with a vekn_number are not re-looked-up."""
        t = _make_tournament().model_copy(update={"vekn_number": 3940009})
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)])) as mocks:
                scrape_cmd.run(args)
            mocks["fetch_player"].assert_not_called()

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
                error_types=["missing_name", "illegal_crypt"],
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


# ---------------------------------------------------------------------------
# Additional coverage for internal helpers and run() routing branches
# ---------------------------------------------------------------------------


class TestScrapeInternalPaths:
    # ── _check_calendar_winner ───────────────────────────────────────────────

    def test_check_calendar_winner_exception_returns_original(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_winner",
            side_effect=Exception("network error"),
        ):
            result, missing = scrape_cmd._check_calendar_winner(client, t, delay=0)
        assert result is t
        assert missing is False

    def test_check_calendar_winner_overrides_winner(self):
        from unittest.mock import MagicMock

        t = _make_tournament()  # winner="Jane Doe"
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_winner",
            return_value="New Winner",
        ):
            result, missing = scrape_cmd._check_calendar_winner(client, t, delay=0)
        assert result.winner == "New Winner"
        assert missing is False

    def test_check_calendar_winner_none_sets_missing(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch("vtes_scraper.cli.scrape.fetch_event_winner", return_value=None):
            result, missing = scrape_cmd._check_calendar_winner(client, t, delay=0)
        assert missing is True

    def test_check_calendar_winner_no_event_url(self):
        from unittest.mock import MagicMock

        t = _make_tournament().model_copy(update={"event_url": None})
        client = MagicMock()
        result, missing = scrape_cmd._check_calendar_winner(client, t, delay=0)
        assert result is t
        assert missing is False

    # ── _lookup_player ───────────────────────────────────────────────────────

    def test_lookup_player_exception_returns_original(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_player",
            side_effect=Exception("timeout"),
        ):
            result = scrape_cmd._lookup_player(client, t, delay=0)
        assert result is t

    def test_lookup_player_not_found_prints_message(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch("vtes_scraper.cli.scrape.fetch_player", return_value=None):
            result = scrape_cmd._lookup_player(client, t, delay=0)
        assert result is t

    # ── _enrich_with_krcg ────────────────────────────────────────────────────

    def test_enrich_with_krcg_prints_crypt_fixes(self):
        t = _make_tournament()
        with patch(
            "vtes_scraper.cli.scrape.enrich_crypt_cards",
            return_value=["capacity: 0 → 4"],
        ):
            with patch("vtes_scraper.cli.scrape.fix_card_sections", return_value=[]):
                result = scrape_cmd._enrich_with_krcg(t)
        assert result is not t  # model was rebuilt

    def test_enrich_with_krcg_prints_section_fixes(self):
        t = _make_tournament()
        with patch("vtes_scraper.cli.scrape.enrich_crypt_cards", return_value=[]):
            with patch(
                "vtes_scraper.cli.scrape.fix_card_sections",
                return_value=["Blood Doll → Master"],
            ):
                result = scrape_cmd._enrich_with_krcg(t)
        assert result is not t

    def test_lookup_player_coerces_winner_name(self):
        """When fetch_player returns a different canonical name, it is printed and stored."""
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_player",
            return_value=("Jane Doe-Smith", 12345),
        ):
            result = scrape_cmd._lookup_player(client, t, delay=0)
        assert result.winner == "Jane Doe-Smith"
        assert result.vekn_number == 12345

    def test_enrich_with_krcg_no_deck(self):
        """Tournament with no deck data is returned unchanged (line 138)."""
        from unittest.mock import MagicMock

        t = MagicMock()
        t.model_dump.return_value = {}  # _to_serializable returns no deck key
        result = scrape_cmd._enrich_with_krcg(t)
        assert result is t

    # ── _validate_content ────────────────────────────────────────────────────

    def test_validate_content_fetch_date_exception(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_date",
            side_effect=Exception("timeout"),
        ):
            with patch("vtes_scraper.cli.scrape.error_types", return_value=[]):
                errors = scrape_cmd._validate_content(client, t, delay=0)
        assert errors == []

    def test_validate_content_no_event_url(self):
        """Tournament with no event_url skips the date fetch (branch 169->179)."""
        from unittest.mock import MagicMock

        t = _make_tournament().model_copy(update={"event_url": None})
        client = MagicMock()
        with patch("vtes_scraper.cli.scrape.error_types", return_value=[]) as mock_et:
            errors = scrape_cmd._validate_content(client, t, delay=0)
        assert errors == []
        # calendar_date should be None since there was no event_url
        _, kwargs = mock_et.call_args
        assert kwargs.get("calendar_date") is None

    # ── run() routing paths ───────────────────────────────────────────────────

    def test_run_icon_merged_no_errors_writes_to_changes_required(self):
        from vtes_scraper.scraper import ICON_MERGED

        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, ICON_MERGED)]),
                fetch_event_winner=t.winner,  # avoids calendar_winner_missing=True
                error_types=[],
            ):
                with patch("vtes_scraper.cli.scrape.console"):
                    ret = scrape_cmd.run(args)
            changes_dir = Path(tmpdir) / "changes_required"
            assert ret == 0
            assert changes_dir.exists()
            assert len(list(changes_dir.glob("*.yaml"))) == 1

    def test_run_icon_merged_write_exception_counts_as_failure(self):
        from vtes_scraper.scraper import ICON_MERGED

        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, ICON_MERGED)]),
                fetch_event_winner=t.winner,
                error_types=[],
            ):
                with patch("vtes_scraper.cli.scrape.console"):
                    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                        ret = scrape_cmd.run(args)
        assert ret == 1

    def test_run_errors_write_exception_counts_as_failure(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                error_types=["too_few_players"],
            ):
                with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                    ret = scrape_cmd.run(args)
        assert ret == 1

    def test_run_stale_changes_required_file_removed(self):
        """After a successful normal write, any stale changes_required copy is deleted."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            changes_dir = Path(tmpdir) / "changes_required"
            changes_dir.mkdir(parents=True)
            stale = changes_dir / t.yaml_filename
            stale.write_text("stale content", encoding="utf-8")

            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner=t.winner,
                error_types=[],
            ):
                ret = scrape_cmd.run(args)
        assert ret == 0
        assert not stale.exists()

    def test_run_overwrite_skipped_message_printed(self):
        """Running twice without --overwrite increments overwrite_skipped counter."""
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner=t.winner,
                error_types=[],
            ):
                scrape_cmd.run(args)
            with _patch_pipeline(
                scrape_forum=iter([(t, None)]),
                fetch_event_winner=t.winner,
                error_types=[],
            ):
                ret = scrape_cmd.run(args)
        assert ret == 0

    def test_run_no_event_id_increments_skipped(self):
        """Tournaments without an event_id are skipped immediately."""
        t = _make_tournament().model_copy(update={"event_id": None})
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _scrape_namespace(output_dir=Path(tmpdir))
            with _patch_pipeline(scrape_forum=iter([(t, None)]), error_types=[]):
                ret = scrape_cmd.run(args)
        assert ret == 0
        assert list(Path(tmpdir).rglob("*.yaml")) == []


# ---------------------------------------------------------------------------
# _check_calendar_name tests
# ---------------------------------------------------------------------------


class TestCheckCalendarName:
    def test_overrides_name_when_calendar_differs(self):
        from unittest.mock import MagicMock

        t = _make_tournament()  # name="Test Event"
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_name",
            return_value="Authoritative Event Name",
        ):
            result = scrape_cmd._check_calendar_name(client, t, delay=0)
        assert result.name == "Authoritative Event Name"
        assert result is not t

    def test_keeps_forum_name_when_calendar_returns_none(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch("vtes_scraper.cli.scrape.fetch_event_name", return_value=None):
            result = scrape_cmd._check_calendar_name(client, t, delay=0)
        assert result is t
        assert result.name == "Test Event"

    def test_keeps_forum_name_when_names_match(self):
        from unittest.mock import MagicMock

        t = _make_tournament()  # name="Test Event"
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_name",
            return_value="Test Event",
        ):
            result = scrape_cmd._check_calendar_name(client, t, delay=0)
        assert result is t

    def test_exception_returns_original_tournament(self):
        from unittest.mock import MagicMock

        t = _make_tournament()
        client = MagicMock()
        with patch(
            "vtes_scraper.cli.scrape.fetch_event_name",
            side_effect=Exception("network error"),
        ):
            result = scrape_cmd._check_calendar_name(client, t, delay=0)
        assert result is t

    def test_no_event_url_returns_original_tournament(self):
        from unittest.mock import MagicMock

        t = _make_tournament().model_copy(update={"event_url": None})
        client = MagicMock()
        result = scrape_cmd._check_calendar_name(client, t, delay=0)
        assert result is t
