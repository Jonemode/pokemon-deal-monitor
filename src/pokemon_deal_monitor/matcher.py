"""Matching eBay titles to catalog cards.

The engine here weighs the evidence every game's titles carry: the card's
name, its number and its set. Each game subclasses TitleRules with how its
sellers write those, and with checks for the printings it tells apart.
"""

import re
import unicodedata
from dataclasses import dataclass

from .catalog import Card


@dataclass(frozen=True)
class Match:
    card: Card
    confidence: float


# Evidence weights. A card name alone is never enough: a match needs the
# card number or the set name as well.
NAME_WEIGHT = 0.3
FULL_NUMBER_WEIGHT = 0.4
PARTIAL_NUMBER_WEIGHT = 0.2
SET_WEIGHT = 0.3
MIN_CONFIDENCE = 0.5

# A title naming this many different catalog cards is a multi-card listing.
MAX_DISTINCT_NAMES = 2

# Titles of listings that are never a single raw card, in any game.
REJECT_PATTERNS = [
    # Graded cards, including grades written without a space ("PSA7").
    r"\b(?:psa|bgs|cgc|sgc|beckett|graded|slabbed|slab)\b",
    r"\b(?:psa|bgs|cgc|sgc)\d",
    # Grade labels copied from a slab, e.g. "NM-MT 8" or "GEM MINT 10".
    r"\b(?:nm mt|gem mt|gem mint|mint) \d{1,2}\b(?!/)",
    # Fakes and customs.
    r"\b(?:proxy|custom|orica|fake|replica)\b",
    # Multi-card listings.
    # Not "sealed": 1st Edition Machamp is commonly sold still in its
    # starter deck shrink wrap.
    r"\b(?:lot|bundle|complete set|\d+ card set)\b",
    # Condition is deliberately not judged from titles, where "HP" usually
    # means hit points; eBay's Card Condition field is used instead.
]


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, and collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9/#]+", " ", text.lower())
    return text.strip()


class TitleRules:
    """How one game's sellers title its cards, and the engine that matches
    titles against its catalog.

    Subclasses set the class attributes and implement title_numbers and
    card_numbers; score_printing and rejects add the game's own checks.
    """

    # Each catalog set's name and how titles write it.
    set_aliases: dict[str, list[str]] = {}
    # Sets outside the catalog. A title naming one of these and no catalog
    # set is about some other card.
    other_set_aliases: list[str] = []
    # Other ways titles write a card's name.
    name_aliases: dict[str, list[str]] = {}
    # Words that start some catalog names, e.g. "dark " in "Dark
    # Charizard", so they must not count as evidence for the plain name.
    name_prefixes: tuple[str, ...] = ()
    # Sets whose titles must include the card's number to match.
    number_required_sets: set[str] = set()
    # The game's own title rejections, on top of REJECT_PATTERNS.
    reject_patterns: list[str] = []

    def __init__(self, cards: list[Card]):
        self.cards = cards
        self.reject_pattern = re.compile(
            "|".join(f"(?:{p})" for p in REJECT_PATTERNS + self.reject_patterns)
        )
        aliases = [(alias, name) for name, group in self.set_aliases.items()
                   for alias in group]
        aliases += [(alias, None) for alias in self.other_set_aliases]
        aliases.sort(key=lambda item: len(item[0]), reverse=True)
        self.set_patterns = [
            (re.compile(rf"\b{re.escape(alias)}\b"), set_name)
            for alias, set_name in aliases
        ]
        self.word_prefixes = tuple(" " + prefix for prefix in self.name_prefixes)
        self._name_patterns: dict[str, list[re.Pattern]] = {}
        self._card_numbers: dict[str, tuple[str, str]] = {}

    def title_numbers(self, text: str) -> tuple[set[str], set[str]]:
        """Return the full and partial card numbers in a normalized title.
        A partial number is what card_numbers gives as the short form."""
        raise NotImplementedError

    def parse_card_number(self, number: str) -> tuple[str, str]:
        """Return a catalog number's full and short forms, normalized as
        title_numbers gives them."""
        raise NotImplementedError

    def card_numbers(self, card: Card) -> tuple[str, str]:
        if card.number not in self._card_numbers:
            self._card_numbers[card.number] = self.parse_card_number(card.number)
        return self._card_numbers[card.number]

    def rejects(self, text: str) -> bool:
        """Return whether a normalized title is ruled out before matching."""
        return bool(self.reject_pattern.search(text))

    def score_printing(
        self, card: Card, text: str, title_full_numbers: set[str]
    ) -> float | None:
        """Return a confidence adjustment for the card's printing, or None
        if the title rules the printing out."""
        return 0.0

    def name_patterns(self, name: str) -> list[re.Pattern]:
        if name not in self._name_patterns:
            names = [normalize(name)] + self.name_aliases.get(name, [])
            self._name_patterns[name] = [
                re.compile(rf"\b{re.escape(n)}\b") for n in names
            ]
        return self._name_patterns[name]

    def detect_sets(self, text: str) -> tuple[set[str], bool]:
        """Return catalog sets named in the title and whether another set is.

        Aliases are matched longest first and consumed, so "expedition base
        set" is not also read as Base Set, and "base set 2" is not read as
        Base Set.
        """
        found = set()
        other_set = False
        for pattern, set_name in self.set_patterns:
            if pattern.search(text):
                text = pattern.sub(" | ", text)
                if set_name is None:
                    other_set = True
                else:
                    found.add(set_name)

        return found, other_set

    def has_name(self, card: Card, text: str) -> bool:
        has_prefix = normalize(card.name).startswith(self.name_prefixes)

        for pattern in self.name_patterns(card.name):
            for m in pattern.finditer(text):
                # Padded so prefixes only match whole words: "islands mew"
                # must not read as the "s " of "_____'s".
                before = " " + text[:m.start()]
                if has_prefix or not before.endswith(self.word_prefixes):
                    return True

        return False

    def count_distinct_names(self, text: str) -> int:
        names = {card.name: card for card in self.cards}
        return sum(1 for card in names.values() if self.has_name(card, text))

    def score_card(
        self,
        card: Card,
        text: str,
        sets: set[str],
        title_full_numbers: set[str],
        title_partial_numbers: set[str],
    ) -> float | None:
        """Return a confidence for one card, or None if the title rules it
        out."""
        if not self.has_name(card, text):
            return None

        full, short = self.card_numbers(card)
        confidence = NAME_WEIGHT

        # A stated number that isn't the card's rules it out, e.g. "#28" is
        # the non-holo Poliwrath, not the 9/75 holo.
        if title_full_numbers:
            if full not in title_full_numbers:
                return None
            confidence += FULL_NUMBER_WEIGHT
        elif title_partial_numbers:
            if short not in title_partial_numbers:
                return None
            confidence += PARTIAL_NUMBER_WEIGHT
        elif card.set_name in self.number_required_sets:
            return None

        if sets:
            if card.set_name not in sets:
                return None
            confidence += SET_WEIGHT

        adjustment = self.score_printing(card, text, title_full_numbers)
        if adjustment is None:
            return None
        return round(min(confidence + adjustment, 1.0), 2)

    def match(self, title: str) -> list[Match]:
        """Return catalog cards that plausibly match an eBay title.

        Matches are sorted by confidence, highest first. More than one match
        means the title is ambiguous between catalog cards.
        """
        text = normalize(title)

        if self.rejects(text):
            return []

        sets, other_set = self.detect_sets(text)
        if other_set and not sets:
            return []

        if self.count_distinct_names(text) > MAX_DISTINCT_NAMES:
            return []

        title_full_numbers, title_partial_numbers = self.title_numbers(text)

        matches = []
        for card in self.cards:
            confidence = self.score_card(
                card, text, sets, title_full_numbers, title_partial_numbers
            )
            if confidence is not None and confidence >= MIN_CONFIDENCE:
                matches.append(Match(card=card, confidence=confidence))

        matches.sort(key=lambda match: match.confidence, reverse=True)
        return matches
