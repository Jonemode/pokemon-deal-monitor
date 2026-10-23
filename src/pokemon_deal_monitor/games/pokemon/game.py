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

# How far over value a listing's total can be and still alert, for every
# set: Buy It Now and Best Offer listings, and the maximum bid suggested
# for auctions. Change this one number to tighten or loosen those alerts,
# e.g. -0.10 to alert only at 10% or more below value.
MAX_OVER_VALUE = 0.20
# How far below value an auction's current bid plus shipping must be to
# alert, for every set. Early bids sit far below where an auction ends, so
# this is stricter than MAX_OVER_VALUE.
MIN_AUCTION_DISCOUNT = 0.20
ALERT_RULES = replace(CardRules.up_to_over_value(MAX_OVER_VALUE),
                      min_auction_discount=MIN_AUCTION_DISCOUNT)

# Promos skip the many worth only a few dollars.
PROMO_RULES = replace(ALERT_RULES, min_value_cents=5000)

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
    default_rules=ALERT_RULES,
    set_rules={"Wizards Black Star Promos": PROMO_RULES},
    # Each replaces its set's rules.
    card_rules={
        # 30th Anniversary Lugia reprints listed as Aquapolis.
        "pokemon:Aquapolis:149/147:holo:unlimited": replace(
            ALERT_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        # Shining Charizard and Shining Celebi.
        "pokemon:Neo Destiny:107/105:holo:1st": replace(
            ALERT_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        "pokemon:Neo Destiny:106/105:holo:1st": replace(
            ALERT_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
        # Birthday Pikachu.
        "pokemon:Wizards Black Star Promos:24/53:holo:unlimited": replace(
            PROMO_RULES, max_plausible_discount=MISLISTED_CARD_DISCOUNT),
    },
)
