"""Tests for the ``validate`` CLI subcommand."""

import argparse
import logging
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import vtes_scraper_v1.scraper as scraper_mod
from vtes_scraper_v1 import validator
from vtes_scraper_v1.cli import validate as validate_cmd

# ---------------------------------------------------------------------------
# Shared fixtures
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


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


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
