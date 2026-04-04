"""Tests for the ``publish`` CLI subcommand."""

import argparse
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vtes_scraper.cli import publish as publish_cmd
from vtes_scraper.models import (
    CryptCard,
    Deck,
    LibraryCard,
    LibrarySection,
    Tournament,
)
from vtes_scraper.publisher import BatchPRResult

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
                "vtes_scraper.cli.publish.publish_all_as_single_pr",
                return_value=result,
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
                "vtes_scraper.cli.publish.publish_all_as_single_pr",
                return_value=result,
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
                "vtes_scraper.cli.publish.publish_all_as_single_pr",
                return_value=result,
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
                "vtes_scraper.cli.publish.publish_all_as_single_pr",
                return_value=result,
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

    def test_run_skips_error_decks(self):
        """Decks inside twds/errors/ must not be submitted to the publisher."""
        t = _make_tournament()
        result = BatchPRResult(pr_url="https://github.com/pr/1", published=["9999"])

        with tempfile.TemporaryDirectory() as tmpdir:
            from vtes_scraper.output.yaml import write_tournament_yaml

            # Place a valid YAML in the errors subdirectory
            errors_dir = Path(tmpdir) / "errors" / "unconfirmed_winner"
            errors_dir.mkdir(parents=True)
            write_tournament_yaml(t, errors_dir, overwrite=True)

            args = argparse.Namespace(
                twds_dir=Path(tmpdir),
                delay=0,
                github_token="mytoken",
                publish_dir=Path(tmpdir) / "publish",
                include_pre_2020=False,
                verbose=False,
            )
            with patch(
                "vtes_scraper.cli.publish.publish_all_as_single_pr",
                return_value=result,
            ) as mock_publish:
                ret = publish_cmd.run(args)
            # No valid tournaments outside errors/ — nothing to publish
            assert ret == 0
            mock_publish.assert_not_called()

    def test_write_publish_report_with_pr_url(self):
        t = _make_tournament()
        result = BatchPRResult(pr_url="https://github.com/pr/1", published=["9999"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(result, Path(tmpdir), "2023-03-25", [t])
            assert path.exists()
            content = path.read_text()
            assert "https://github.com/pr/1" in content

    def test_write_publish_report_skipped_all(self):
        result = BatchPRResult(skipped_all=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(result, Path(tmpdir), "2023-03-25", [])
            content = path.read_text()
            assert "already present on master" in content

    def test_write_publish_report_no_pr(self):
        result = BatchPRResult()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(result, Path(tmpdir), "2023-03-25", [])
            content = path.read_text()
            assert "No PR opened" in content

    def test_write_publish_report_with_errors(self):
        result = BatchPRResult(
            published=["9999"],
            errors=[("bad_id", "Failed to commit")],
        )
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(result, Path(tmpdir), "2023-03-25", [t])
            content = path.read_text()
            assert "bad_id" in content

    def test_write_publish_report_with_skipped(self):
        result = BatchPRResult(skipped=["8888"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = publish_cmd._write_publish_report(result, Path(tmpdir), "2023-03-25", [])
            content = path.read_text()
            assert "8888" in content
