# PR #4 Evaluation: Player Name Coercion vs Issue #3 Requirements

## Context

**Issue #3** "[FEATURE] Player Name Coercion" requests a `--check-players` validation
option so the scraper can verify tournament winners are registered VEKN members,
improving data quality before pushing to the master TWD repository.

**PR #4** "Add player name validation for VEKN membership" (Draft, by copilot-swe-agent)
implements that feature across 6 files (510 insertions, 21 new tests).

---

## Requirement vs Implementation Mapping

### Req 1 — `--check-players` CLI flag ✅
**Issue says:** Implement a `--check-players` validation option.
**PR delivers:** `--check-players` added to `validate` subcommand in
`vtes_scraper/cli/validate.py` (lines 143–165).

### Req 2 — Query VEKN player database with exact name ✅
**Issue says:** Query the VEKN player database using the winner's exact name.
**PR delivers:** `fetch_player()` in `vtes_scraper/scraper.py` queries
`https://www.vekn.net/event-calendar/players?name=<name>&sort=constructed`,
URL-encodes the name with `urllib.parse.quote`, and parses the result HTML table.

### Req 3 — Retry without digits if no match ✅
**Issue says:** If no match, retry by removing numerical characters from the name
(e.g., "Frederic Pin 3200006" → "Frederic Pin").
**PR delivers:** `_name_without_digits()` helper strips digit sequences via
`re.sub(r"\d+", "", name)` and collapses whitespace. `_check_player()` calls it
on the second pass when the first returns `None`.

### Req 4 — Append VEKN ID to event file on match ✅
**Issue says:** Upon successful match, append the player's VEKN ID number to the
event file.
**PR delivers:** Sets `data["vekn_number"] = vekn_number` and calls `_save_yaml()`
to persist. Also corrects the `winner` field when the VEKN-found name differs,
which aligns with the issue title "Player Name Coercion" and is an appropriate
in-scope enhancement.

### Req 5 — Move unmatched to `errors/unknown_winner/` ✅
**Issue says:** If no match found, move the event to an `errors/unknown_winner`
directory.
**PR delivers:** Calls `_move_to_error(path, output_dir, "unknown_winner")` when
both lookup passes fail.

### Req 6 — Idempotent: only check files missing `vekn_number` ✅
**Issue says:** Apply validation only to events not already in the errors folder
and only when the VEKN number attribute is absent.
**PR delivers:**
- Files in `errors/` are already excluded by the validate command's collection
  logic (`not p.is_relative_to(errors_dir)` — pre-existing guard).
- Player check is gated with `data.get("vekn_number") is None`.

---

## Observations / Minor Notes

| # | Observation | Severity |
|---|---|---|
| 1 | **`_save_yaml()` doesn't round-trip formatting.** A fresh YAML instance is used, which may reflow comments or trailing newlines present in the original file. | Low |
| 2 | **Ambiguous results handled silently.** When multiple players match a search and none is an exact case-insensitive match, `fetch_player` returns `None` and logs at DEBUG level. The file is left as valid without a `vekn_number`, which is defensively correct but not documented in the `--check-players` help text. | Low |
| 3 | **Network errors during player check are non-fatal.** If `fetch_player` raises, `_check_player` logs a WARNING and returns `(False, False)`, counting the file as valid. Acceptable for a best-effort check. | Low |
| 4 | **`vekn_number` field added to `Tournament` model** as optional (`str \| None = None`) — only populated via the validate CLI, not during scraping. Consistent with how `fetch_event_date` is a post-scrape enrichment step. | Informational |
| 5 | **`validator.py` docstring updated** to document `unknown_winner`, keeping the module self-documenting. | Positive |
| 6 | **21 new tests added** (307 total, all passing). Tests cover `fetch_player` HTML parsing (single result, multiple results, exact match, no table, empty table) and the full `--check-players` CLI flow (found, coerced name, not found → moved, already has vekn_number → skipped, network error). | Positive |

---

## Overall Verdict

**PR #4 fully satisfies all six requirements from Issue #3.** No requirement gaps
were found. The minor notes above are code-quality observations, not blockers.

Suggested follow-ups before merging:
1. **(Low)** Consider using `ruamel.yaml` round-trip loading in `_save_yaml()` to
   preserve original file formatting (comments, ordering, blank lines).
2. **(Low)** Mention ambiguous-match behaviour in the `--check-players` help text
   or add a console output line so users understand why some files are skipped
   without a `vekn_number`.

---

## Files Changed in PR #4

| File | Change |
|---|---|
| `vtes_scraper/models.py` | +1 line: `vekn_number: str \| None = None` field on `Tournament` |
| `vtes_scraper/scraper.py` | +76 lines: `VEKN_PLAYERS_URL` constant + `fetch_player()` |
| `vtes_scraper/cli/validate.py` | +136 lines: `_save_yaml()`, `_name_without_digits()`, `_check_player()`, `--check-players` flag wiring |
| `vtes_scraper/validator.py` | +3 lines: docstring entry for `unknown_winner` error type |
| `tests/test_scraper.py` | +98 lines: unit tests for `fetch_player` |
| `tests/test_cli.py` | +210 lines: integration tests for `--check-players` CLI flow |
