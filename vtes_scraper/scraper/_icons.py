"""Topic icon detection for Kunena forum threads."""

from bs4 import Tag

# ---------------------------------------------------------------------------
# Topic icon types
# ---------------------------------------------------------------------------
# Icons are served from https://www.vekn.net/media/kunena/topic_icons/default/user/
# Each constant's value matches the icon filename stem.

#: Changes have been requested — scrape and store in changes_required/.
ICON_MERGED = "merged"

#: Deck already added to the official TWD — scrape and store as usual.
ICON_SOLVED = "solved"

#: Informational post only — do not scrape.
ICON_IDEA = "idea"

#: Not yet in TWD — scrape and store as usual.
ICON_DEFAULT = "default"


# Base URL prefix for Kunena user topic icons on vekn.net
_ICON_BASE = "media/kunena/topic_icons/default/user/"

# Ordered mapping: icon filename stem → constant.
_ICON_SRC_MAP: tuple[tuple[str, str], ...] = (
    ("merged", ICON_MERGED),
    ("solved", ICON_SOLVED),
    ("idea", ICON_IDEA),
    ("default", ICON_DEFAULT),
)


def detect_topic_icon(link_tag: Tag) -> str | None:
    """
    Given a topic ``<a>`` tag from the forum index, detect its icon type.

    Walks up the DOM tree to find the nearest row container (``<tr>``,
    ``<li>``, or ``<div>`` whose class hints at a topic row), then looks
    for an ``<img>`` whose ``src`` contains the Kunena user-icon path.

    Returns one of :data:`ICON_MERGED`, :data:`ICON_SOLVED`,
    :data:`ICON_IDEA`, :data:`ICON_DEFAULT`, or ``None`` if no
    recognised icon is found.
    """
    # Walk up to find the row container
    row: Tag | None = None
    node = link_tag.parent
    for _ in range(8):
        if node is None or node.name in ("html", "body", "[document]"):
            break
        name = getattr(node, "name", "") or ""
        classes = " ".join(node.get("class") or []).lower()
        if name in ("tr", "li") or any(
            kw in classes for kw in ("krow", "ktopic", "row", "topic-item", "klist")
        ):
            row = node
            break
        node = node.parent

    search_root = row if row is not None else link_tag.parent
    if not search_root:
        return None

    for img in search_root.find_all("img"):
        src = str(img.get("src") or "").lower()
        if _ICON_BASE not in src:
            continue
        for stem, icon_type in _ICON_SRC_MAP:
            if f"{stem}.png" in src:
                return icon_type

    return None
