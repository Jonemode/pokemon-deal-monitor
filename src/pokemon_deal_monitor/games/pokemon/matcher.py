"""How sellers title vintage Pokémon cards."""

import re
from functools import lru_cache

from ...matcher import TitleRules, normalize
from .catalog import CARDS, PokemonCard, Rarity, Variant


UNEXPECTED_FIRST_EDITION_PENALTY = 0.2

# Sets where the same Pokemon also has a non-holo rare, so a title without
# a card number must say it is the holo.
SETS_WITH_NON_HOLO_DUPLICATES = {"Expedition", "Aquapolis", "Skyridge"}

# Crystal cards sharing a name with a regular holo in the same set, such as
# Aquapolis Kingdra. Sellers rarely write "crystal", so without that word
# these need their number; otherwise the cheaper holo is assumed, which can
# undervalue a crystal but never makes a holo look like a crystal bargain.
CRYSTAL_NAME_CLASHES = {
    (card.set_name, card.name)
    for card in CARDS
    if card.rarity == Rarity.CRYSTAL
    and any(
        other.set_name == card.set_name and other.name == card.name
        and other.rarity != Rarity.CRYSTAL
        for other in CARDS
    )
}

# Sets where each targeted card has a single English printing, so the
# title needn't say holo or reverse holo. In Southern Islands the six
# targeted cards only exist as reverse holos.
SINGLE_PRINTING_SETS = {"Southern Islands", "Wizards Black Star Promos"}

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
PARTIAL_NUMBER_PATTERN = re.compile(
    r"#\s?(h?)0*(\d{1,3})\b|\b(h)0*(\d{1,2})\b"
    # Promo numbers are also written "No. 4" or "Promo 4".
    r"|\b(?:no|promo) ?#?0*(\d{1,3})\b"
)


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
        elif m[4] is not None:
            numbers.add(f"{m[3]}{m[4]}")
        else:
            numbers.add(m[5])
    return numbers


@lru_cache(maxsize=None)
def card_number_key(number: str) -> tuple[str, str]:
    """Return the normalized full number and numerator for a catalog card."""
    (full,) = full_numbers(normalize(number))
    return full, full.split("/")[0]


class PokemonTitleRules(TitleRules):

    set_aliases = {
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
        "Wizards Black Star Promos": [
            "wizards black star promos", "wizards black star promo",
            "wotc black star promos", "wotc black star promo",
            "black star promos", "black star promo",
            "wizards promo", "wotc promos", "wotc promo",
        ],
    }

    # Vintage sets outside the target list.
    other_set_aliases = [
        "base set 2", "base 2", "jungle", "fossil", "team rocket",
        "gym heroes", "gym challenge",
        "nintendo black star promo", "nintendo promo",
    ]

    name_aliases = {
        "Ho-Oh": ["hooh"],
        "Porygon2": ["porygon 2"],
        # Printed as "_____'s Pikachu", which normalizes to "s pikachu".
        "Birthday Pikachu": ["s pikachu"],
    }

    # Cards are named with these prefixes in the catalog, so "Dark
    # Charizard" must not count as evidence for plain Charizard, nor "Team
    # Rocket's Meowth" ("team rocket s meowth") for plain Meowth.
    name_prefixes = (
        "dark ", "light ", "shining ", "s ", "cool ", "flying ", "surfing ",
        "birthday ",
    )

    # Promos repeat names (four Pikachus) and modern Black Star Promos reuse
    # the set name, so the number is the only reliable way to tell them
    # apart.
    number_required_sets = {"Wizards Black Star Promos"}

    reject_patterns = [
        # Modern reprints of vintage cards.
        r"\b(?:celebrations|classic collection|evolutions|25th|30th|reprint)\b",
        # Non-English printings.
        r"\b(?:japanese|japan|jpn|korean|chinese|german|french|italian"
        r"|spanish|portuguese|dutch|jp|ita|foreign)\b",
        # Markers seen on Japanese listings sold as "Southern Island" and
        # similar.
        r"\b(?:old back|pokeca|commemorati)",
        # Stamped and special promo versions, priced apart from the plain
        # card. A "1st Edition stamp" is the edition mark, not a special
        # version.
        r"\b(?:prerelease|pre release|winner)\b",
        r"(?<!edition )(?<!1st ed )(?<!1st )\bstamp(?:ed)?\b",
        # Modern promo codes such as SWSH050, SM210 or SVP 085.
        r"\b(?:swsh|sm|xy|bw|dp|hgss|svp|sv|mep) ?\d{1,3}\b",
        # Mega Evolutions, and the Mega Evolution series, came long after
        # WotC.
        r"\bmega\b",
    ]

    def title_numbers(self, text: str) -> tuple[set[str], set[str]]:
        return full_numbers(text), partial_numbers(text)

    def parse_card_number(self, number: str) -> tuple[str, str]:
        return card_number_key(number)

    def rejects(self, text: str) -> bool:
        return (
            super().rejects(text)
            or bool(NON_HOLO_PATTERN.search(text))
            or bool(NOT_FIRST_EDITION_PATTERN.search(text))
        )

    def score_printing(
        self, card: PokemonCard, text: str, title_full_numbers: set[str]
    ) -> float | None:
        """Check the title against the card's edition, holo or reverse holo
        printing, and crystal rarity."""
        full, _ = self.card_numbers(card)
        adjustment = 0.0

        if card.first_edition_required:
            if not FIRST_EDITION_PATTERN.search(text):
                return None
            if UNLIMITED_PATTERN.search(text):
                return None
        elif FIRST_EDITION_PATTERN.search(text):
            # None of the unlimited-only target sets had a 1st Edition print.
            adjustment -= UNEXPECTED_FIRST_EDITION_PENALTY

        mentions_reverse = bool(REVERSE_HOLO_PATTERN.search(text))
        if card.set_name in SINGLE_PRINTING_SETS:
            # Only one printing exists, so the title needn't say which.
            # Sellers use "Regular" for the non-holo Southern Islands cards.
            if card.variant == Variant.REVERSE_HOLO and REGULAR_PATTERN.search(text):
                return None
        elif card.variant == Variant.REVERSE_HOLO:
            if not mentions_reverse or REGULAR_PATTERN.search(text):
                return None
        elif mentions_reverse:
            return None

        is_crystal = card.rarity == Rarity.CRYSTAL
        says_crystal = bool(CRYSTAL_PATTERN.search(text))
        if is_crystal:
            if (
                not says_crystal
                and full not in title_full_numbers
                and (card.set_name, card.name) in CRYSTAL_NAME_CLASHES
            ):
                return None
        elif says_crystal:
            return None

        if (
            card.set_name in SETS_WITH_NON_HOLO_DUPLICATES
            and not is_crystal
            and full not in title_full_numbers
            and not HOLO_PATTERN.search(text)
        ):
            return None

        return adjustment


RULES = PokemonTitleRules(CARDS)
