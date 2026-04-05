"""Tests for the ``parse`` CLI subcommand."""

import argparse
import tempfile
from pathlib import Path

from vtes_scraper.cli import parse as parse_cmd

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


class TestParseYamlToTxt:
    """Tests for the yaml → txt conversion path (_parse_yaml_to_txt)."""

    def _write_yaml_tournament(self, tmpdir: Path) -> Path:
        """Parse the SIMPLE_TWD into a YAML file and return its path."""
        import argparse as _ap
        import tempfile as _tf

        tmpdir.mkdir(parents=True, exist_ok=True)
        with _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(SIMPLE_TWD)
            src = Path(f.name)

        args = _ap.Namespace(
            input_file=src,
            output_dir=tmpdir,
            overwrite=False,
            verbose=False,
        )
        parse_cmd.run(args)
        src.unlink()
        yamls = list(tmpdir.rglob("*.yaml"))
        assert yamls, "No YAML file produced by txt→yaml step"
        return yamls[0]

    def test_yaml_to_txt_stdout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = self._write_yaml_tournament(Path(tmpdir) / "src")
            args = argparse.Namespace(
                input_file=yaml_path,
                output_dir=None,
                overwrite=False,
                verbose=False,
            )
            ret = parse_cmd.run(args)
        assert ret == 0

    def test_yaml_to_txt_with_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            out_dir = Path(tmpdir) / "out"
            out_dir.mkdir()
            yaml_path = self._write_yaml_tournament(src_dir)
            args = argparse.Namespace(
                input_file=yaml_path,
                output_dir=out_dir,
                overwrite=False,
                verbose=False,
            )
            ret = parse_cmd.run(args)
        assert ret == 0

    def test_yaml_to_txt_file_exists_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            out_dir = Path(tmpdir) / "out"
            out_dir.mkdir()
            yaml_path = self._write_yaml_tournament(src_dir)
            args = argparse.Namespace(
                input_file=yaml_path,
                output_dir=out_dir,
                overwrite=False,
                verbose=False,
            )
            parse_cmd.run(args)
            ret = parse_cmd.run(args)  # second call → FileExistsError caught
        assert ret == 0

    def test_yaml_parse_error_returns_1(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(": : : invalid yaml {{{{")
            bad_yaml = Path(f.name)
        args = argparse.Namespace(
            input_file=bad_yaml,
            output_dir=None,
            overwrite=False,
            verbose=False,
        )
        ret = parse_cmd.run(args)
        bad_yaml.unlink()
        assert ret == 1

    def test_yml_extension_also_works(self):
        """.yml extension should be treated the same as .yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            yaml_path = self._write_yaml_tournament(src_dir)
            yml_path = yaml_path.with_suffix(".yml")
            yaml_path.rename(yml_path)
            args = argparse.Namespace(
                input_file=yml_path,
                output_dir=None,
                overwrite=False,
                verbose=False,
            )
            ret = parse_cmd.run(args)
        assert ret == 0


class TestParseUnsupportedExtension:
    def test_unsupported_extension_returns_1(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            tmp = Path(f.name)
        args = argparse.Namespace(
            input_file=tmp,
            output_dir=None,
            overwrite=False,
            verbose=False,
        )
        ret = parse_cmd.run(args)
        tmp.unlink()
        assert ret == 1
