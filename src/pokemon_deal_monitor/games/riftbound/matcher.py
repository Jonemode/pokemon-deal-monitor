"""How sellers title Riftbound signature cards."""

import re

from ...matcher import Match, TitleRules, normalize
from .catalog import CARDS, RiftboundCard


# Card numbers, e.g. "299*/298" or "OGN 299/298", read without the star.
FULL_NUMBER_PATTERN = re.compile(r"\b0*(\d{1,3}) ?/ ?0*(\d{3})\b")
PARTIAL_NUMBER_PATTERN = re.compile(r"(?<!/)\b0*(\d{3})\b(?! ?/)")
# A star after a card number marks the signature printing.
STARRED_NUMBER_PATTERN = re.compile(r"\d ?\*")
SIGNATURE_PATTERN = re.compile(
    r"\b(?:signature|signatures|signatured|signed|sig|auto|autograph"
    r"|autographed)\b"
)


class RiftboundTitleRules(TitleRules):

    set_aliases = {
        "Origins": ["origins", "origin", "ogn"],
        "Spiritforged": ["spiritforged", "spirit forged", "sfd"],
    }

    # Later sets, and products of their own, with signatures too.
    other_set_aliases = [
        "proving grounds", "radiance", "rad", "vendetta", "ven",
        "unleashed", "unl", "legacy", "t1", "t1s", "worlds",
    ]

    name_aliases = {
        "Kai'Sa, Daughter of the Void": ["kaisa"],
        "Miss Fortune, Bounty Hunter": ["mf"],
    }

    reject_patterns = [
        # Other languages' printings, priced apart from English.
        r"\b(?:chinese|china|s chinese|simplified|cn|korean|kor|korea"
        r"|japanese|french|german)\b",
    ]

    def __init__(self, cards):
        super().__init__(cards)
        self.catalog_numbers = {self.card_numbers(card)[1] for card in cards}

    def title_numbers(self, text: str) -> tuple[set[str], set[str]]:
        full = {f"{m[1]}/{m[2]}" for m in FULL_NUMBER_PATTERN.finditer(text)}
        # A lone number counts only if it is a catalog card's, so years
        # and serial numbers are ignored.
        partial = {m[1] for m in PARTIAL_NUMBER_PATTERN.finditer(text)}
        return full, partial & self.catalog_numbers

    def parse_card_number(self, number: str) -> tuple[str, str]:
        (full,) = {f"{m[1]}/{m[2]}"
                   for m in FULL_NUMBER_PATTERN.finditer(normalize(number))}
        return full, full.split("/")[0]

    def name_patterns(self, name: str) -> list[re.Pattern]:
        """Sellers write the champion, its title, or both, in either
        order."""
        if name not in self._name_patterns:
            card = RiftboundCard(name, "", "")
            names = {normalize(name), normalize(card.champion),
                     normalize(card.title)}
            names.update(self.name_aliases.get(name, []))
            self._name_patterns[name] = [
                re.compile(rf"\b{re.escape(n)}\b") for n in names if n
            ]
        return self._name_patterns[name]

    def score_printing(self, card, text, title_full_numbers):
        # The same number without a signature is a far cheaper card.
        return 0.0 if SIGNATURE_PATTERN.search(text) else None

    def match(self, title: str) -> list[Match]:
        if STARRED_NUMBER_PATTERN.search(title):
            title += " signature"
        return super().match(title)


RULES = RiftboundTitleRules(CARDS)
