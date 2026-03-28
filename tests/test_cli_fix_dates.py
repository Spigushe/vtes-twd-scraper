"""Tests for the ``fix-date`` CLI subcommand."""

import argparse
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from vtes_scraper.cli import fix_dates as fix_dates_cmd

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
