from datetime import date
from pathlib import Path

from vtes_scraper_v1.models import CryptCard, Deck, LibrarySection, Tournament
from vtes_scraper_v1.output._common import _date_subdir

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _fmt_date(d: date) -> str:
    """Format a date as 'Month DDth YYYY', e.g. 'March 25th 2023'."""
    n = d.day
    suffix = _ORDINAL_SUFFIX.get(n % 10, "th") if not (11 <= n % 100 <= 13) else "th"
    return f"{d.strftime('%B')} {n}{suffix} {d.year}"


def _fmt_crypt_card(card: CryptCard) -> str:
    """Render one crypt card line with fixed-width column layout."""
    count_name = f"{card.count}x {card.name}"
    line = f"{count_name:<35}{card.capacity} {card.disciplines:<22}"
    if card.title:
        line += f"{card.title:<11}"
    else:
        line += " " * 11
    line += f"{card.clan}:{card.grouping}"
    if card.comment:
        line = f"{line} -- {card.comment}"
    return line


def _fmt_library_section(section: LibrarySection) -> str:
    """Render one library section (header + cards)."""
    lines: list[str] = [f"{section.name} ({section.count})"]
    for card in section.cards:
        entry = f"{card.count}x {card.name}"
        if card.comment:
            entry = f"{entry} -- {card.comment}"
        lines.append(entry)
    return "\n".join(lines)


def tournament_to_txt(tournament: Tournament) -> str:
    """Convert a Tournament object to the TWD TXT format string."""
    lines: list[str] = []

    # --- Mandatory header (7 lines) ---
    lines.append(tournament.name)
    lines.append(tournament.location)

    date_str = _fmt_date(tournament.date_start)
    if tournament.date_end:
        date_str = f"{date_str} -- {_fmt_date(tournament.date_end)}"
    lines.append(date_str)

    lines.append(tournament.rounds_format)
    lines.append(f"{tournament.players_count} players")
    lines.append(tournament.winner)
    lines.append(tournament.event_url)
    lines.append("")  # blank separator

    deck: Deck = tournament.deck

    # --- Optional deck metadata ---
    if deck.name:
        lines.append(f"Deck Name: {deck.name}")
    if deck.created_by and deck.created_by != tournament.winner:
        lines.append(f"Created by: {deck.created_by}")
    if deck.description:
        lines.append("Description:")
        lines.append(deck.description)
    if deck.name or deck.created_by or deck.description:
        lines.append("")  # blank line before crypt

    # --- Crypt block ---
    avg = f"{deck.crypt_avg:.2f}".rstrip("0").rstrip(".")
    lines.append(
        f"Crypt ({deck.crypt_count} cards, min={deck.crypt_min} max={deck.crypt_max} avg={avg})"
    )
    lines.append("----------------------------------------")
    for card in deck.crypt:
        lines.append(_fmt_crypt_card(card))
    lines.append("")

    # --- Library block ---
    lines.append(f"Library ({deck.library_count} cards)")
    lines.append("------------------")
    for section in deck.library_sections:
        lines.append(_fmt_library_section(section))
        lines.append("")

    return "\n".join(lines)


def write_tournament_txt(
    tournament: Tournament,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """
    Write a Tournament to {output_dir}/YYYY/MM/{event_id}.txt

    Raises:
        FileExistsError: if file exists and overwrite=False
        ValueError: if tournament has no event_id
    """
    dest = output_dir / _date_subdir(tournament)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / tournament.txt_filename

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {path}. Use --overwrite to replace."
        )

    path.write_text(tournament_to_txt(tournament), encoding="utf-8")
    return path
