
import re

from .catalog import CARDS, PokemonCard, Variant


FIRST_EDITION_PATTERN = re.compile(
    r"\b(?:1st|first)\s*(?:edition|ed)\b",
    re.IGNORECASE,
)

REVERSE_HOLO_PATTERN = re.compile(
    r"\b(?:reverse\s*holo|reverse\s*foil|rev\s*holo)\b",
    re.IGNORECASE,
)

GRADED_PATTERN = re.compile(
    r"\b(?:PSA|BGS|CGC|SGC|graded|slabbed)\b",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def match_listing(title: str) -> list[PokemonCard]:
    """Return eligible cards that plausibly match an eBay title."""
    normalized = normalize(title)

    if GRADED_PATTERN.search(normalized):
        return []

    matches = []

    for card in CARDS:
        if not re.search(
            rf"\b{re.escape(card.name.lower())}\b",
            normalized,
        ):
            continue

        has_number = card.number.lower() in normalized
        has_set = card.set_name.lower() in normalized

        # Require either the exact number or the set name.
        if not (has_number or has_set):
            continue

        if (
            card.first_edition_required
            and not FIRST_EDITION_PATTERN.search(normalized)
        ):
            continue

        if card.variant == Variant.REVERSE_HOLO:
            if not REVERSE_HOLO_PATTERN.search(normalized):
                continue
        elif REVERSE_HOLO_PATTERN.search(normalized):
            continue

        matches.append(card)

    return matches

