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
`?limitstart=N` (0, 20, 40, …).

???? Is this URL stable or should it be treated as a configurable parameter?

### 1.2 VEKN Event Calendar

The official event calendar lives at:

```
https://www.vekn.net/event-calendar/event/{event_id}
```

It is the authoritative source for event metadata (name, date, standings).

### 1.3 VEKN Player Registry

Player lookup (to resolve VEKN member numbers) is done via:

```
https://www.vekn.net/event-calendar/players
```

???? Is this endpoint stable and publicly queryable without authentication?

---

## 2. Forum Topic Classification

Each topic on the forum carries a **Kunena topic icon** that signals its
processing status. The scraper uses that icon to decide what to do with the
post.

| Icon       | Meaning                                         | Action                                     |
|------------|-------------------------------------------------|--------------------------------------------|
| `default`  | TWD report not yet processed                    | Scrape and validate normally               |
| `solved`   | TWD already added to the official archive       | Scrape and validate normally               |
| `merged`   | Changes have been requested by the maintainer   | Scrape but store separately for review     |
| `idea`     | Informational or meta post (not a TWD report)   | Skip entirely                              |

Icons are detected from `<img>` tags inside the topic row. The `src` attribute
contains `media/kunena/topic_icons/default/user/{icon}.png`.

???? Are these four icons exhaustive? Can new icons appear in the future that
the scraper should handle?

???? For topics with no detectable icon, should the scraper treat them as
`default` (scrape) or `idea` (skip)?

Some topics must always be skipped regardless of icon (e.g. the "how to
report a TWD" pinned thread). These are identified by their URL slug.

???? What is the complete list of slugs to skip? Should this list be
maintained in code or in a config file?

---

## 3. Scraping Strategy

### 3.1 Scrape Modes

The scraper operates in two modes.

**Fact-check mode** (default — automated jobs and CLI)

- Reads only the **first post** of each forum thread (the original TWD report).
- After parsing, every non-deck field is **confirmed** against the VEKN event
  calendar before the record is accepted (see Section 6).
- A field that cannot be confirmed is flagged as unconfirmed and routed to the
  appropriate error directory.

**Slow-check mode** (CLI only, opt-in flag)

- Reads **all posts** in the thread: first post and every reply.
- Intended for topics where the original report was corrected or supplemented
  in the comments (e.g. missing cards, corrected player count, updated deck
  link).
- ???? What is the merge strategy when a reply contradicts the first post?
  (Last confirmed value wins? Manual review required?)
- ???? Is the slow-check only useful during the initial ingestion of a topic,
  or should it also be used during re-validation?

### 3.2 Page Range

The scraper iterates forum index pages. Each page lists 20 topics.

- Default scope: the most recent pages (???? how many by default?).
- Full scrape: all pages from 0 to the last available.
- Both `start_page` and `last_page` are 0-indexed; `last_page` is inclusive.

### 3.3 Request Rate

The scraper must identify itself and be respectful of the server:

- **User-Agent**: must include the project repository URL and a contact point.
- **Delay between requests**: ???? What is the agreed delay? (Currently 1.5 s.)
- The scraper must honour `robots.txt` and VEKN forum terms of service.

### 3.4 Duplicate Handling

If a YAML file for a given `event_id` already exists on disk, the scraper
**skips** it by default. An `--overwrite` flag allows re-scraping.

---

## 4. TWD Post Format

The first post of each forum thread contains the TWD report. The scraper
extracts its raw text and passes it to the parser.

### 4.1 Header Block

The header describes the tournament. Fields appear in a fixed order:

```
{tournament name}
{location}
{date}
{rounds format}
{players count}
{winner name}
{VEKN event URL}
```

A lenient fallback parser handles posts where fields are labelled (e.g.
`Winner: Alice`) or appear out of order.

???? What labelling conventions are accepted in the lenient parser? Should
we maintain an exhaustive list of recognised prefixes?

### 4.2 Deck Block

The deck follows immediately after the header. It contains:

1. A **crypt section** opened by a header of the form:
   ```
   Crypt ({N} cards, min {min}, max {max}, avg {avg})
   ```
2. A **library section** with named subsections (Master, Action, Reaction, …).

Each crypt card line:
```
{count}x {Card Name} {capacity} {disciplines} {clan}:{grouping}
```

Each library card line:
```
{count}x {Card Name}
```

???? Are there known formatting variants in the wild that the parser must
handle (e.g. count without `x`, disciplines in different order)?

---

## 5. Parsed Data Model

### 5.1 Tournament Fields

The **Source** column indicates where the value originates.
`Forum` = parsed from the forum post.
`Calendar` = fetched from the VEKN event calendar (authoritative; overwrites the forum value).

| Field            | Type           | Status    | Source     | Notes                                             |
|------------------|----------------|-----------|------------|---------------------------------------------------|
| `name`           | `str`          | Mandatory | Calendar   | Event name — calendar value overrides forum       |
| `location`       | `str`          | Mandatory | Forum      | `"City, Country"` or `"Online"`                   |
| `date_start`     | `date`         | Mandatory | Calendar   | Tournament start date — must match calendar       |
| `date_end`       | `date`         | Optional  | Calendar   | Only for multi-day events                         |
| `rounds_format`  | `str`          | Mandatory | Forum      | Must match `\d+R\+F` (e.g. `"3R+F"`)             |
| `players_count`  | `int`          | Mandatory | Forum      | Minimum ???? (currently 12)                       |
| `winner`         | `str`          | Mandatory | Calendar   | Winner's name — must match calendar standings     |
| `vekn_number`    | `int`          | Mandatory | Calendar   | Winner's VEKN membership number from standings    |
| `winner_gw`      | `int`          | Mandatory | Calendar   | Winner's Game Wins total from official standings  |
| `winner_vp`      | `float`        | Mandatory | Calendar   | Winner's Victory Points total from standings      |
| `event_url`      | `str`          | Mandatory | Forum      | Canonical VEKN calendar URL                       |
| `event_id`       | `int`          | Derived   | —          | Extracted from `event_url`                        |
| `forum_post_url` | `str`          | Mandatory | —          | Source forum thread URL (for traceability)        |
| `last_edit`      | `datetime`     | Mandatory | —          | UTC timestamp of the last write to the JSON file  |

???? Is `forum_post_url` required for publication to the archive, or only for
internal traceability in this repository?

???? `winner_gw` and `winner_vp` come from the final standings table. Should
they reflect the **final round only** or the **cumulative tournament total**?

`last_edit` is set by the scraper (or validator) each time the file is
written or updated. It is not sourced from the forum or the calendar.

### 5.2 Deck Fields

| Field               | Type              | Status    | Notes                              |
|---------------------|-------------------|-----------|------------------------------------|
| `name`              | `str`             | Optional  | Deck name                          |
| `created_by`        | `str`             | Optional  | Only when different from winner    |
| `description`       | `str`             | Optional  | Free-form notes / strategy text    |
| `crypt_count`       | `int`             | Mandatory | Total crypt cards                  |
| `crypt_min`         | `int`             | Mandatory | Minimum capacity in crypt          |
| `crypt_max`         | `int`             | Mandatory | Maximum capacity in crypt          |
| `crypt_avg`         | `float`           | Mandatory | Average capacity in crypt          |
| `crypt`             | `list[CryptCard]` | Mandatory | Non-empty                          |
| `library_count`     | `int`             | Mandatory | Total library cards                |
| `library_sections`  | `list[Section]`   | Mandatory | Non-empty                          |

### 5.3 Date Formats Accepted by the Parser

- `YYYY-MM-DD` — ISO 8601
- `DD/MM/YYYY`
- `Month DD YYYY` / `DD Month YYYY` (full month name)
- `Mon DD YYYY` / `DD Mon YYYY` (abbreviated month name)
- Ordinal suffixes (`1st`, `2nd`, `3rd`, `4th` …) are stripped before parsing.

???? Are there additional date formats observed in real posts that need support?

---

## 6. Calendar Confirmation

The VEKN event calendar is the **authoritative source** for all non-deck
fields. The forum post is treated as a raw input only; every field that the
calendar can supply **must** be confirmed or overwritten by the calendar value.
A record with any unconfirmed mandatory calendar field is invalid.

The deck list itself (crypt and library) is the one block that comes
exclusively from the forum post and is not cross-checked against the calendar.

### 6.1 Event Name

Fetched from the VEKN event calendar page. Extraction strategies, in order:

1. JSON-LD structured data (`name` field).
2. `<h1>` element text.

The calendar value replaces whatever name was in the forum post.

### 6.2 Event Dates

Fetched from the VEKN event calendar page. Extraction strategies, in order:

1. JSON-LD structured data (`startDate` / `endDate` fields).
2. `<time datetime="...">` element.
3. Event date `<div>` text.
4. Regex scan for date-like strings.

If the calendar date differs from the forum date, the calendar value wins.
If the calendar provides no date at all, the record is flagged `incoherent_date`.

### 6.3 Winner Name, VEKN Number, and Score

Fetched from the official standings table on the event calendar page.
The scraper identifies the first-place row in a table with headers such as
`Pos.`, `Rank`, `#`, or `Player`, then extracts:

- `winner` — player name as it appears in the standings.
- `vekn_number` — VEKN membership number from the standings row.
- `winner_gw` — Game Wins total from the standings row.
- `winner_vp` — Victory Points total from the standings row.

All four fields are mandatory. If any cannot be read from the standings table
the record is flagged `unconfirmed_winner`.

???? What should happen when the winner name in the forum post does not match
the name in the official standings (e.g. spelling difference or transliteration)?
Should the scraper accept the calendar name unconditionally, or raise a flag?

???? If the standings table has no GW or VP column (only rank and player name),
how should the scraper handle it?

### 6.4 Card Data (krcg)

Crypt and library cards are validated and enriched using the **krcg** card
database:

- Crypt cards: `capacity`, `disciplines`, `title`, `clan`, `grouping` are
  updated from the database. `count` and `name` are always preserved from the
  scraped data.
- Library cards: each card's section is validated. Misassigned cards are moved
  to the correct section.

When a vampire exists in multiple groupings, the version whose group is
consistent with the rest of the crypt is selected (see grouping rules below).

---

## 7. Validation Rules

Validation runs after parsing and enrichment. Each rule produces a named error
type. When multiple errors are present, the **first** one (in priority order)
determines the output directory.

| Priority | Error type          | Condition                                                                |
|----------|---------------------|--------------------------------------------------------------------------|
| 1        | `illegal_header`    | Any mandatory tournament field is absent or blank                        |
| 2        | `unconfirmed_winner`| `winner` is absent, or `vekn_number` is absent or `None`                |
| 3        | `limited_format`    | Tournament `name` contains the word `"Limited"` (case-insensitive)       |
| 4        | `illegal_crypt`     | Crypt is empty, grouping rule violated, or `crypt_count` is inconsistent |
| 5        | `illegal_library`   | Library is empty, section count is wrong, or `library_count` is wrong    |
| 6        | `too_few_players`   | `players_count` is present but below the minimum                         |
| 7        | `incoherent_date`   | `date_start` does not match the official calendar date                   |

### 7.1 Grouping Rule

All crypt cards with an integer grouping must span **at most two consecutive
integers** (e.g. G5 and G6 are legal; G4, G5, G6 is not). Cards with
grouping `ANY` are excluded from this check.

???? Is this rule a VEKN tournament regulation or a TWD archive convention?
Does it apply to all formats (Standard, Limited, …)?

### 7.2 Player Count Minimum

???? What is the official VEKN minimum for a tournament to qualify as a
rating event? (Currently assumed to be 12.)

### 7.3 Limited Format

Tournaments whose name contains `"Limited"` are flagged as `limited_format`
and not published.

???? Are there other keywords that indicate a non-standard format that should
be excluded (e.g. `"Draft"`, `"Sealed"`)?

---

## 8. Output

### 8.1 File Naming and Directory Layout

Each tournament produces one JSON file named `{event_id}.json`. Files are
stored under:

```
twds/
├── YYYY/
│   └── MM/
│       └── {event_id}.json       ← Valid tournaments
├── errors/
│   ├── illegal_header/
│   ├── unconfirmed_winner/
│   ├── limited_format/
│   ├── illegal_crypt/
│   ├── illegal_library/
│   ├── too_few_players/
│   └── incoherent_date/
└── changes_required/             ← Posts marked with the "merged" icon
    └── {event_id}.json
```

`YYYY/MM` is derived from `date_start`.

???? Should `changes_required/` files also be organised by date, or does a
flat directory suffice?

### 8.2 JSON Structure

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
  "event_url": "https://www.vekn.net/event-calendar/event/9999",
  "event_id": 9999,
  "forum_post_url": "https://www.vekn.net/forum/event-reports-and-twd/12345-example",
  "last_edit": "2026-04-20T14:32:00Z",
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

???? Should `date_end`, `created_by`, and `description` appear in the JSON
when absent (as `null`) or be omitted entirely?

---

## 9. Automation

### 9.1 Scheduled Scrape

A daily job scrapes the most recent forum pages, validates new posts, and
commits resulting JSON files.

???? What page range should the daily job target? How many pages back is
sufficient to catch all new posts within 24 hours?

### 9.2 Scheduled Validation

A weekly job re-validates published JSON files and updates card data from krcg.
Each file that is updated receives a fresh `last_edit` timestamp.

???? Should the weekly job re-validate only a recent subset, or the full
archive? What is the acceptable run time?

### 9.3 Scheduled Publication

A weekly job publishes validated JSON files to the shared TWD archive as a
pull request.

???? Should pre-2020 tournaments be included in publication by default?

---

## 10. Open Questions Summary

For convenience, all `????` items grouped by theme:

**Sources**
- Is the forum URL stable or configurable?

**Icon classification**
- Are the four icons exhaustive?
- How should topics with no detectable icon be treated?
- Should the skip-slug list be in code or config?

**Scrape modes**
- In slow-check mode, what is the merge strategy when a reply contradicts the
  first post?
- Is slow-check useful during re-validation, or only on first ingestion?
- Page range for the default (fact-check) scrape?

**Parsing**
- What labelling prefixes does the lenient header parser recognise?
- What crypt/library formatting variants must be handled?
- Are there additional date formats needed?

**Calendar confirmation**
- When the winner name in the post and in the standings differ, does the
  calendar name win unconditionally, or is a flag raised?
- If the standings table has no GW/VP column, how should the scraper handle it?
- Do `winner_gw` and `winner_vp` reflect the final round only or the
  cumulative tournament total?

**Validation rules**
- Is the grouping rule a VEKN regulation or an archive convention?
- What is the official minimum player count?
- Are there other format keywords to exclude beyond `"Limited"`?

**Output**
- Is `forum_post_url` required for publication or only for internal traceability?
- Should `changes_required/` be organised by date?
- Should optional fields appear as `null` or be omitted in the JSON?

**Automation**
- Full vs. partial re-validation in the weekly job?
- Should pre-2020 tournaments be published by default?
