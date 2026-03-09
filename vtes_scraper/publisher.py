"""
GitHub Pull Request publisher for TWD decks.

Collects all tournaments that are not yet present in GiottoVerducci/TWD and
opens a **single** Pull Request containing every new deck file, placed under
the `decks/` folder of that repository.

Authentication:
  Requires a GitHub Personal Access Token (PAT) with 'repo' or
  'public_repo' scope, supplied as the GITHUB_TOKEN environment variable
  or passed explicitly to the functions.

API surface used (GitHub REST v3):
  - GET  /repos/{owner}/{repo}/git/ref/heads/{branch}  → base SHA
  - GET  /repos/{owner}/{repo}/contents/{path}         → check file existence
  - POST /repos/{owner}/{repo}/git/refs               → create branch
  - PUT  /repos/{owner}/{repo}/contents/{path}        → create/update file
  - POST /repos/{owner}/{repo}/pulls                  → open PR
"""

from __future__ import annotations

import os
import base64
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from dotenv import load_dotenv

from vtes_scraper.models import Tournament
from vtes_scraper.output import tournament_to_txt

load_dotenv()

logger = logging.getLogger(__name__)

_TARGET_OWNER = "GiottoVerducci"
_TARGET_REPO = "TWD"
_TARGET_BRANCH = "master"
_DECKS_FOLDER = "decks"
_GITHUB_API = "https://api.github.com"
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class BatchPRResult:
    """Outcome of a single batch publish run."""

    pr_url: str | None = None
    """URL of the opened (or already-open) PR, None if nothing was published."""

    published: list[str] = field(default_factory=list)
    """event_ids successfully committed to the PR branch."""

    skipped: list[str] = field(default_factory=list)
    """event_ids already present on master — not included in the PR."""

    errors: list[tuple[str, str]] = field(default_factory=list)
    """(event_id, error_message) pairs for decks that could not be committed."""

    skipped_all: bool = False
    """True when every tournament was already in the target repo (no PR created)."""


# ---------------------------------------------------------------------------
# Low-level GitHub API helpers
# ---------------------------------------------------------------------------


def _headers(token: str | None = None) -> dict[str, str]:
    if not token:
        token = _GITHUB_TOKEN

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_branch_sha(
    client: httpx.Client,
    branch: str,
    token: str | None = None,
) -> str:
    """Return the current HEAD commit SHA of *branch*."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/git/ref/heads/{branch}"
    resp = client.get(url, headers=_headers(token))
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


def _create_branch(
    client: httpx.Client,
    branch: str,
    sha: str,
    token: str | None = None,
) -> None:
    """Create a new git ref (branch) pointing at *sha* (idempotent)."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/git/refs"
    resp = client.post(
        url,
        headers=_headers(token),
        json={"ref": f"refs/heads/{branch}", "sha": sha},
    )
    if resp.status_code == 422:
        # Branch already exists — reuse it
        logger.debug("Branch %r already exists, reusing it.", branch)
        return
    resp.raise_for_status()


def _file_exists_on_branch(
    client: httpx.Client,
    path: str,
    branch: str,
    token: str | None = None,
) -> bool:
    """Return True if *path* exists on *branch* in the target repo."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/contents/{path}"
    resp = client.get(url, headers=_headers(token), params={"ref": branch})
    return resp.status_code == 200


def _put_file(
    client: httpx.Client,
    path: str,
    content: str,
    branch: str,
    commit_message: str,
    token: str | None = None,
) -> None:
    """Create or update a file on *branch* via the Contents API."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    body: dict = {
        "message": commit_message,
        "content": encoded,
        "branch": branch,
    }

    # If the file already exists on this branch we must supply its current SHA
    resp = client.get(url, headers=_headers(token), params={"ref": branch})
    if resp.status_code == 200:
        body["sha"] = resp.json()["sha"]

    resp = client.put(url, headers=_headers(token), json=body)
    resp.raise_for_status()


def _open_pull_request(
    client: httpx.Client,
    head_branch: str,
    title: str,
    body: str,
    token: str | None = None,
) -> str:
    """Open a PR and return its HTML URL (returns existing URL if already open)."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/pulls"
    resp = client.post(
        url,
        headers=_headers(token),
        json={
            "title": title,
            "head": head_branch,
            "base": _TARGET_BRANCH,
            "body": body,
        },
    )
    if resp.status_code == 422:
        data = resp.json()
        errors = data.get("errors", [])
        for err in errors:
            if "pull request already exists" in str(err.get("message", "")).lower():
                existing = _find_existing_pr(client, token, head_branch)
                if existing:
                    logger.debug(
                        "PR already open for branch %r: %s", head_branch, existing
                    )
                    return existing
    resp.raise_for_status()
    return resp.json()["html_url"]


def _find_existing_pr(
    client: httpx.Client,
    head_branch: str,
    token: str | None = None,
) -> str | None:
    """Find an already-open PR for *head_branch* and return its HTML URL."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/pulls"
    resp = client.get(
        url,
        headers=_headers(token),
        params={"state": "open", "head": f"{_TARGET_OWNER}:{head_branch}"},
    )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]["html_url"]
    return None


def _sanitize_branch_name(text: str) -> str:
    """Convert arbitrary text to a valid git branch name segment."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:50]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def publish_all_as_single_pr(
    tournaments: list[Tournament],
    token: str | None = None,
    branch_prefix: str = "twd/weekly-decks",
    delay: float = 1.0,
) -> BatchPRResult:
    """
    Publish all new tournaments in a **single** Pull Request against
    GiottoVerducci/TWD.

    Steps:
      1. Filter tournaments: skip any deck whose file already exists on master.
      2. If nothing is new, return early (BatchPRResult.skipped_all = True).
      3. Create one branch named ``{branch_prefix}-{YYYY-MM-DD}`` off master.
      4. Commit each new deck's TXT file to that branch.
      5. Open one PR with a summary table of all included decks.

    Args:
        tournaments: All Tournament objects scraped this run.
        token: GitHub PAT with *public_repo* (or *repo*) scope.
        branch_prefix: Prefix for the feature branch name.
        delay: Seconds to wait between consecutive GitHub API file commits.

    Returns:
        A BatchPRResult describing the outcome.
    """
    result = BatchPRResult()

    with httpx.Client(timeout=30) as client:
        # ── Step 1: filter out already-published decks ──────────────────────
        new_tournaments: list[Tournament] = []
        for t in tournaments:
            event_id = t.event_id or "unknown"
            file_path = f"{_DECKS_FOLDER}/{event_id}.txt"
            if _file_exists_on_branch(client, token, file_path, _TARGET_BRANCH):
                logger.debug("Deck %s already on master — skipping.", event_id)
                result.skipped.append(event_id)
            else:
                new_tournaments.append(t)

        # ── Step 2: early exit if nothing new ───────────────────────────────
        if not new_tournaments:
            result.skipped_all = True
            return result

        # ── Step 3: create one branch for the whole batch ───────────────────
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        branch = f"{branch_prefix}-{today}"
        try:
            base_sha = _get_branch_sha(client, token, _TARGET_BRANCH)
            _create_branch(client, token, branch, base_sha)
        except httpx.HTTPStatusError as exc:
            # Cannot even create the branch — abort everything
            for t in new_tournaments:
                result.errors.append(
                    (t.event_id or "unknown", f"Branch creation failed: {exc}")
                )
            return result

        # ── Step 4: commit each deck file ────────────────────────────────────
        for i, t in enumerate(new_tournaments):
            if i > 0:
                time.sleep(delay)

            event_id = t.event_id or "unknown"
            file_path = f"{_DECKS_FOLDER}/{event_id}.txt"
            try:
                txt_content = tournament_to_txt(t)
                commit_msg = f"feat: add TWD deck {event_id} - {t.name}"
                _put_file(client, token, file_path, txt_content, branch, commit_msg)
                result.published.append(event_id)
                logger.debug("Committed %s to branch %s", file_path, branch)
            except httpx.HTTPStatusError as exc:
                err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                result.errors.append((event_id, err))
                logger.error("Failed to commit deck %s: %s", event_id, err)
            except Exception as exc:
                result.errors.append((event_id, str(exc)))
                logger.error("Failed to commit deck %s: %s", event_id, exc)

        # ── Step 5: open the PR (only if at least one file was committed) ───
        if not result.published:
            # All commits failed — no point opening an empty PR
            return result

        pr_title = f"Add {len(result.published)} TWD deck(s) — {today}"

        pr_body_lines = [
            f"Automated weekly import of **{len(result.published)}** new "
            f"tournament winning deck(s) scraped from [vekn.net](https://www.vekn.net/forum/event-reports-and-twd).",
            "",
            "| Event ID | Event Name | Location | Date | Winner |",
            "|---|---|---|---|---|",
        ]
        for t in new_tournaments:
            if (t.event_id or "unknown") in result.published:
                name_link = f"[{t.name}]({t.event_url})" if t.event_url else t.name
                pr_body_lines.append(
                    f"| {t.event_id} | {name_link} | {t.location} | {t.date_start} | {t.winner} |"
                )

        if result.errors:
            pr_body_lines += [
                "",
                f"⚠️ **{len(result.errors)} deck(s) could not be committed** "
                f"(see workflow logs for details):",
            ]
            for event_id, err in result.errors:
                pr_body_lines.append(f"- `{event_id}`: {err}")

        pr_body_lines += [
            "",
            "_Automatically submitted by "
            "[vtes-twd-scraper](https://github.com/Spigushe/twd_scrapper)._",
        ]

        try:
            pr_url = _open_pull_request(
                client,
                token,
                branch,
                pr_title,
                "\n".join(pr_body_lines),
            )
            result.pr_url = pr_url
            logger.info("PR opened: %s", pr_url)
        except httpx.HTTPStatusError as exc:
            err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("Failed to open PR: %s", err)
            # published list is still populated so the caller can report progress

    return result
