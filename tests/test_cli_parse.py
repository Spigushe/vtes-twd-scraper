"""Tests for the ``parse`` CLI subcommand."""

import argparse
import tempfile
from pathlib import Path

from vtes_scraper_v1.cli import parse as parse_cmd

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
