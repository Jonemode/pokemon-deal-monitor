import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .catalog import CARDS, PokemonCard, Rarity, Variant


@dataclass(frozen=True)
class Match:
    card: PokemonCard
    confidence: float


# Evidence weights. A card name alone is never enough: a match needs the
# card number or the set name as well.
NAME_WEIGHT = 0.3
FULL_NUMBER_WEIGHT = 0.4
PARTIAL_NUMBER_WEIGHT = 0.2
SET_WEIGHT = 0.3
UNEXPECTED_FIRST_EDITION_PENALTY = 0.2
MIN_CONFIDENCE = 0.5

SET_ALIASES = {
    "Base Set": ["base set", "base"],
    "Neo Genesis": ["neo genesis", "neo gen", "genesis"],
    "Neo Discovery": ["neo discovery", "discovery"],
    "Neo Revelation": ["neo revelation", "neo rev", "revelation"],
    "Neo Destiny": ["neo destiny", "destiny"],
    "Expedition": ["expedition base set", "expedition"],
    "Aquapolis": ["aquapolis"],
    "Skyridge": ["skyridge", "sky ridge"],
    "Southern Islands": ["southern islands", "southern island"],
    "Legendary Collection": ["legendary collection", "legendary coll"],
}

# Vintage sets outside the target list. A title naming one of these and no
# target set is about some other card.
OTHER_SET_ALIASES = [
    "base set 2", "base 2", "jungle", "fossil", "team rocket",
    "gym heroes", "gym challenge", "black star promo",
]

NAME_ALIASES = {
    "Ho-Oh": ["hooh"],
    "Porygon2": ["porygon 2"],
}

# Cards are named with these prefixes in the catalog, so "Dark Charizard"
# must not count as evidence for plain Charizard.
NAME_PREFIXES = ("dark ", "light ", "shining ")

# Sets where the same Pokemon also has a non-holo rare, so a title without
# a card number must say it is the holo.
SETS_WITH_NON_HOLO_DUPLICATES = {"Expedition", "Aquapolis", "Skyridge"}

# Southern Islands only exists as Regular and Reverse Holo, so sellers who
# just say "holo" mean the reverse holo.
HOLO_MEANS_REVERSE_SETS = {"Southern Islands"}

REJECT_PATTERNS = [
    # Graded cards, including grades written without a space ("PSA7").
    r"\b(?:psa|bgs|cgc|sgc|beckett|graded|slabbed|slab)\b",
    r"\b(?:psa|bgs|cgc|sgc)\d",
    # Grade labels copied from a slab, e.g. "NM-MT 8" or "GEM MINT 10".
    r"\b(?:nm mt|gem mt|gem mint|mint) \d{1,2}\b(?!/)",
    # Modern reprints of vintage cards.
    r"\b(?:celebrations|classic collection|evolutions|25th|reprint)\b",
    # Non-English printings.
    r"\b(?:japanese|japan|jpn|korean|chinese|german|french|italian"
    r"|spanish|portuguese|dutch|jp|ita|foreign)\b",
    # Markers seen on Japanese listings sold as "Southern Island" and similar.
    r"\b(?:old back|pokeca|commemorati)",
    # Fakes and customs.
    r"\b(?:proxy|custom|orica|fake|replica)\b",
    # Multi-card listings.
    # Not "sealed": 1st Edition Machamp is commonly sold still in its
    # starter deck shrink wrap.
    r"\b(?:lot|bundle|complete set|\d+ card set)\b",
    # Conditions worse than lightly played.
    r"\b(?:damaged|dmg|heavily played|moderately played|poor|creased)\b",
    r"\bmp\b",
    r"(?<!\d )\bhp\b",
]
REJECT_PATTERN = re.compile("|".join(f"(?:{p})" for p in REJECT_PATTERNS))

# A title naming this many different catalog cards is a multi-card listing.
MAX_DISTINCT_NAMES = 2

FIRST_EDITION_PATTERN = re.compile(r"\b(?:1st|first ed|1 ?ed\b)")
NOT_FIRST_EDITION_PATTERN = re.compile(r"\b(?:no|not|non) (?:1st|first)\b")
UNLIMITED_PATTERN = re.compile(r"\b(?:unlimited|unl)\b")
NON_HOLO_PATTERN = re.compile(r"\bnon ?holo|\bno holo\b")
REVERSE_HOLO_PATTERN = re.compile(
    r"\breverse\b|\brev holo\b|\bfirework|\bswirl|\bcosmo"
)
# Sellers label the non-holo version of a reverse holo card "Regular".
REGULAR_PATTERN = re.compile(r"\bregular\b")
HOLO_PATTERN = re.compile(r"\bholo|\bfoil\b")
CRYSTAL_PATTERN = re.compile(r"\bcrystal\b")

FULL_NUMBER_PATTERN = re.compile(r"\b(h?)0*(\d{1,3}) ?/ ?(h?)0*(\d{1,3})\b")
PARTIAL_NUMBER_PATTERN = re.compile(r"#\s?(h?)0*(\d{1,3})\b|\b(h)0*(\d{1,2})\b")


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, and collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9/#]+", " ", text.lower())
    return text.strip()


def full_numbers(text: str) -> set[str]:
    return {
        f"{m[1]}{m[2]}/{m[3]}{m[4]}"
        for m in FULL_NUMBER_PATTERN.finditer(text)
    }


def partial_numbers(text: str) -> set[str]:
    numbers = set()
    for m in PARTIAL_NUMBER_PATTERN.finditer(text):
        if m[2] is not None:
            numbers.add(f"{m[1]}{m[2]}")
        else:
            numbers.add(f"{m[3]}{m[4]}")
    return numbers


@lru_cache(maxsize=None)
def card_number_key(number: str) -> tuple[str, str]:
    """Return the normalized full number and numerator for a catalog card."""
    (full,) = full_numbers(normalize(number))
    return full, full.split("/")[0]


@lru_cache(maxsize=None)
def name_patterns(name: str) -> list[re.Pattern]:
    names = [normalize(name)] + NAME_ALIASES.get(name, [])
    return [re.compile(rf"\b{re.escape(n)}\b") for n in names]


def detect_sets(text: str) -> tuple[set[str], bool]:
    """Return target sets named in the title and whether another set is.

    Aliases are matched longest first and consumed, so "expedition base set"
    is not also read as Base Set, and "base set 2" is not read as Base Set.
    """
    aliases = [(alias, name) for name, group in SET_ALIASES.items()
               for alias in group]
    aliases += [(alias, None) for alias in OTHER_SET_ALIASES]
    aliases.sort(key=lambda item: len(item[0]), reverse=True)

    found = set()
    other_set = False
    for alias, set_name in aliases:
        pattern = rf"\b{re.escape(alias)}\b"
        if re.search(pattern, text):
            text = re.sub(pattern, " | ", text)
            if set_name is None:
                other_set = True
            else:
                found.add(set_name)

    return found, other_set


def has_name(card: PokemonCard, text: str) -> bool:
    has_prefix = normalize(card.name).startswith(NAME_PREFIXES)

    for pattern in name_patterns(card.name):
        for m in pattern.finditer(text):
            if has_prefix or not text[:m.start()].endswith(NAME_PREFIXES):
                return True

    return False


def count_distinct_names(text: str) -> int:
    names = {card.name: card for card in CARDS}
    return sum(1 for card in names.values() if has_name(card, text))


def score_card(
    card: PokemonCard,
    text: str,
    sets: set[str],
    title_full_numbers: set[str],
    title_partial_numbers: set[str],
) -> float | None:
    """Return a confidence for one card, or None if the title rules it out."""
    if not has_name(card, text):
        return None

    full, numerator = card_number_key(card.number)
    confidence = NAME_WEIGHT

    if title_full_numbers:
        if full not in title_full_numbers:
            return None
        confidence += FULL_NUMBER_WEIGHT
    elif numerator in title_partial_numbers:
        confidence += PARTIAL_NUMBER_WEIGHT

    if sets:
        if card.set_name not in sets:
            return None
        confidence += SET_WEIGHT

    if card.first_edition_required:
        if not FIRST_EDITION_PATTERN.search(text):
            return None
        if UNLIMITED_PATTERN.search(text):
            return None
    elif FIRST_EDITION_PATTERN.search(text):
        # None of the unlimited-only target sets had a 1st Edition print.
        confidence -= UNEXPECTED_FIRST_EDITION_PENALTY

    mentions_reverse = bool(REVERSE_HOLO_PATTERN.search(text))
    if card.variant == Variant.REVERSE_HOLO:
        if card.set_name in HOLO_MEANS_REVERSE_SETS:
            mentions_reverse = mentions_reverse or bool(HOLO_PATTERN.search(text))
        if not mentions_reverse or REGULAR_PATTERN.search(text):
            return None
    elif mentions_reverse:
        return None

    is_crystal = card.rarity == Rarity.CRYSTAL
    if bool(CRYSTAL_PATTERN.search(text)) != is_crystal:
        # The number alone identifies a crystal even when the seller
        # leaves the word out.
        if not (is_crystal and full in title_full_numbers):
            return None

    if (
        card.set_name in SETS_WITH_NON_HOLO_DUPLICATES
        and not is_crystal
        and full not in title_full_numbers
        and not HOLO_PATTERN.search(text)
    ):
        return None

    return round(min(confidence, 1.0), 2)


def match_listing(title: str) -> list[Match]:
    """Return eligible cards that plausibly match an eBay title.

    Matches are sorted by confidence, highest first. More than one match
    means the title is ambiguous between catalog cards.
    """
    text = normalize(title)

    if REJECT_PATTERN.search(text):
        return []
    if NON_HOLO_PATTERN.search(text) or NOT_FIRST_EDITION_PATTERN.search(text):
        return []

    sets, other_set = detect_sets(text)
    if other_set and not sets:
        return []

    if count_distinct_names(text) > MAX_DISTINCT_NAMES:
        return []

    title_full_numbers = full_numbers(text)
    title_partial_numbers = partial_numbers(text)

    matches = []
    for card in CARDS:
        confidence = score_card(
            card, text, sets, title_full_numbers, title_partial_numbers
        )
        if confidence is not None and confidence >= MIN_CONFIDENCE:
            matches.append(Match(card=card, confidence=confidence))

    matches.sort(key=lambda match: match.confidence, reverse=True)
    return matches
