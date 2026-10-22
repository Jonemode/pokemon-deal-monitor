"""Vintage Pokémon cards, as the monitor watches them."""

from dataclasses import replace

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

# Promos alert up to 5% over value, but skip the many worth only a few
# dollars.
PROMO_RULES = CardRules(min_discount=-0.05, min_value_cents=5000)

# Cards sellers often list wrongly, with a far cheaper card's listing
# titled as this one. A discount beyond this is taken to mean the wrong
# card rather than a bargain.
MISLISTED_CARD_DISCOUNT = 0.50

POKEMON = Game(
    key=GAME,
    name="Pokémon",
    cards=CARDS,
    title_rules=RULES,
    searches=SEARCHES,
    tcgplayer=TCGPLAYER,
    pricecharting_ids_path=PRODUCT_IDS_PATH,
    set_rules={
        "Wizards Black Star Promos": PROMO_RULES,
        "Legendary Collection": CardRules(min_discount=-0.05),
    },
    # Each replaces its set's rules.
    card_rules={
        # 30th Anniversary Lugia reprints listed as Aquapolis.
        "pokemon:Aquapolis:149/147:holo:unlimited": CardRules(
            max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        # Shining Charizard and Shining Celebi.
        "pokemon:Neo Destiny:107/105:holo:1st": CardRules(
            max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        "pokemon:Neo Destiny:106/105:holo:1st": CardRules(
            max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        # Birthday Pikachu.
        "pokemon:Wizards Black Star Promos:24/53:holo:unlimited": replace(
            PROMO_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
    },
)
