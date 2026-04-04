"""Tests for the ``validate`` CLI subcommand.

Two groups of concerns:
  - Scraper interaction: forum rescrape, calendar winner lookup, date fetch.
  - Validator interaction: error_types routing, file moves, in-place updates.
"""

import argparse
import contextlib
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml import YAML

import vtes_scraper.cli.validate as validate_mod
from vtes_scraper.cli.validate import _check_and_update_winner, _iter_published_yaml
from vtes_scraper.models import (
    Crypt_Card_Dict,
    Deck_Dict,
    Library_Card_Dict,
    Library_Section_Dict,
    Tournament,
    Tournament_Dict,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_yaml = YAML()


def _make_tournament(**overrides) -> Tournament:
    defaults = Tournament_Dict(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        vekn_number=3940009,
        event_url="https://www.vekn.net/event-calendar/event/9999",
        forum_post_url="https://www.vekn.net/forum/event-reports-and-twd/99999-test-event",
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


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def _tournament_dict(**overrides) -> Tournament_Dict:
    base = Tournament_Dict(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        vekn_number=3940009,
        event_url="https://www.vekn.net/event-calendar/event/9999",
        event_id=9999,
        forum_post_url="https://www.vekn.net/forum/event-reports-and-twd/99999-test-event",
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
        if k in Tournament_Dict.__annotations__:
            base[k] = v
    return base


def _validate_namespace(
    twds_dir: Path,
    dry_run: bool = False,
    full_validation: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        twds_dir=twds_dir,
        dry_run=dry_run,
        full_validation=full_validation,
        verbose=False,
    )


@contextlib.contextmanager
def _patch_validate(**overrides):
    """Patch all external calls in validate.run() to no-ops by default."""
    defaults = {
        "extract_twd_from_thread": None,
        "fetch_event_winner": None,
        "fetch_player": None,
        "fetch_event_date": None,
        "enrich_crypt_cards": [],
        "fix_card_sections": [],
        "error_types": [],
    }
    defaults.update(overrides)

    patches = [patch(f"vtes_scraper.cli.validate.{k}", return_value=v) for k, v in defaults.items()]
    mocks = {}
    try:
        for k, p in zip(defaults.keys(), patches):
            mocks[k] = p.start()
        yield mocks
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# _iter_published_yaml
# ---------------------------------------------------------------------------


class TestIterPublishedYaml:
    @pytest.fixture
    def full_validation(self):
        return True

    def test_yields_normal_files(self, tmp_path, full_validation):
        f = tmp_path / "2023" / "03" / "9999.yaml"
        _write_yaml(f, {})
        result = list(_iter_published_yaml(tmp_path, full_validation))
        assert f in result

    def test_skips_changes_required(self, tmp_path, full_validation):
        f = tmp_path / "changes_required" / "9999.yaml"
        _write_yaml(f, {})
        result = list(_iter_published_yaml(tmp_path, full_validation))
        assert f not in result

    def test_includes_errors_subdir(self, tmp_path, full_validation):
        f = tmp_path / "errors" / "unconfirmed_winner" / "9999.yaml"
        _write_yaml(f, {})
        result = list(_iter_published_yaml(tmp_path, full_validation))
        assert f in result

    def test_yields_multiple_years(self, tmp_path, full_validation):
        f1 = tmp_path / "2022" / "01" / "1111.yaml"
        f2 = tmp_path / "2023" / "03" / "2222.yaml"
        _write_yaml(f1, {})
        _write_yaml(f2, {})
        result = list(_iter_published_yaml(tmp_path, full_validation))
        assert f1 in result
        assert f2 in result

    def test_empty_dir_yields_nothing(self, tmp_path, full_validation):
        assert list(_iter_published_yaml(tmp_path, full_validation)) == []


# ---------------------------------------------------------------------------
# _check_and_update_winner  (scraper interaction)
# ---------------------------------------------------------------------------


class TestCheckAndUpdateWinner:
    def _client(self):
        return MagicMock()

    def test_updates_winner_from_calendar(self):
        data = _tournament_dict(winner="Old Name")
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="Calendar Name"),
            patch.object(validate_mod, "fetch_player", return_value=("Calendar Name", 1234567)),
        ):
            dirty = _check_and_update_winner(client, data, "https://example.com/event/1")
        assert dirty is True
        assert "winner" in data and data["winner"] == "Calendar Name"
        assert "vekn_number" in data and data["vekn_number"] == 1234567

    def test_updates_vekn_number_from_player_registry(self):
        data = _tournament_dict(winner="Jane Doe", vekn_number=None)
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="Jane Doe"),
            patch.object(validate_mod, "fetch_player", return_value=("Jane Doe", 3940009)),
        ):
            dirty = _check_and_update_winner(client, data, "https://example.com/event/1")
        assert dirty is True
        assert "vekn_number" in data and data["vekn_number"] == 3940009

    def test_canonicalises_winner_name_via_player_registry(self):
        """Player registry may return a differently cased/accented canonical name."""
        data = _tournament_dict(winner="jane doe", vekn_number=None)
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="jane doe"),
            patch.object(validate_mod, "fetch_player", return_value=("Jane Doe", 3940009)),
        ):
            _check_and_update_winner(client, data, "https://example.com/event/1")
        assert "winner" in data and data["winner"] == "Jane Doe"

    def test_no_change_when_already_correct(self):
        data = _tournament_dict(winner="Jane Doe", vekn_number=3940009)
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="Jane Doe"),
            patch.object(validate_mod, "fetch_player", return_value=("Jane Doe", 3940009)),
        ):
            dirty = _check_and_update_winner(client, data, "https://example.com/event/1")
        assert dirty is False

    def test_no_change_when_calendar_winner_missing(self):
        data = _tournament_dict(winner="Jane Doe", vekn_number=3940009)
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value=None),
            patch.object(validate_mod, "fetch_player", return_value=("Jane Doe", 3940009)),
        ):
            dirty = _check_and_update_winner(client, data, "https://example.com/event/1")
        assert dirty is False

    def test_no_change_when_player_not_found(self):
        data = _tournament_dict(winner="Jane Doe", vekn_number=None)
        client = self._client()
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="Jane Doe"),
            patch.object(validate_mod, "fetch_player", return_value=None),
        ):
            dirty = _check_and_update_winner(client, data, "https://example.com/event/1")
        assert dirty is False
        assert data.get("vekn_number") is None

    def test_fetch_player_uses_updated_winner_name(self):
        """fetch_player must be called with the calendar winner, not the stale one."""
        data = _tournament_dict(winner="Old Name")
        client = self._client()
        mock_player = MagicMock(return_value=("Calendar Name", 9999999))
        with (
            patch.object(validate_mod, "fetch_event_winner", return_value="Calendar Name"),
            patch.object(validate_mod, "fetch_player", mock_player),
        ):
            _check_and_update_winner(client, data, "https://example.com/event/1")
        mock_player.assert_called_once()
        assert mock_player.call_args[0][1] == "Calendar Name"


# ---------------------------------------------------------------------------
# validate.run — scraper interaction
# ---------------------------------------------------------------------------


class TestValidateRunScraperInteraction:
    def test_forum_rescrape_called_for_each_file(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        fresh = _make_tournament()
        with _patch_validate(extract_twd_from_thread=fresh) as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["extract_twd_from_thread"].assert_called_once()
        url_arg = mocks["extract_twd_from_thread"].call_args[0][1]
        assert "forum" in url_arg

    def test_forum_rescrape_preserves_vekn_number(self, tmp_path):
        saved = _tournament_dict(vekn_number=3940009)
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", saved)
        # Forum rescrape returns a tournament without vekn_number
        fresh = _make_tournament(vekn_number=None)
        with _patch_validate(extract_twd_from_thread=fresh):
            validate_mod.run(_validate_namespace(tmp_path))
        # Written file must still carry the original vekn_number
        written = tmp_path / "2023" / "03" / "9999.yaml"
        with open(written, encoding="utf-8") as fh:
            on_disk = _yaml.load(fh)
        assert on_disk["vekn_number"] == 3940009

    def test_forum_rescrape_skipped_in_dry_run(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path, dry_run=True))
        mocks["extract_twd_from_thread"].assert_not_called()

    def test_forum_rescrape_error_does_not_abort(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate(extract_twd_from_thread=Exception("boom")):
            with patch.object(
                validate_mod, "extract_twd_from_thread", side_effect=Exception("boom")
            ):
                rc = validate_mod.run(_validate_namespace(tmp_path))
        assert rc == 0

    def test_calendar_winner_check_called_with_event_url(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["fetch_event_winner"].assert_called_once()
        url_arg = mocks["fetch_event_winner"].call_args[0][1]
        assert "9999" in url_arg

    def test_calendar_winner_check_skipped_in_dry_run(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path, dry_run=True))
        mocks["fetch_event_winner"].assert_not_called()

    def test_fetch_player_called_after_calendar_winner(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate(fetch_event_winner="Jane Doe") as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["fetch_player"].assert_called_once()
        assert mocks["fetch_player"].call_args[0][1] == "Jane Doe"

    def test_enrich_crypt_cards_called(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["enrich_crypt_cards"].assert_called_once()

    def test_fix_card_sections_called(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["fix_card_sections"].assert_called_once()

    def test_fetch_event_date_called_with_event_url(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["fetch_event_date"].assert_called_once()
        url_arg = mocks["fetch_event_date"].call_args[0][1]
        assert "9999" in url_arg

    def test_fetch_event_date_skipped_in_dry_run(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path, dry_run=True))
        mocks["fetch_event_date"].assert_not_called()

    def test_calendar_date_passed_to_error_types(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate(fetch_event_date=date(2023, 3, 25)) as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        _, kwargs = mocks["error_types"].call_args
        assert kwargs.get("calendar_date") == date(2023, 3, 25)

    def test_multiple_files_each_scraped_independently(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        _write_yaml(tmp_path / "2023" / "04" / "8888.yaml", _tournament_dict(event_id=8888))
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        assert mocks["extract_twd_from_thread"].call_count == 2
        assert mocks["fetch_event_winner"].call_count == 2


# ---------------------------------------------------------------------------
# validate.run — validator interaction
# ---------------------------------------------------------------------------


class TestValidateRunValidatorInteraction:
    def test_error_types_called_for_each_file(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["error_types"].assert_called_once()

    def test_no_errors_file_updated_in_place_when_dirty(self, tmp_path):
        """A clean file that was modified (e.g. crypt enriched) is written back."""
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        # enrich_crypt_cards returns a non-empty fix list → dirty=True
        with _patch_validate(enrich_crypt_cards=["capacity: 0 → 4"], error_types=[]):
            validate_mod.run(_validate_namespace(tmp_path))
        written = tmp_path / "2023" / "03" / "9999.yaml"
        assert written.exists()

    def test_no_errors_clean_file_not_rewritten(self, tmp_path):
        """A clean, unchanged file is not touched."""
        original = tmp_path / "2023" / "03" / "9999.yaml"
        _write_yaml(original, _tournament_dict())
        mtime_before = original.stat().st_mtime
        with _patch_validate(error_types=[]):
            validate_mod.run(_validate_namespace(tmp_path))
        assert original.stat().st_mtime == mtime_before

    def test_errors_move_file_to_errors_subdir(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate(error_types=["illegal_header"]):
            validate_mod.run(_validate_namespace(tmp_path))
        assert (tmp_path / "errors" / "illegal_header" / "9999.yaml").exists()
        assert not (tmp_path / "2023" / "03" / "9999.yaml").exists()

    def test_first_error_determines_subdir(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate(error_types=["illegal_header", "unconfirmed_winner"]):
            validate_mod.run(_validate_namespace(tmp_path))
        assert (tmp_path / "errors" / "illegal_header" / "9999.yaml").exists()
        assert not (tmp_path / "errors" / "unconfirmed_winner" / "9999.yaml").exists()

    def test_all_error_types_can_route_correctly(self, tmp_path):
        error_types_list = [
            "illegal_header",
            "unconfirmed_winner",
            "limited_format",
            "illegal_crypt",
            "illegal_library",
            "too_few_players",
            "incoherent_date",
        ]
        for i, error in enumerate(error_types_list):
            f = tmp_path / f"202{i}" / "01" / f"{1000 + i}.yaml"
            _write_yaml(f, _tournament_dict(event_id=1000 + i))
            with _patch_validate(error_types=[error]):
                validate_mod.run(_validate_namespace(tmp_path))
            assert (tmp_path / "errors" / error / f"{1000 + i}.yaml").exists()

    def test_dry_run_does_not_move_files(self, tmp_path):
        original = tmp_path / "2023" / "03" / "9999.yaml"
        _write_yaml(original, _tournament_dict())
        with _patch_validate(error_types=["illegal_header"]):
            validate_mod.run(_validate_namespace(tmp_path, dry_run=True))
        assert original.exists()
        assert not (tmp_path / "errors").exists()

    def test_dry_run_does_not_update_files(self, tmp_path):
        original = tmp_path / "2023" / "03" / "9999.yaml"
        _write_yaml(original, _tournament_dict())
        mtime_before = original.stat().st_mtime
        with _patch_validate(enrich_crypt_cards=["capacity: 0 → 4"], error_types=[]):
            validate_mod.run(_validate_namespace(tmp_path, dry_run=True))
        assert original.stat().st_mtime == mtime_before

    def test_changes_required_dir_skipped(self, tmp_path):
        _write_yaml(tmp_path / "changes_required" / "9999.yaml", _tournament_dict())
        with _patch_validate() as mocks:
            validate_mod.run(_validate_namespace(tmp_path))
        mocks["error_types"].assert_not_called()

    def test_errors_dir_files_are_revalidated(self, tmp_path, full_validation=True):
        """Files already in errors/ are processed so they can be recovered."""
        _write_yaml(tmp_path / "errors" / "unconfirmed_winner" / "9999.yaml", _tournament_dict())
        with _patch_validate(error_types=[]) as mocks:
            validate_mod.run(_validate_namespace(tmp_path, full_validation=full_validation))
        mocks["error_types"].assert_called_once()

    def test_recovered_error_file_moved_to_clean_location(self, tmp_path):
        """An errors/ file that now passes validation is written back in place."""
        error_file = tmp_path / "errors" / "unconfirmed_winner" / "9999.yaml"
        _write_yaml(error_file, _tournament_dict())
        with _patch_validate(enrich_crypt_cards=["fix"], error_types=[]):
            validate_mod.run(_validate_namespace(tmp_path))
        # File is updated in place (in errors/), not moved elsewhere
        assert error_file.exists()

    def test_winner_update_written_to_file(self, tmp_path):
        """When the calendar returns a different winner name, it is persisted."""
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict(winner="Old Name"))
        with _patch_validate(
            fetch_event_winner="Calendar Winner",
            fetch_player=("Calendar Winner", 3940009),
            error_types=[],
        ):
            validate_mod.run(_validate_namespace(tmp_path))
        with open(tmp_path / "2023" / "03" / "9999.yaml", encoding="utf-8") as fh:
            on_disk = _yaml.load(fh)
        assert on_disk["winner"] == "Calendar Winner"

    def test_vekn_number_update_written_to_file(self, tmp_path):
        """When vekn_number is resolved from the player registry, it is persisted."""
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict(vekn_number=None))
        with _patch_validate(
            fetch_event_winner="Jane Doe",
            fetch_player=("Jane Doe", 3940009),
            error_types=[],
        ):
            validate_mod.run(_validate_namespace(tmp_path))
        with open(tmp_path / "2023" / "03" / "9999.yaml", encoding="utf-8") as fh:
            on_disk = _yaml.load(fh)
        assert on_disk["vekn_number"] == 3940009

    def test_returns_zero(self, tmp_path):
        _write_yaml(tmp_path / "2023" / "03" / "9999.yaml", _tournament_dict())
        with _patch_validate():
            rc = validate_mod.run(_validate_namespace(tmp_path))
        assert rc == 0

    def test_returns_zero_on_empty_dir(self, tmp_path):
        with _patch_validate():
            rc = validate_mod.run(_validate_namespace(tmp_path))
        assert rc == 0
