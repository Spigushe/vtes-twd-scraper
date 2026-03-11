"""
Tests for topic icon detection (_detect_topic_icon) and the scrape CLI
routing logic (idea=skip, merged→changes_required/, others→YYYY/MM/).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

import vtes_scraper.cli.scrape as _scrape_mod  # import directly, bypasses cli/__init__
from vtes_scraper.scraper import (
    ICON_DEFAULT,
    ICON_IDEA,
    ICON_MERGED,
    ICON_SOLVED,
    _detect_topic_icon,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ICON_BASE = "https://www.vekn.net/media/kunena/topic_icons/default/user/"


def _make_soup(icon_stem: str | None, container: str = "div") -> BeautifulSoup:
    """
    Build a minimal forum-index row with an optional Kunena icon image.

    container: "div" (class="krow"), "tr", or "li"
    """
    img = f'<img src="{_ICON_BASE}{icon_stem}.png">' if icon_stem else ""

    if container == "tr":
        html = (
            f'<table><tr class="krow">'
            f"{img}"
            f'<td><a href="/forum/event-reports-and-twd/123-test">Title</a></td>'
            f"</tr></table>"
        )
    elif container == "li":
        html = (
            f'<ul><li class="ktopic">'
            f"{img}"
            f'<a href="/forum/event-reports-and-twd/123-test">Title</a>'
            f"</li></ul>"
        )
    else:
        html = (
            f'<div class="krow">'
            f"{img}"
            f'<a href="/forum/event-reports-and-twd/123-test">Title</a>'
            f"</div>"
        )
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# _detect_topic_icon
# ---------------------------------------------------------------------------


class TestDetectTopicIcon:
    def test_idea_icon(self):
        soup = _make_soup("idea")
        assert _detect_topic_icon(soup.find("a")) == ICON_IDEA

    def test_merged_icon(self):
        soup = _make_soup("merged")
        assert _detect_topic_icon(soup.find("a")) == ICON_MERGED

    def test_solved_icon(self):
        soup = _make_soup("solved")
        assert _detect_topic_icon(soup.find("a")) == ICON_SOLVED

    def test_default_icon(self):
        soup = _make_soup("default")
        assert _detect_topic_icon(soup.find("a")) == ICON_DEFAULT

    def test_no_icon_returns_none(self):
        soup = _make_soup(None)
        assert _detect_topic_icon(soup.find("a")) is None

    def test_unrelated_image_returns_none(self):
        html = (
            '<div class="krow">'
            '<img src="https://www.vekn.net/images/logo.png">'
            '<a href="/forum/event-reports-and-twd/123-test">Title</a>'
            "</div>"
        )
        soup = BeautifulSoup(html, "lxml")
        assert _detect_topic_icon(soup.find("a")) is None

    def test_icon_in_tr_container(self):
        soup = _make_soup("merged", container="tr")
        assert _detect_topic_icon(soup.find("a")) == ICON_MERGED

    def test_icon_in_li_container(self):
        soup = _make_soup("idea", container="li")
        assert _detect_topic_icon(soup.find("a")) == ICON_IDEA

    def test_icon_outside_row_still_detected(self):
        """Falls back to link_tag.parent when no row container is found."""
        html = (
            "<div>"
            f'<img src="{_ICON_BASE}solved.png">'
            '<a href="/forum/event-reports-and-twd/123-test">Title</a>'
            "</div>"
        )
        soup = BeautifulSoup(html, "lxml")
        assert _detect_topic_icon(soup.find("a")) == ICON_SOLVED


# ---------------------------------------------------------------------------
# Fixtures — minimal Tournament stubs for CLI tests
# ---------------------------------------------------------------------------


def _make_tournament(event_id: str = "9999") -> MagicMock:
    t = MagicMock()
    t.event_id = event_id
    t.name = f"Test Tournament {event_id}"
    t.yaml_filename = f"{event_id}.yaml"
    return t


# ---------------------------------------------------------------------------
# CLI routing — scrape.run()
# ---------------------------------------------------------------------------


class TestScrapeCliRouting:
    """
    Test scrape.run() routing without hitting the network.
    scrape_forum is mocked to yield (tournament, icon) pairs.
    write_tournament_yaml is mocked to avoid file-system side-effects where
    appropriate; we use tmp_path for real-write assertions.
    """

    def _run(self, tmp_path: Path, yields: list[tuple]) -> int:
        """Invoke cli.scrape.run() with mocked scrape_forum."""
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )

        with patch.object(scrape_mod, "scrape_forum", return_value=iter(yields)):
            return scrape_mod.run(args)

    # ------------------------------------------------------------------
    # merged → changes_required/
    # ------------------------------------------------------------------

    def test_merged_writes_to_changes_required(self, tmp_path):
        t = _make_tournament("8001")
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(
                scrape_mod, "scrape_forum", return_value=iter([(t, ICON_MERGED)])
            ),
            patch.object(
                scrape_mod, "tournament_to_yaml_str", return_value="yaml: content\n"
            ),
        ):
            scrape_mod.run(args)

        expected = tmp_path / "changes_required" / "8001.yaml"
        assert expected.exists()

    def test_merged_does_not_write_to_normal_dir(self, tmp_path):
        t = _make_tournament("8002")
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(
                scrape_mod, "scrape_forum", return_value=iter([(t, ICON_MERGED)])
            ),
            patch.object(
                scrape_mod, "tournament_to_yaml_str", return_value="yaml: content\n"
            ),
            patch.object(scrape_mod, "write_tournament_yaml") as mock_write,
        ):
            scrape_mod.run(args)

        mock_write.assert_not_called()

    def test_merged_always_overwrites(self, tmp_path):
        """merged files are always rewritten — no FileExistsError guard."""
        t = _make_tournament("8003")
        (tmp_path / "changes_required").mkdir()
        (tmp_path / "changes_required" / "8003.yaml").write_text("old: content\n")

        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(
                scrape_mod, "scrape_forum", return_value=iter([(t, ICON_MERGED)])
            ),
            patch.object(
                scrape_mod, "tournament_to_yaml_str", return_value="new: content\n"
            ),
        ):
            scrape_mod.run(args)

        content = (tmp_path / "changes_required" / "8003.yaml").read_text()
        assert content == "new: content\n"

    # ------------------------------------------------------------------
    # default / solved → normal dir; stale changes_required file removed
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("icon", [ICON_DEFAULT, ICON_SOLVED, None])
    def test_normal_icons_write_to_normal_dir(self, tmp_path, icon):
        t = _make_tournament("8010")
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        written_paths = []
        with (
            patch.object(scrape_mod, "scrape_forum", return_value=iter([(t, icon)])),
            patch.object(
                scrape_mod,
                "write_tournament_yaml",
                side_effect=lambda tournament, output_dir, **kw: _capture(
                    written_paths, output_dir / "fake" / tournament.yaml_filename
                ),
            ),
        ):
            scrape_mod.run(args)

        assert len(written_paths) == 1

    @pytest.mark.parametrize("icon", [ICON_DEFAULT, ICON_SOLVED, None])
    def test_stale_changes_required_deleted(self, tmp_path, icon):
        """When a topic reverts from merged to default/solved, delete the stale copy."""
        t = _make_tournament("8020")
        stale = tmp_path / "changes_required" / "8020.yaml"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale: true\n")

        scrape_mod = _scrape_mod

        normal_path = tmp_path / "2023" / "01" / "8020.yaml"

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(scrape_mod, "scrape_forum", return_value=iter([(t, icon)])),
            patch.object(
                scrape_mod,
                "write_tournament_yaml",
                return_value=normal_path,
            ),
        ):
            scrape_mod.run(args)

        assert (
            not stale.exists()
        ), "stale changes_required file should have been deleted"

    @pytest.mark.parametrize("icon", [ICON_DEFAULT, ICON_SOLVED, None])
    def test_no_stale_file_is_fine(self, tmp_path, icon):
        """No error when there is no stale changes_required file to delete."""
        t = _make_tournament("8030")
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(scrape_mod, "scrape_forum", return_value=iter([(t, icon)])),
            patch.object(
                scrape_mod, "write_tournament_yaml", return_value=tmp_path / "x.yaml"
            ),
        ):
            rc = scrape_mod.run(args)

        assert rc == 0

    # ------------------------------------------------------------------
    # Return codes
    # ------------------------------------------------------------------

    def test_returns_zero_on_success(self, tmp_path):
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with patch.object(scrape_mod, "scrape_forum", return_value=iter([])):
            rc = scrape_mod.run(args)
        assert rc == 0

    # ------------------------------------------------------------------
    # Missing event_id guard
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("icon", [ICON_DEFAULT, ICON_MERGED, ICON_SOLVED, None])
    def test_missing_event_id_is_skipped(self, tmp_path, icon):
        """A tournament with no event_id must be skipped, not crash."""
        t = _make_tournament("")  # empty event_id → yaml_filename raises ValueError
        t.event_id = ""
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(scrape_mod, "scrape_forum", return_value=iter([(t, icon)])),
            patch.object(scrape_mod, "write_tournament_yaml") as mock_write,
        ):
            rc = scrape_mod.run(args)

        assert rc == 0
        mock_write.assert_not_called()
        assert not (tmp_path / "changes_required").exists()

    def test_returns_one_on_failure(self, tmp_path):
        t = _make_tournament("9999")
        scrape_mod = _scrape_mod

        args = argparse.Namespace(
            output_dir=tmp_path,
            max_pages=None,
            start_page=0,
            delay=0,
            overwrite=False,
            verbose=False,
        )
        with (
            patch.object(
                scrape_mod, "scrape_forum", return_value=iter([(t, ICON_DEFAULT)])
            ),
            patch.object(
                scrape_mod, "write_tournament_yaml", side_effect=RuntimeError("boom")
            ),
        ):
            rc = scrape_mod.run(args)

        assert rc == 1


# ---------------------------------------------------------------------------
# Helper used in parametrised test above
# ---------------------------------------------------------------------------


def _capture(lst: list, path: Path) -> Path:
    lst.append(path)
    return path
