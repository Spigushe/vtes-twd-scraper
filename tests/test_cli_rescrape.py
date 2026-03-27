"""Tests for the ``rescrape`` CLI subcommand."""

import argparse
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vtes_scraper.cli import rescrape as rescrape_cmd
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
