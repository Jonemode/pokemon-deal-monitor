"""Vintage Pokémon cards, as the monitor watches them."""

from dataclasses import replace
from datetime import timedelta

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

# Searches run less often than every poll. Each still reaches back many
# hours, so these only delay alerts.
SEARCH_INTERVALS = {
    "pokemon neo genesis 1st edition": timedelta(minutes=15),
    "pokemon neo discovery 1st edition": timedelta(minutes=15),
    "pokemon neo revelation 1st edition": timedelta(minutes=15),
    "pokemon southern islands": timedelta(minutes=10),
    "pokemon wotc promo": timedelta(minutes=15),
}

# Promos alert up to 5% over value, but skip the many worth only a few
# dollars.
PROMO_RULES = CardRules(min_discount=-0.05, min_value_cents=5000)

# Alert up to 20% over value, for every kind of listing, with a maximum
# bid to match.
OVER_VALUE_RULES = CardRules(
    min_discount=-0.20, max_offer_premium=0.20,
    min_auction_discount=-0.20, max_bid_discount=-0.20)

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
    search_intervals=SEARCH_INTERVALS,
    tcgplayer=TCGPLAYER,
    pricecharting_ids_path=PRODUCT_IDS_PATH,
    set_rules={
        "Wizards Black Star Promos": PROMO_RULES,
        "Legendary Collection": OVER_VALUE_RULES,
        "Expedition": OVER_VALUE_RULES,
        "Aquapolis": OVER_VALUE_RULES,
        "Skyridge": OVER_VALUE_RULES,
    },
    # Each replaces its set's rules.
    card_rules={
        # 30th Anniversary Lugia reprints listed as Aquapolis.
        "pokemon:Aquapolis:149/147:holo:unlimited": replace(
            OVER_VALUE_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
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
