"""Strict and lenient header parsers for TWD posts."""

import re

from vtes_scraper.parser._helpers import (
    CREATED_BY_RE,
    DECK_NAME_RE,
    DESCRIPTION_RE,
    PLAYERS_RE,
    ROUNDS_RE,
    WINNER_LABEL_RE,
    _extract_vekn_url,
    _normalize_rounds,
    _split_date,
)


def _parse_header_strict(lines: list[str]) -> dict:
    non_blank = [line.strip() for line in lines if line.strip()]
    if len(non_blank) < 7:
        raise ValueError(f"Strict: need 7 non-blank lines, got {len(non_blank)}")

    name, location, raw_date, rounds_raw, players_raw, winner, event_url = non_blank[:7]

    if not PLAYERS_RE.search(players_raw):
        raise ValueError(f"Strict: line 4 not player count: {players_raw!r}")
    if not ROUNDS_RE.search(rounds_raw):
        raise ValueError(f"Strict: line 3 not rounds format: {rounds_raw!r}")
    if "vekn.net" not in event_url:
        raise ValueError(f"Strict: line 6 not vekn URL: {event_url!r}")

    date_start, date_end = _split_date(raw_date)

    vp_comment: str | None = None
    for line in non_blank[7:]:
        if line.startswith("-") or re.search(r"vp|gw|final", line, re.IGNORECASE):
            vp_comment = line.lstrip("- ").strip()
            break

    return dict(
        name=name,
        location=location,
        date_start=date_start,
        date_end=date_end,
        rounds_format=_normalize_rounds(rounds_raw),
        players_count=players_raw,
        winner=winner,
        event_url=_extract_vekn_url(event_url) or event_url,
        vp_comment=vp_comment,
    )


def _parse_header_lenient(lines: list[str]) -> dict:
    non_blank = [line.strip() for line in lines if line.strip()]

    name = location = date_start = date_end = None
    rounds_format = players_count = winner = event_url = vp_comment = None
    unlabeled: list[str] = []

    for line in non_blank:
        # Rounds
        if ROUNDS_RE.search(line) and not PLAYERS_RE.search(line):
            rounds_format = _normalize_rounds(line)
            continue
        # Players (short line only — avoids matching "X players won with...")
        pm = PLAYERS_RE.search(line)
        if pm and len(line) < 30:
            players_count = line
            continue
        # Winner labeled
        wm = WINNER_LABEL_RE.match(line)
        if wm:
            winner = wm.group(1).strip()
            continue
        # VEKN URL
        url = _extract_vekn_url(line)
        if url:
            if event_url is None:
                event_url = url
            continue
        # VP/GW comment
        if re.match(r"^[-\d]", line) and re.search(r"vp|gw|final", line, re.IGNORECASE):
            vp_comment = line.lstrip("- ").strip()
            continue
        # Stop at deck metadata
        if (
            DECK_NAME_RE.match(line)
            or CREATED_BY_RE.match(line)
            or DESCRIPTION_RE.match(line)
        ):
            break

        unlabeled.append(line)

    if unlabeled:
        name = unlabeled[0]
    if len(unlabeled) >= 2:
        location = unlabeled[1]
    if len(unlabeled) >= 3:
        date_start, date_end = _split_date(unlabeled[2])
    if winner is None and len(unlabeled) >= 4:
        winner = unlabeled[3]

    missing = [
        f
        for f, v in [
            ("name", name),
            ("location", location),
            ("date_start", date_start),
            ("rounds_format", rounds_format),
            ("players_count", players_count),
            ("winner", winner),
            ("event_url", event_url),
        ]
        if not v
    ]
    if missing:
        raise ValueError(f"Lenient parse: missing fields {missing}")

    return dict(
        name=name,
        location=location,
        date_start=date_start,
        date_end=date_end,
        rounds_format=rounds_format,
        players_count=players_count,
        winner=winner,
        event_url=event_url,
        vp_comment=vp_comment,
    )
