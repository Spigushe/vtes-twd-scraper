# VEKN Scraping — Design Document

## Goal

Automatically collect Tournament Winning Decks (TWD) from the VEKN forum,
validate them against official data, and produce structured JSON files ready
for publication to the shared TWD archive.

---

## 1. Data Source

### 1.1 Forum

All TWD reports are posted by players to a single forum section:

```
https://www.vekn.net/forum/event-reports-and-twd
```

The forum software is **Kunena**. Topics are paginated 20 per page via
`?limitstart=N` (0, 20, 40, …). This URL is stable.

### 1.2 VEKN Event Calendar

The official event calendar lives at:

```
https://www.vekn.net/event-calendar/event/{event_id}
```

It is the authoritative source for all non-deck tournament data.

### 1.3 VEKN Player Registry

```
https://www.vekn.net/event-calendar/players
```

This endpoint is stable, public, and requires no authentication.

---

## 2. Forum Topic Classification

Each topic carries a **Kunena topic icon** that signals its processing status.

| Icon      | Meaning                                       | Action                                 |
|-----------|-----------------------------------------------|----------------------------------------|
| `default` | TWD report not yet processed                  | Scrape and validate normally           |
| `solved`  | TWD already added to the official archive     | Scrape and validate normally           |
| `merged`  | Changes have been requested by the maintainer | Scrape but store separately for review |
| `idea`    | Informational or meta post (not a TWD report) | Skip entirely                          |

Icons are detected from `<img>` tags inside the topic row. The `src` attribute
contains `media/kunena/topic_icons/default/user/{icon}.png`.

These four icons are exhaustive as of the current VEKN forum. If new icons
appear in the future, the scraper code must be updated to handle them.

Topics with **no detectable icon** are treated as `idea` and skipped.

The following thread slugs are always skipped regardless of icon. They are
pinned meta/admin threads at the top of the first page:

- `2119-how-to-report-a-twd`
- `79623-contributing-to-the-twd`
- `63835-howto-use-the-archon-correctly`

---

## 3. Scraping Strategy

### 3.1 Scrape Modes

The scraper operates in two modes.

**Fact-check mode** (default — automated jobs and CLI)

- Reads only the **first post** of each forum thread (the original TWD report).
- After parsing, every non-deck field is **confirmed** against the VEKN event
  calendar before the record is accepted (see Section 6).
- A field that cannot be confirmed is flagged and routed to the appropriate
  error directory.

**Slow-check mode** (CLI only, opt-in flag — initial ingestion only)

- Reads the first post and **all replies** in the thread.
- Intended for topics where the original report was corrected or supplemented
  in the comments (e.g. missing cards, corrected player count, updated link).
- The scraper reads posts in order and stops as soon as it has accumulated
  enough data to build a complete TWD record.
- This mode is only for initial ingestion. Re-validation always uses
  fact-check mode.

### 3.2 Page Range

The scraper iterates forum index pages (20 topics per page, 0-indexed).

- **Default scope**: the 2 most recent pages (pages 0 and 1, i.e. 40 topics).
- **Full scrape**: all pages from 0 to the last available.
- Both `--start-page` and `--last-page` are 0-indexed; `--last-page` is
  inclusive.

### 3.3 Request Rate

- **User-Agent**: must include the project repository URL and a contact point.
- **Delay between requests**: up to 2 seconds between consecutive requests.
- The scraper must honour `robots.txt` and VEKN forum terms of service.

### 3.4 Duplicate Handling

If a JSON file for a given `event_id` already exists on disk, the scraper
**skips** it by default. An `--overwrite` flag allows re-scraping.

---

## 4. TWD Post Format

### 4.1 Header Block

The header describes the tournament. The canonical format is **7 lines in
fixed order**, followed by optional extra fields:

```
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

-- 5VP in final        ← retrieved from event calendar, not parsed from post

Deck Name : Eyes of the Insane
Created by: Bobby Lemon
Description:
A great deck that...
```

The `-- N VP in final` line is **not** parsed from the forum post. The
winner's VP in the final is fetched from the VEKN event calendar standings
(see Section 6.3).

A lenient fallback parser handles posts where fields are labelled (e.g.
`Winner: Ravel Zorzal`) or appear out of order. As scraping progresses the
parser accumulates a candidate list of observed label-to-field mappings.
Candidates that are never confirmed by a successful parse are pruned (self-
purging), provided the overhead of maintaining the list stays acceptable.

### 4.2 Deck Block

The deck follows the header. It contains:

1. A **crypt section** opened by a header of the form:
   ```
   Crypt ({N} cards, min {min}, max {max}, avg {avg})
   ```
2. A **library section** with named subsections (Master, Action, Reaction, …).

Each crypt card line uses fixed-width columns:

```
{Qty}x {Name:<X}  {Capacity}  {Disciplines:<Y}  [{title:<Z}]  {Clan}:{Grouping}
```

Example:

```
2x Nathan Turner      4  PRO ani                 Gangrel:6
2x Indira             3  PRO                     Gangrel:6
1x Casey Snyder       6  PRO ani cel for  baron  Gangrel:6
1x Martina Srnankova  6  FOR PRO ani             Gangrel:6
1x Dario Ziggler      5  FOR ani pro tha         Gangrel:6
1x Kamile Paukstys    5  PRO ani for             Gangrel:6
1x Hanna Nokelainen   4  ani for pro             Gangrel:6
1x Joaquín de Cádiz   3  for pro                 Gangrel:6
1x Joseph Fischer     3  PRO                     Gangrel antitribu:5
1x Ruslan Fedorenko   2  pro                     Gangrel:6
```

The `x` after the quantity may be absent (e.g. `2 Nathan Turner …`). Both
forms must be accepted. Discipline order is normalised by the krcg library
after ingestion and does not need to be enforced during parsing.

Each library card line:

```
{count}x {Card Name}  -- {optional comment}
```

---

## 5. Parsed Data Model

### 5.1 Tournament Fields

`Calendar` = value fetched from the VEKN event calendar (authoritative —
overwrites the forum value). `Forum` = parsed from the forum post only.

| Field              | Type       | Status    | Source   | Notes                                                        |
|--------------------|------------|-----------|----------|--------------------------------------------------------------|
| `name`             | `str`      | Mandatory | Calendar | Event name — calendar value overrides forum                  |
| `location`         | `str`      | Mandatory | Calendar | `"City, Country"` or `"Online"` — calendar overrides forum   |
| `date_start`       | `date`     | Mandatory | Calendar | Tournament start date — calendar overrides forum             |
| `date_end`         | `date`     | Optional  | Calendar | Only for multi-day events                                    |
| `rounds_format`    | `str`      | Mandatory | Calendar | Must match `\d+R\+F` (e.g. `"3R+F"`) — calendar overrides   |
| `players_count`    | `int`      | Mandatory | Calendar | No VEKN minimum; below 12 triggers `too_few_players` error   |
| `winner`           | `str`      | Mandatory | Calendar | Calendar standings name overrides forum post                 |
| `vekn_number`      | `int`      | Mandatory | Calendar | Winner's VEKN membership number from standings               |
| `winner_gw`        | `int`      | Mandatory | Calendar | Winner's Game Wins in rounds (before final)                  |
| `winner_vp`        | `float`    | Mandatory | Calendar | Winner's Victory Points in rounds (before final)             |
| `winner_vp_final`  | `float`    | Mandatory | Calendar | Winner's Victory Points in the final round                   |
| `event_url`        | `str`      | Mandatory | Forum    | Canonical VEKN calendar URL                                  |
| `event_id`         | `int`      | Derived   | —        | Extracted from `event_url`                                   |
| `forum_post_url`   | `str`      | Mandatory | —        | Required for publication and validation traceability         |
| `last_edit`          | `datetime` | Mandatory | —        | UTC timestamp set on every write or update                   |
| `last_validation`    | `datetime` | Mandatory | —        | UTC timestamp set by the validation job after each run       |
| `validation_status`  | `str`      | Mandatory | —        | Outcome of the last validation run: `None`, `Error`, `Pass`  |

`last_edit`, `last_validation`, and `validation_status` are internal fields.
The validation job targets files where `last_edit > last_validation`, then
sets `last_validation` and `validation_status` on each processed file.

### 5.2 Winner Score Format

The winner's score is stored in three separate fields:

| Example standings row | `winner_gw` | `winner_vp` | `winner_vp_final` |
|-----------------------|-------------|-------------|-------------------|
| 1 GW · 6.0 VP · Final 3.0 VP | `1` | `6.0` | `3.0` |

Display form (used in publication output): `1GW6.0 + 3VP in finals`.

### 5.3 Deck Fields

| Field              | Type              | Status    | Notes                           |
|--------------------|-------------------|-----------|---------------------------------|
| `name`             | `str`             | Optional  | Deck name                       |
| `created_by`       | `str`             | Optional  | Only when different from winner |
| `description`      | `str`             | Optional  | Free-form notes / strategy      |
| `crypt_count`      | `int`             | Mandatory | Total crypt cards               |
| `crypt_min`        | `int`             | Mandatory | Minimum capacity in crypt       |
| `crypt_max`        | `int`             | Mandatory | Maximum capacity in crypt       |
| `crypt_avg`        | `float`           | Mandatory | Average capacity in crypt       |
| `crypt`            | `list[CryptCard]` | Mandatory | Non-empty                       |
| `library_count`    | `int`             | Mandatory | Total library cards             |
| `library_sections` | `list[Section]`   | Mandatory | Non-empty                       |

### 5.4 Date Formats Accepted by the Parser

- `YYYY-MM-DD` — ISO 8601
- `DD/MM/YYYY`
- `Month DD YYYY` / `DD Month YYYY` (full month name)
- `Mon DD YYYY` / `DD Mon YYYY` (abbreviated month name)
- Ordinal suffixes (`1st`, `2nd`, `3rd`, `4th` …) are stripped before parsing.

No additional formats are known to appear in real posts.

---

## 6. Calendar Confirmation

The VEKN event calendar is the **authoritative source** for all non-deck
fields. The forum post is raw input only. Every mandatory calendar field that
cannot be confirmed produces a validation error.

The deck list (crypt and library) comes exclusively from the forum post and
is not cross-checked against the calendar.

### 6.1 Event Name

Extraction strategies, in order:

1. JSON-LD structured data (`name` field).
2. `<h1>` element text.

The calendar value replaces the forum post name unconditionally.

### 6.2 Location, Dates, Rounds Format, Player Count

These fields are fetched from the VEKN event calendar and override the forum
post values. Date extraction strategies:

1. JSON-LD structured data (`startDate` / `endDate` fields).
2. `<time datetime="...">` element.
3. Event date `<div>` text.
4. Regex scan for date-like strings.

If the calendar provides no date, the record is flagged `incoherent_date`.

### 6.3 Winner Name, VEKN Number, and Score

Extracted from the official standings table (first-place row). The scraper
looks for a table with headers such as `Pos.`, `Rank`, `#`, or `Player`.

Fields extracted:

| JSON field        | Standings column |
|-------------------|-----------------|
| `winner`          | Player name     |
| `vekn_number`     | VEKN number     |
| `winner_gw`       | GW              |
| `winner_vp`       | VP              |
| `winner_vp_final` | Final           |

The calendar winner name overrides the forum post value unconditionally.

If the standings table is missing or any of the five fields cannot be read
(including missing GW, VP, or Final columns), the record is flagged
`unknown_winner`.

### 6.4 Card Data (krcg)

Crypt and library cards are validated and enriched using the **krcg** card
database:

- Crypt cards: `capacity`, `disciplines`, `title`, `clan`, `grouping` are
  updated from the database. `count` and `name` are always preserved.
- Library cards: each card's section is validated; misassigned cards are moved
  to the correct section.

When a vampire exists in multiple groupings, the version consistent with the
rest of the crypt is selected (see grouping rules below).

---

## 7. Validation Rules

Validation runs after calendar confirmation and krcg enrichment. When multiple
errors are present, the **first** one (priority order) determines the output
directory.

| Priority | Error type           | Condition                                                                 |
|----------|----------------------|---------------------------------------------------------------------------|
| 1        | `illegal_header`     | Any mandatory tournament field is absent or blank                         |
| 2        | `unknown_winner` | `winner`, `vekn_number`, `winner_gw`, `winner_vp`, or `winner_vp_final` missing |
| 3        | `limited_format`     | Tournament name contains `"Limited"`, `"Draft"`, or `"Sealed"` (case-insensitive) |
| 4        | `illegal_crypt`      | Crypt is empty, grouping rule violated, or `crypt_count` inconsistent     |
| 5        | `illegal_library`    | Library is empty, a section count is wrong, or `library_count` wrong     |
| 6        | `too_few_players`    | `players_count` is present and below 12                                   |
| 7        | `incoherent_date`    | `date_start` does not match the official calendar date                    |

### 7.1 Grouping Rule

All crypt cards with an integer grouping must span **at most two consecutive
integers** (e.g. G5 and G6 are legal; G4, G5, G6 is not). Cards with
grouping `ANY` are excluded from this check.

This is an actual VEKN tournament regulation. Violations are flagged as
`illegal_crypt`.

### 7.2 Player Count

There is no official VEKN minimum for a tournament to qualify as a rating
event. However, a `players_count` below 12 triggers the `too_few_players`
error because the multi-deck format applies below that threshold.

### 7.3 Non-Standard Formats

Tournaments whose name contains any of the following keywords are flagged as
`limited_format` and not published:

- `Limited`
- `Draft`
- `Sealed`

---

## 8. Output

### 8.1 File Naming and Directory Layout

Each tournament produces one JSON file named `{event_id}.json`.

```
twds/
├── YYYY/
│   └── MM/
│       └── {event_id}.json       ← Valid tournaments (YYYY/MM from date_start)
├── errors/
│   ├── illegal_header/
│   ├── unknown_winner/
│   ├── limited_format/
│   ├── illegal_crypt/
│   ├── illegal_library/
│   ├── too_few_players/
│   └── incoherent_date/
└── changes_required/
    └── YYYY/
        └── {event_id}.json       ← Posts marked with the "merged" icon, by year
```

### 8.2 JSON Structure

Optional fields are omitted from the JSON when absent, provided the schema
validator can still distinguish a missing optional field from an invalid record.

```json
{
  "name": "Example Championship",
  "location": "Paris, France",
  "date_start": "2026-03-15",
  "rounds_format": "3R+F",
  "players_count": 20,
  "winner": "Alice Dupont",
  "vekn_number": 1234567,
  "winner_gw": 2,
  "winner_vp": 8.5,
  "winner_vp_final": 3.0,
  "event_url": "https://www.vekn.net/event-calendar/event/9999",
  "event_id": 9999,
  "forum_post_url": "https://www.vekn.net/forum/event-reports-and-twd/12345-example",
  "last_edit": "2026-04-20T14:32:00Z",
  "last_validation": "2026-04-20T14:32:00Z",
  "validation_status": "Pass",
  "deck": {
    "name": "Nocturnal Visitor",
    "crypt_count": 12,
    "crypt_min": 4,
    "crypt_max": 9,
    "crypt_avg": 6.5,
    "crypt": [
      {
        "count": 2,
        "name": "Eze",
        "capacity": 9,
        "disciplines": "ANI FOR PRO",
        "clan": "Gangrel",
        "grouping": 6
      }
    ],
    "library_count": 90,
    "library_sections": [
      {
        "name": "Master",
        "count": 15,
        "cards": [
          { "count": 1, "name": "Anarch Free Press, The" }
        ]
      }
    ]
  }
}
```

---

## 9. Automation

### 9.1 Scheduled Scrape

A daily job runs fact-check mode on the 2 most recent pages (40 topics),
validates new posts, and commits resulting JSON files.

### 9.2 Scheduled Validation

A weekly job re-validates published JSON files and updates card data from
krcg. It targets only files where `last_edit > last_validation`, then updates
`last_validation` on each processed file regardless of outcome.

### 9.3 Scheduled Publication

A weekly job publishes validated JSON files to the shared TWD archive as a
pull request. Pre-2020 tournaments are excluded from publication by default.

---

## 10. Open Questions

No open questions remain.
