"""Vintage Pokémon cards, as the monitor watches them."""

from ...game import Game
from ...valuation import CardRules
from .catalog import CARDS, GAME
from .matcher import RULES
from .pricecharting import PRODUCT_IDS_PATH
from .tcgplayer import TCGPLAYER


# One search per target set, two for promos since sellers call them either
# Black Star or WOTC promos. Each poll makes one call per query, so with the
# Browse API's default 5,000 calls a day a 5 minute interval leaves headroom.
SEARCHES = [
    "pokemon base set 1st edition",
    "pokemon neo genesis 1st edition",
    "pokemon neo discovery 1st edition",
    "pokemon neo revelation 1st edition",
    "pokemon neo destiny 1st edition",
    "pokemon expedition holo",
    "pokemon aquapolis",
    "pokemon skyridge",
    "pokemon southern islands",
    "pokemon legendary collection reverse holo",
    "pokemon black star promo",
    "pokemon wotc promo",
]

POKEMON = Game(
    key=GAME,
    name="Pokémon",
    cards=CARDS,
    title_rules=RULES,
    searches=SEARCHES,
    tcgplayer=TCGPLAYER,
    pricecharting_ids_path=PRODUCT_IDS_PATH,
    set_rules={
        # Alert up to 5% over value, but skip the many promos worth only a
        # few dollars.
        "Wizards Black Star Promos": CardRules(min_discount=-0.05,
                                               min_value_cents=5000),
        "Legendary Collection": CardRules(min_discount=-0.05),
    },
    card_rules={
        # 30th Anniversary Lugia reprints listed as Aquapolis.
        "pokemon:Aquapolis:149/147:holo:unlimited": CardRules(
            max_plausible_discount=0.50),
    },
)
