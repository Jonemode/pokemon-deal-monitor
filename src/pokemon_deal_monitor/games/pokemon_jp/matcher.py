"""How sellers title Japanese Pokémon cards."""

from ...matcher import TitleRules, normalize
from ..pokemon.matcher import full_numbers, partial_numbers
from .catalog import CARDS


class JapanesePokemonTitleRules(TitleRules):

    set_aliases = {
        "CoroCoro Promo": [
            "corocoro comics", "corocoro comic", "corocoro", "coro coro",
        ],
    }

    # Shining Legends has an English and Japanese Shining Mew of its own,
    # worth a few dollars.
    other_set_aliases = ["shining legends", "sm3"]

    # "Hikaru" is Japanese for shining.
    name_aliases = {"Shining Mew": ["shiny mew", "hikaru mew"]}

    name_prefixes = ("shining ", "shiny ", "hikaru ")

    reject_patterns = [
        r"\b(?:reprint|celebrations|25th|30th)\b",
    ]

    def __init__(self, cards):
        super().__init__(cards)
        self.catalog_numbers = {self.card_numbers(card)[1] for card in cards}

    def title_numbers(self, text: str) -> tuple[set[str], set[str]]:
        """Read a full number starting with a catalog card's, such as
        151/151, as that card's number, and any other, such as Shining
        Legends' 041/072, as another card's. A short number naming no
        catalog card, as in "Promo 105" or "#5", is the seller's own
        numbering and ignored."""
        full, partial = full_numbers(text), partial_numbers(text)
        own = {number for number in full
               if number.split("/")[0] in self.catalog_numbers}
        partial |= {number.split("/")[0] for number in own}
        return full - own, partial & self.catalog_numbers

    def parse_card_number(self, number: str) -> tuple[str, str]:
        number = normalize(number)
        return number, number


RULES = JapanesePokemonTitleRules(CARDS)
