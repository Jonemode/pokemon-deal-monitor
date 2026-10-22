"""Where the Pokémon catalog is on TCGplayer."""

import re

from ...matcher import normalize
from ...tcgcsv import TcgplayerCatalog, product_number_field
from .catalog import PokemonCard, Variant
from .matcher import card_number_key, full_numbers


class PokemonTcgplayerCatalog(TcgplayerCatalog):

    category_id = 3

    # TCGplayer files 1st Edition Base Set under "Base Set (Shadowless)"
    # rather than "Base Set".
    group_ids = {
        "Base Set": 1663,
        "Neo Genesis": 1396,
        "Neo Discovery": 1434,
        "Neo Revelation": 1389,
        "Neo Destiny": 1444,
        "Expedition": 1375,
        "Aquapolis": 1397,
        "Skyridge": 1372,
        "Southern Islands": 648,
        "Legendary Collection": 1374,
        "Wizards Black Star Promos": 1418,
    }

    # TCGplayer lists stamped and special versions of a promo under the
    # same number as the plain card, e.g. "Rapidash [Pokemon Center NY]".
    excluded_names = re.compile(
        r"\[|misprint|stamp|prerelease|corocoro|glossy", re.IGNORECASE
    )

    def card_number(self, card: PokemonCard) -> str:
        full, _ = card_number_key(card.number)
        return full

    def product_number(self, product: dict) -> str | None:
        value = product_number_field(product)
        if value is None:
            return None
        return next(iter(full_numbers(normalize(value))), None)

    def sub_type_name(self, card: PokemonCard) -> str:
        if card.variant == Variant.REVERSE_HOLO:
            return "Reverse Holofoil"
        if card.variant == Variant.NORMAL:
            return "Normal"
        if card.first_edition_required:
            return "1st Edition Holofoil"
        return "Holofoil"


TCGPLAYER = PokemonTcgplayerCatalog()
