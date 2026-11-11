"""Vintage Pokémon cards, as the monitor watches them."""

from dataclasses import replace
from datetime import timedelta

from ...game import Game
from ...valuation import NEAR_MINT, CardRules
from .catalog import CARDS, GAME, Variant
from .matcher import RULES, SETS_WITH_NON_HOLO_DUPLICATES
from .pricecharting import PRODUCT_IDS_PATH
from .tcgplayer import TCGPLAYER


# One search per target set, two for promos since sellers call them either
# Black Star or WOTC promos. Each poll makes one call per query, so with the
# Browse API's default 5,000 calls a day SEARCH_INTERVALS keeps us under it.
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

# Graded copies, valued at PriceCharting's price for their grade. Not
# "reverse holo": their slabs' labels, which titles copy, say "REV.FOIL".
GRADED_SEARCHES = ["pokemon legendary collection"]
GRADED_SETS = frozenset({"Legendary Collection"})

# Searches run less often than every poll. Each still reaches back many
# hours, so these only delay alerts. Polls are 4 minutes apart, so a search
# runs on the first poll after its interval: use multiples of 4 minutes.
SEARCH_INTERVALS = {
    "pokemon neo genesis 1st edition": timedelta(minutes=8),
    "pokemon neo discovery 1st edition": timedelta(minutes=8),
    "pokemon neo revelation 1st edition": timedelta(minutes=8),
    "pokemon neo destiny 1st edition": timedelta(minutes=8),
    "pokemon southern islands": timedelta(minutes=8),
    "pokemon wotc promo": timedelta(minutes=8),
    "pokemon black star promo": timedelta(minutes=12),
    # Few graded copies are listed.
    GRADED_SEARCHES[0]: timedelta(minutes=12),
}

# How far over value a listing's total can be and still alert, for every
# set: Buy It Now and Best Offer listings, and the maximum bid suggested
# for auctions. Change this one number to tighten or loosen those alerts,
# e.g. -0.10 to alert only at 10% or more below value.
MAX_OVER_VALUE = 0.30
# How far below value an auction's current bid plus shipping must be to
# alert, for every set. Early bids sit far below where an auction ends, so
# this is stricter than MAX_OVER_VALUE.
MIN_AUCTION_DISCOUNT = 0.20
ALERT_RULES = replace(CardRules.up_to_over_value(MAX_OVER_VALUE),
                      min_auction_discount=MIN_AUCTION_DISCOUNT)

# Graded listings alert up to this far over their grade's price, with a
# maximum bid to match.
GRADED_MAX_OVER_VALUE = 0.05
GRADED_RULES = replace(CardRules.up_to_over_value(GRADED_MAX_OVER_VALUE),
                       min_auction_discount=MIN_AUCTION_DISCOUNT)

# Promos skip the many worth only a few dollars.
PROMO_RULES = replace(ALERT_RULES, min_value_cents=5000)
# Promos only worth buying near mint: Mew 8, 9 and 47, Meowth 10, Eevee 11.
NEAR_MINT_PROMOS = ["8/53:normal", "9/53:holo", "47/53:normal",
                    "10/53:holo", "11/53:holo"]

# E-Card reverse holos with art no holo shares. A few have no PriceCharting
# price, such as Aquapolis Golduck with its 50a and 50b printings.
REVERSE_HOLO_ART_RULES = replace(ALERT_RULES, alert_without_value=True)

# Cards sellers often list wrongly, with a far cheaper card's listing
# titled as this one. A discount beyond this is taken to mean the wrong
# card rather than a bargain.
MISLISTED_CARD_DISCOUNT = 0.50

# 1st edition Base Set starters listed this far below value, at any listing
# type, are taken to be fakes or unlimited copies.
STARTERS_MAX_DISCOUNT = 0.75
BASE_SET_1ST_STARTERS = ["2/102", "4/102", "15/102"]  # Blastoise, Charizard, Venusaur

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
    graded_searches=GRADED_SEARCHES,
    graded_sets=GRADED_SETS,
    graded_rules=GRADED_RULES,
    set_rules={"Wizards Black Star Promos": PROMO_RULES},
    # Each replaces its set's rules.
    card_rules={
        **{
            card.identifier: REVERSE_HOLO_ART_RULES
            for card in CARDS
            if card.variant == Variant.REVERSE_HOLO
            and card.set_name in SETS_WITH_NON_HOLO_DUPLICATES
        },
        **{
            f"pokemon:Wizards Black Star Promos:{promo}:unlimited":
                replace(PROMO_RULES, card_conditions=NEAR_MINT)
            for promo in NEAR_MINT_PROMOS
        },
        **{
            f"pokemon:Base Set:{number}:holo:1st":
                replace(ALERT_RULES, max_discount=STARTERS_MAX_DISCOUNT)
            for number in BASE_SET_1ST_STARTERS
        },
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
