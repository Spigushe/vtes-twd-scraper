"""
GitHub Pull Request publisher for TWD decks.

Forks GiottoVerducci/TWD into the authenticated user's account (if not
already forked), pushes new deck files to a branch on the fork, and opens
a **single** Pull Request back into the upstream repository.

Authentication:
  Requires a GitHub Personal Access Token (PAT) with 'public_repo' scope,
  supplied as the GITHUB_TOKEN environment variable or passed explicitly.

API surface used (GitHub REST v3):
  - GET  /user                                         → authenticated user login
  - POST /repos/{owner}/{repo}/forks                   → fork upstream repo
  - GET  /repos/{owner}/{repo}/git/refs/heads/{branch} → base SHA (upstream)
  - GET  /repos/{owner}/{repo}/contents/{path}         → check file existence (upstream)
  - POST /repos/{fork_owner}/{repo}/git/refs           → create branch on fork
  - PUT  /repos/{fork_owner}/{repo}/contents/{path}    → create/update file on fork
  - POST /repos/{owner}/{repo}/pulls                   → open PR into upstream
"""

import base64
import logging
import os
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

    published: list[int | str] = field(default_factory=list[int | str])
    """event_ids successfully committed to the PR branch."""

    skipped: list[int | str] = field(default_factory=list[int | str])
    """event_ids already present on master — not included in the PR."""

    errors: list[tuple[int | str, str]] = field(default_factory=list[tuple[int | str, str]])
    """(event_id, error_message) pairs for decks that could not be committed."""

    skipped_all: bool = False
    """True when every tournament was already in the target repo (no PR created)."""

    dry_run: bool = False
    """True when this result comes from a dry-run (branch deleted, no PR opened)."""


# ---------------------------------------------------------------------------
# Low-level GitHub API helpers
# ---------------------------------------------------------------------------


def _headers(token: str | None = None) -> dict[str, str]:
    if not token:
        token = _GITHUB_TOKEN
    if not token:
        raise ValueError(
            "GitHub token not provided. "
            "Set the GITHUB_TOKEN environment variable or pass it explicitly."
        )
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }


def _get_authenticated_user(client: httpx.Client, token: str | None = None) -> str:
    """Return the login of the token's owner via GET /user."""
    resp = client.get(f"{_GITHUB_API}/user", headers=_headers(token))
    resp.raise_for_status()
    return str(resp.json()["login"])


def _ensure_fork(client: httpx.Client, token: str | None = None) -> str:
    """Fork GiottoVerducci/TWD if needed and return the fork owner's login.

    POST /forks is idempotent — GitHub returns the existing fork when one
    already exists.  Fork creation is asynchronous, so we poll until the
    fork's API endpoint responds 200 (up to 10 seconds).
    """
    fork_owner = _get_authenticated_user(client, token)
    resp = client.post(
        f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/forks",
        headers=_headers(token),
    )
    resp.raise_for_status()
    logger.debug(
        "Fork ensured for %s/%s under %s.",
        _TARGET_OWNER,
        _TARGET_REPO,
        fork_owner,
    )
    fork_url = f"{_GITHUB_API}/repos/{fork_owner}/{_TARGET_REPO}"
    for _ in range(10):
        if client.get(fork_url, headers=_headers(token)).status_code == 200:
            break
        time.sleep(1)
    return fork_owner


def _get_branch_sha(
    client: httpx.Client,
    branch: str,
    token: str | None = None,
) -> str:
    """Return the current HEAD commit SHA of *branch*."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/git/refs/heads/{branch}"
    resp = client.get(url, headers=_headers(token))
    resp.raise_for_status()
    return str(resp.json()["object"]["sha"])


def _create_branch(
    client: httpx.Client,
    branch: str,
    sha: str,
    token: str | None = None,
    owner: str = _TARGET_OWNER,
) -> None:
    """Create a new git ref (branch) pointing at *sha* (idempotent)."""
    url = f"{_GITHUB_API}/repos/{owner}/{_TARGET_REPO}/git/refs"
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
    owner: str = _TARGET_OWNER,
) -> None:
    """Create or update a file on *branch* via the Contents API."""
    url = f"{_GITHUB_API}/repos/{owner}/{_TARGET_REPO}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    body: dict[str, str] = {
        "message": commit_message,
        "content": encoded,
        "branch": branch,
    }

    # If the file already exists on this branch we must supply its current SHA
    resp = client.get(url, headers=_headers(token), params={"ref": branch})
    if resp.status_code == 200:
        body["sha"] = str(resp.json()["sha"])

    resp = client.put(url, headers=_headers(token), json=body)
    resp.raise_for_status()


def _open_pull_request(
    client: httpx.Client,
    head_branch: str,
    title: str,
    body: str,
    token: str | None = None,
    fork_owner: str = _TARGET_OWNER,
) -> str:
    """Open a PR from *fork_owner*:*head_branch* into upstream and return its HTML URL."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/pulls"
    head = f"{fork_owner}:{head_branch}"
    resp = client.post(
        url,
        headers=_headers(token),
        json={
            "title": title,
            "head": head,
            "base": _TARGET_BRANCH,
            "body": body,
        },
    )
    if resp.status_code == 422:
        data = resp.json()
        errors = data.get("errors", [])
        for err in errors:
            if "pull request already exists" in str(err.get("message", "")).lower():
                existing = _find_existing_pr(client, head_branch, token, fork_owner)
                if existing:
                    logger.debug(
                        "PR already open for branch %r: %s",
                        head_branch,
                        existing,
                    )
                    return existing
    resp.raise_for_status()
    return str(resp.json()["html_url"])


def _find_existing_pr(
    client: httpx.Client,
    head_branch: str,
    token: str | None = None,
    fork_owner: str = _TARGET_OWNER,
) -> str | None:
    """Find an already-open PR for *fork_owner*:*head_branch* and return its HTML URL."""
    url = f"{_GITHUB_API}/repos/{_TARGET_OWNER}/{_TARGET_REPO}/pulls"
    resp = client.get(
        url,
        headers=_headers(token),
        params={"state": "open", "head": f"{fork_owner}:{head_branch}"},
    )
    if resp.status_code == 200 and resp.json():
        return str(resp.json()[0]["html_url"])
    return None


def _delete_branch(
    client: httpx.Client,
    branch: str,
    token: str | None = None,
    owner: str = _TARGET_OWNER,
) -> None:
    """Delete a git ref (branch) on *owner*'s fork (best-effort)."""
    url = f"{_GITHUB_API}/repos/{owner}/{_TARGET_REPO}/git/refs/heads/{branch}"
    resp = client.delete(url, headers=_headers(token))
    if resp.status_code == 204:
        logger.debug("Deleted branch %r on %s.", branch, owner)
    else:
        logger.warning(
            "Could not delete branch %r on %s: HTTP %s",
            branch,
            owner,
            resp.status_code,
        )


def sanitize_branch_name(text: str) -> str:
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
    dry_run: bool = False,
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
         (dry_run: skip PR creation and delete the branch instead)

    Args:
        tournaments: All Tournament objects scraped this run.
        token: GitHub PAT with *public_repo* (or *repo*) scope.
        branch_prefix: Prefix for the feature branch name.
        delay: Seconds to wait between consecutive GitHub API file commits.
        dry_run: When True, create branch and commit files to verify behaviour,
            then delete the branch instead of opening a PR.

    Returns:
        A BatchPRResult describing the outcome.
    """
    result = BatchPRResult(dry_run=dry_run)

    with httpx.Client(timeout=30) as client:
        # ── Step 0: ensure fork exists ───────────────────────────────────────
        try:
            fork_owner = _ensure_fork(client, token)
        except httpx.HTTPStatusError as exc:
            for t in tournaments:
                result.errors.append((t.event_id or "unknown", f"Fork creation failed: {exc}"))
            return result

        # ── Step 1: filter out already-published decks ──────────────────────
        new_tournaments: list[Tournament] = []
        for t in tournaments:
            event_id = t.event_id or "unknown"
            file_path = f"{_DECKS_FOLDER}/{event_id}.txt"
            if _file_exists_on_branch(client, file_path, _TARGET_BRANCH, token):
                logger.debug("Deck %s already on master — skipping.", event_id)
                result.skipped.append(event_id)
            else:
                new_tournaments.append(t)

        # ── Step 2: early exit if nothing new ───────────────────────────────
        if not new_tournaments:
            result.skipped_all = True
            return result

        # ── Step 3: create one branch on the fork ───────────────────────────
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        branch = f"{branch_prefix}-{today}"
        try:
            base_sha = _get_branch_sha(client, _TARGET_BRANCH, token)
            _create_branch(client, branch, base_sha, token, owner=fork_owner)
        except httpx.HTTPStatusError as exc:
            # Cannot even create the branch — abort everything
            for t in new_tournaments:
                result.errors.append((t.event_id or "unknown", f"Branch creation failed: {exc}"))
            return result

        # ── Step 4: commit each deck file to the fork ────────────────────────
        for i, t in enumerate(new_tournaments):
            if i > 0:
                time.sleep(delay)

            event_id = t.event_id or "unknown"
            file_path = f"{_DECKS_FOLDER}/{event_id}.txt"
            try:
                txt_content = tournament_to_txt(t)
                commit_msg = f"feat: add TWD deck {event_id} - {t.name}"
                _put_file(
                    client,
                    file_path,
                    txt_content,
                    branch,
                    commit_msg,
                    token,
                    owner=fork_owner,
                )
                result.published.append(event_id)
                logger.debug("Committed %s to branch %s", file_path, branch)
            except httpx.HTTPStatusError as exc:
                err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                result.errors.append((event_id, err))
                logger.error("Failed to commit deck %s: %s", event_id, err)
            except Exception as exc:
                result.errors.append((event_id, str(exc)))
                logger.error("Failed to commit deck %s: %s", event_id, exc)

        # ── Step 5: open PR or (dry-run) delete the branch ───────────────────
        if not result.published:
            # All commits failed — no point opening an empty PR or keeping branch
            if dry_run:
                _delete_branch(client, branch, token, owner=fork_owner)
            return result

        if dry_run:
            logger.info("Dry-run: deleting branch %r instead of opening a PR.", branch)
            _delete_branch(client, branch, token, owner=fork_owner)
            return result

        pr_title = f"Add {len(result.published)} TWD deck(s) — {today}"

        pr_body_lines = [
            f"Automated weekly import of **{len(result.published)}** new "
            f"tournament winning deck(s) scraped from [vekn.net](https://www.vekn.net/forum/event-reports-and-twd).",
            "",
            "| Event ID | Event Name | Location | Date | Winner |",
            "| -------- | ---------- | -------- | ---- | ------ |",
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
                branch,
                pr_title,
                "\n".join(pr_body_lines),
                token,
                fork_owner=fork_owner,
            )
            result.pr_url = pr_url
            logger.info("PR opened: %s", pr_url)
        except httpx.HTTPStatusError as exc:
            err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("Failed to open PR: %s", err)
            # published list is still populated so the caller can report progress

    return result
