# VEKN Scraping — Feasibility Evaluation

Evaluated against `docs/vekn-scraping-design.md` commit `d34be3e`.

---

## Overall Verdict

The design is coherent and implementable for roughly **80% of its surface
area**.  The remaining 20% is concentrated in four specific risks, detailed
below.  Nothing is a hard blocker, but two items need design adjustments
before implementation starts.

---

## Completeness

All expected layers are present: sourcing, classification, parsing,
enrichment, validation, output, and automation.  The JSON example is
concrete and the validation priority table is unambiguous.

**One structural gap**: Section 6.2 lists date extraction strategies but
gives none for `location`, `rounds_format`, or `players_count`, even
though §5.1 marks all three as source = Calendar.  Those fields need
their own extraction strategies, or the source column is misleading.

---

## Feasibility by Component

| Component | Feasibility | Risk | Notes |
|---|---|---|---|
| Forum scraping — fact-check mode | ✅ High | Low | Already implemented; small changes needed |
| Slow-check mode (thread replies) | ✅ High | Low | Straightforward extension |
| Calendar: name, dates, winner name | ✅ High | Low | Already implemented |
| Calendar: `winner_gw`, `winner_vp` | 🟡 Medium | Medium | Column names vary; some older events may lack GW/VP/Final columns |
| Calendar: `winner_vp_final` | 🟡 Medium | Medium | "Final" column absent for events with no seeded final — would trigger `unknown_winner` on legitimate records |
| Calendar: `location` | 🟡 Medium | Medium | Calendar has a location field but format varies; normalising to `"City, Country"` is non-trivial |
| Calendar: `rounds_format` | 🔴 Low | **High** | VEKN calendar does not reliably expose rounds format as a structured field; if unextractable the design flags every post `illegal_header` |
| Calendar: `players_count` | 🟡 Medium | Medium | No dedicated field; must be inferred from standings row count (registered players ≠ reporting players) |
| JSON output migration | ✅ High | Low | Mechanical rewrite of `vtes_scraper/output/`; YAML → JSON |
| Self-purging lenient parser | 🟡 Medium | Medium | Concept is sound; stopping condition and pruning trigger still vague |
| `validation_status` / `last_validation` | ✅ High | Low | Simple timestamp + enum field |
| Optional fields omitted | ✅ High | Low | One Pydantic config flag (`exclude_none=True`) |

---

## Specific Issues

### 1. `rounds_format` source = Calendar is likely wrong — **Critical**

The current codebase does not fetch this from the calendar, and it is
unlikely to be a structured field on the event page.  If the design
requires calendar confirmation for `rounds_format` and the calendar
cannot provide it, every record fails `illegal_header`.

**Recommendation**: keep `rounds_format` source as `Forum`, confirm only
via the regex constraint (`\d+R\+F`).

### 2. `winner_vp_final` mandatory on all events — **High risk**

The design requires `winner_vp_final` as mandatory.  If the calendar
standings have no "Final" column — which can happen for smaller events
or events with non-standard structure — the record is flagged
`unknown_winner`.  This would reject otherwise valid TWDs.

**Recommendation**: make `winner_vp_final` Optional with a dedicated
non-blocking flag, or fold it into `unknown_winner` only when a final
round is confirmed to exist.

### 3. `players_count` from calendar

Inferring player count from standings row count is not the same as the
registered count.  A player who dropped would not appear in standings.
This source may produce values inconsistent with the forum post, and
the discrepancy would trigger `too_few_players` on legitimate records.

**Recommendation**: keep `players_count` as source = Forum with a
calendar cross-check rather than a full override.

### 4. `validation_status = "None"` bootstrapping

A file freshly written by the scraper has `validation_status: "None"`
(never validated).  The validation job targets `last_edit >
last_validation` — but `last_validation` is mandatory, so its initial
value must be specified.

**Recommendation**: use sentinel `"1970-01-01T00:00:00Z"` at creation
time, or omit `last_validation` until the first validation run and
treat its absence as equivalent to "never validated".

### 5. Slow-check stopping condition underspecified

"Stops as soon as it has accumulated enough data" is not directly
implementable.  A precise stopping condition is needed.

**Recommendation**: stop when the header block and at least one crypt
card have been successfully parsed from any post in the thread.

### 6. Section 6.2 extraction gap

No extraction strategies are given for `location`, `rounds_format`, or
`players_count` from the calendar page.  If these are truly Calendar-
sourced they each need the same treatment as dates (ordered strategy
list with fallback).

### 7. Error files and re-validation scope

Section 9.2 says the weekly job targets "published JSON files".  It is
unclear whether files in `errors/` are also re-validated.  If not,
their `validation_status` stays `"Error"` forever even if the
underlying issue was fixed manually.

**Recommendation**: specify explicitly whether error files are included
in the weekly validation scope.

---

## Recommended Fixes Before Implementation

1. **`rounds_format`**: change source back to `Forum`; calendar
   cross-check is not reliably feasible.

2. **`winner_vp_final`**: make Optional; add `missing_final_vp` as a
   distinct non-blocking flag or fold into `unknown_winner` only when a
   final is confirmed.

3. **`players_count`**: keep as source = Forum with calendar
   cross-check rather than full override.

4. **`last_validation` initial value**: define the sentinel value or
   the omit-until-first-run policy.

5. **Slow-check stopping condition**: add a precise definition to
   §3.1 of the design document.

6. **Section 6.2**: fill in extraction strategies for `location` and
   `players_count`, or downgrade them to Forum source.

7. **Validation scope**: clarify whether `errors/` files are included
   in the weekly validation job.

---

## Spike

A feasibility spike is available on branch
`spike/calendar-fields-feasibility`.  Run it against the test event IDs
in `spike/test_events.txt` to empirically confirm which calendar fields
are extractable and at what success rate:

```bash
python spike/calendar_fields.py
# or target specific events:
python spike/calendar_fields.py --event-ids 8470 12012 13096
```

The spike probes `location`, `rounds_format`, `players_count`, `winner`,
`vekn_number`, `winner_gw`, `winner_vp`, and `winner_vp_final` for each
event and prints a per-event breakdown plus a summary success-rate matrix.
