"""Tests for vtes_scraper.publisher using httpx mocking."""

from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vtes_scraper.models import CryptCard, Deck, LibraryCard, LibrarySection, Tournament
from vtes_scraper.publisher import (
    BatchPRResult,
    _create_branch,
    _delete_branch,
    _file_exists_on_branch,
    _find_existing_pr,
    _get_authenticated_user,
    _get_branch_sha,
    _headers,
    _open_pull_request,
    _put_file,
    _sanitize_branch_name,
    publish_all_as_single_pr,
)


def _make_tournament(event_id_num: int = 9999) -> Tournament:
    return Tournament(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url=f"https://www.vekn.net/event-calendar/event/{event_id_num}",
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
# _headers
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_raises_without_token(self):
        with patch("vtes_scraper.publisher._GITHUB_TOKEN", None):
            with pytest.raises(ValueError, match="GitHub token"):
                _headers(token=None)

    def test_returns_dict_with_token(self):
        h = _headers(token="mytoken")
        assert h["Authorization"] == "Bearer mytoken"
        assert "Accept" in h

    def test_uses_env_token_when_not_passed(self):
        with patch("vtes_scraper.publisher._GITHUB_TOKEN", "env_token"):
            h = _headers(token=None)
        assert h["Authorization"] == "Bearer env_token"


# ---------------------------------------------------------------------------
# _sanitize_branch_name
# ---------------------------------------------------------------------------


class TestSanitizeBranchName:
    def test_lowercase(self):
        assert _sanitize_branch_name("Hello World") == "hello-world"

    def test_special_chars_replaced(self):
        assert _sanitize_branch_name("test!@#$name") == "test-name"

    def test_truncated_at_50(self):
        long_name = "a" * 100
        result = _sanitize_branch_name(long_name)
        assert len(result) <= 50

    def test_strips_leading_trailing_dashes(self):
        result = _sanitize_branch_name("--hello--")
        assert not result.startswith("-")
        assert not result.endswith("-")


# ---------------------------------------------------------------------------
# Low-level API helpers
# ---------------------------------------------------------------------------


class TestGetAuthenticatedUser:
    def test_returns_login(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"login": "testuser"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        result = _get_authenticated_user(mock_client, token="mytoken")
        assert result == "testuser"


class TestGetBranchSha:
    def test_returns_sha(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"object": {"sha": "abc123"}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        sha = _get_branch_sha(mock_client, "master", token="mytoken")
        assert sha == "abc123"


class TestCreateBranch:
    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        # Should not raise
        _create_branch(mock_client, "new-branch", "abc123", token="mytoken")

    def test_already_exists_422(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        # Should not raise even if 422
        _create_branch(mock_client, "existing-branch", "abc123", token="mytoken")


class TestFileExistsOnBranch:
    def test_returns_true_when_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        result = _file_exists_on_branch(
            mock_client, "decks/test.txt", "master", token="t"
        )
        assert result is True

    def test_returns_false_when_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        result = _file_exists_on_branch(
            mock_client, "decks/test.txt", "master", token="t"
        )
        assert result is False


class TestPutFile:
    def test_creates_new_file(self):
        # GET returns 404 (no existing file), PUT succeeds
        get_resp = MagicMock()
        get_resp.status_code = 404

        put_resp = MagicMock()
        put_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = get_resp
        mock_client.put.return_value = put_resp

        _put_file(mock_client, "decks/test.txt", "content", "branch", "msg", token="t")
        mock_client.put.assert_called_once()

    def test_updates_existing_file(self):
        # GET returns 200 with existing sha
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {"sha": "existing_sha"}

        put_resp = MagicMock()
        put_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = get_resp
        mock_client.put.return_value = put_resp

        _put_file(mock_client, "decks/test.txt", "content", "branch", "msg", token="t")
        # PUT was called with sha in body
        call_kwargs = mock_client.put.call_args[1]
        assert call_kwargs["json"]["sha"] == "existing_sha"


class TestOpenPullRequest:
    def test_returns_pr_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "html_url": "https://github.com/owner/repo/pull/1"
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        url = _open_pull_request(mock_client, "branch", "Title", "Body", token="t")
        assert url == "https://github.com/owner/repo/pull/1"

    def test_existing_pr_422(self):
        # 422 with "pull request already exists"
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 422
        mock_post_resp.json.return_value = {
            "errors": [{"message": "A pull request already exists for this head"}]
        }
        mock_post_resp.raise_for_status = MagicMock()

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = [
            {"html_url": "https://github.com/owner/repo/pull/2"}
        ]

        mock_client = MagicMock()
        mock_client.post.return_value = mock_post_resp
        mock_client.get.return_value = mock_get_resp

        url = _open_pull_request(mock_client, "branch", "Title", "Body", token="t")
        assert url == "https://github.com/owner/repo/pull/2"

    def test_other_422_raises(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {
            "errors": [{"message": "Unrelated validation error"}]
        }
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=MagicMock()
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        with pytest.raises(httpx.HTTPStatusError):
            _open_pull_request(mock_client, "branch", "Title", "Body", token="t")


class TestFindExistingPr:
    def test_returns_url_when_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"html_url": "https://github.com/owner/repo/pull/5"}
        ]

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        url = _find_existing_pr(mock_client, "branch", token="t")
        assert url == "https://github.com/owner/repo/pull/5"

    def test_returns_none_when_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        url = _find_existing_pr(mock_client, "branch", token="t")
        assert url is None

    def test_returns_none_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = []

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        url = _find_existing_pr(mock_client, "branch", token="t")
        assert url is None


# ---------------------------------------------------------------------------
# BatchPRResult
# ---------------------------------------------------------------------------


class TestDeleteBranch:
    def test_success_204(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        mock_client = MagicMock()
        mock_client.delete.return_value = mock_resp

        # Should not raise
        _delete_branch(mock_client, "my-branch", token="mytoken", owner="testuser")
        mock_client.delete.assert_called_once()

    def test_non_204_logs_warning(self, caplog):
        import logging

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.delete.return_value = mock_resp

        with caplog.at_level(logging.WARNING, logger="vtes_scraper.publisher"):
            _delete_branch(
                mock_client, "missing-branch", token="mytoken", owner="testuser"
            )

        assert any("Could not delete branch" in r.message for r in caplog.records)


class TestBatchPRResult:
    def test_defaults(self):
        result = BatchPRResult()
        assert result.pr_url is None
        assert result.published == []
        assert result.skipped == []
        assert result.errors == []
        assert result.skipped_all is False
        assert result.dry_run is False

    def test_dry_run_flag(self):
        result = BatchPRResult(dry_run=True)
        assert result.dry_run is True


# ---------------------------------------------------------------------------
# publish_all_as_single_pr
# ---------------------------------------------------------------------------


class TestPublishAllAsSinglePr:
    def _mock_client_responses(self, file_exists=False, fork_fails=False):
        """Build a mock httpx.Client context manager with common responses."""
        # Authenticated user
        user_resp = MagicMock()
        user_resp.json.return_value = {"login": "testuser"}
        user_resp.raise_for_status = MagicMock()

        # Fork
        fork_resp = MagicMock()
        fork_resp.raise_for_status = MagicMock()
        if fork_fails:
            fork_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock()
            )

        # Fork check (polling)
        fork_check_resp = MagicMock()
        fork_check_resp.status_code = 200

        # File exists check
        file_check_resp = MagicMock()
        file_check_resp.status_code = 200 if file_exists else 404

        # Branch SHA
        sha_resp = MagicMock()
        sha_resp.json.return_value = {"object": {"sha": "abc123"}}
        sha_resp.raise_for_status = MagicMock()

        # Create branch
        branch_resp = MagicMock()
        branch_resp.status_code = 201
        branch_resp.raise_for_status = MagicMock()

        # Put file (get existing)
        put_get_resp = MagicMock()
        put_get_resp.status_code = 404

        # Put file (actual put)
        put_resp = MagicMock()
        put_resp.raise_for_status = MagicMock()

        # Open PR
        pr_resp = MagicMock()
        pr_resp.status_code = 201
        pr_resp.json.return_value = {
            "html_url": "https://github.com/GiottoVerducci/TWD/pull/99"
        }
        pr_resp.raise_for_status = MagicMock()

        return (
            user_resp,
            fork_resp,
            fork_check_resp,
            file_check_resp,
            sha_resp,
            branch_resp,
            put_get_resp,
            put_resp,
            pr_resp,
        )

    def test_all_skipped_returns_skipped_all(self):
        t = _make_tournament()

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=True),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert result.skipped_all is True
        assert result.pr_url is None

    def test_fork_failure_returns_errors(self):
        t = _make_tournament()

        err = httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())
        with patch("vtes_scraper.publisher._ensure_fork", side_effect=err):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert len(result.errors) == 1

    def test_successful_publish(self):
        t = _make_tournament()

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file"),
            patch(
                "vtes_scraper.publisher._open_pull_request",
                return_value="https://github.com/pr/1",
            ),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert result.pr_url == "https://github.com/pr/1"
        assert len(result.published) == 1

    def test_branch_creation_failure(self):
        t = _make_tournament()
        err = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", side_effect=err),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert len(result.errors) == 1
        assert "Branch creation failed" in result.errors[0][1]

    def test_put_file_http_error(self):
        t = _make_tournament()
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "Unprocessable"
        err = httpx.HTTPStatusError("422", request=MagicMock(), response=mock_response)

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file", side_effect=err),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert len(result.errors) == 1
        assert result.pr_url is None  # no PR if nothing published

    def test_put_file_generic_error(self):
        t = _make_tournament()

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file", side_effect=RuntimeError("oops")),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        assert len(result.errors) == 1

    def test_pr_open_http_error_does_not_raise(self):
        t = _make_tournament()
        err = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file"),
            patch("vtes_scraper.publisher._open_pull_request", side_effect=err),
        ):
            result = publish_all_as_single_pr([t], token="mytoken", delay=0)

        # Published but no PR URL
        assert len(result.published) == 1
        assert result.pr_url is None

    def test_multiple_tournaments_with_mix(self):
        t1 = _make_tournament(9001)
        t2 = _make_tournament(9002)

        def file_exists(client, path, branch, token):
            return "9001" in path  # t1 already exists

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch(
                "vtes_scraper.publisher._file_exists_on_branch", side_effect=file_exists
            ),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file"),
            patch(
                "vtes_scraper.publisher._open_pull_request",
                return_value="https://github.com/pr/1",
            ),
        ):
            result = publish_all_as_single_pr([t1, t2], token="mytoken", delay=0)

        assert "9001" in result.skipped
        assert "9002" in result.published

    def test_dry_run_deletes_branch_and_no_pr(self):
        t = _make_tournament()

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file"),
            patch("vtes_scraper.publisher._open_pull_request") as mock_pr,
            patch("vtes_scraper.publisher._delete_branch") as mock_del,
        ):
            result = publish_all_as_single_pr(
                [t], token="mytoken", delay=0, dry_run=True
            )

        assert result.dry_run is True
        assert result.pr_url is None
        assert len(result.published) == 1
        mock_pr.assert_not_called()
        mock_del.assert_called_once()

    def test_dry_run_all_skipped_no_branch_deleted(self):
        t = _make_tournament()

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=True),
            patch("vtes_scraper.publisher._delete_branch") as mock_del,
        ):
            result = publish_all_as_single_pr(
                [t], token="mytoken", delay=0, dry_run=True
            )

        assert result.skipped_all is True
        mock_del.assert_not_called()

    def test_dry_run_all_commits_failed_deletes_branch(self):
        t = _make_tournament()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        err = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response)

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file", side_effect=err),
            patch("vtes_scraper.publisher._delete_branch") as mock_del,
        ):
            result = publish_all_as_single_pr(
                [t], token="mytoken", delay=0, dry_run=True
            )

        assert len(result.errors) == 1
        assert result.pr_url is None
        mock_del.assert_called_once()

    def test_with_errors_in_pr_body(self):
        """Test PR body generation when there are both published and errored decks."""
        t1 = _make_tournament(9001)
        t2 = _make_tournament(9002)
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "Bad"
        err = httpx.HTTPStatusError("422", request=MagicMock(), response=mock_response)

        call_count = [0]

        def put_file_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise err

        with (
            patch("vtes_scraper.publisher._ensure_fork", return_value="testuser"),
            patch("vtes_scraper.publisher._file_exists_on_branch", return_value=False),
            patch("vtes_scraper.publisher._get_branch_sha", return_value="abc123"),
            patch("vtes_scraper.publisher._create_branch"),
            patch("vtes_scraper.publisher._put_file", side_effect=put_file_side_effect),
            patch(
                "vtes_scraper.publisher._open_pull_request",
                return_value="https://github.com/pr/3",
            ),
        ):
            result = publish_all_as_single_pr([t1, t2], token="mytoken", delay=0)

        assert len(result.published) == 1
        assert len(result.errors) == 1
        assert result.pr_url == "https://github.com/pr/3"
