from pathlib import Path

from vtes_scraper.models import CryptCard, Deck, LibrarySection, Tournament
from vtes_scraper.output._common import _date_subdir


def _fmt_crypt_card(card: CryptCard) -> str:
    """Render one crypt card line, matching the parser's expected column layout."""
    count_name = f"{card.count}x {card.name}"
    capa_disc = f"{card.capacity}  {card.disciplines}"

    parts = [count_name, capa_disc]
    if card.title:
        parts.append(card.title)
    parts.append(f"{card.clan}:{card.grouping}")

    line = "  ".join(parts)
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

    date_str = tournament.date_start.isoformat()
    if tournament.date_end:
        date_str = f"{date_str} -- {tournament.date_end.isoformat()}"
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
    lines.append("----------------------------------")
    for card in deck.crypt:
        lines.append(_fmt_crypt_card(card))
    lines.append("")

    # --- Library block ---
    lines.append(f"Library ({deck.library_count} cards)")
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
