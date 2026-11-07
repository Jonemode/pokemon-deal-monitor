"""Japanese Pokémon cards, as the monitor watches them."""

from dataclasses import replace
from datetime import timedelta

from ...catalog import DATA_DIR
from ...game import ENGLISH, JAPANESE, Game
from ...valuation import NEAR_MINT
from ..pokemon.game import ALERT_RULES
from .catalog import CARDS, GAME
from .matcher import RULES


SEARCHES = ["corocoro shining mew"]

# Its 200 newest listings reach back over two months.
SEARCH_INTERVALS = {"corocoro shining mew": timedelta(minutes=16)}

# Listed by hand: TCGplayer doesn't sell Japanese promos, and the one card
# is easier to map than to search for.
PRODUCT_IDS_PATH = DATA_DIR / GAME / "pricecharting_ids.json"

POKEMON_JP = Game(
    key=GAME,
    name="Japanese Pokémon",
    cards=CARDS,
    title_rules=RULES,
    searches=SEARCHES,
    search_intervals=SEARCH_INTERVALS,
    pricecharting_ids_path=PRODUCT_IDS_PATH,
    # English is kept too, since some sellers leave eBay's default.
    languages=JAPANESE | ENGLISH,
    # Most listings are sold from Japan.
    us_sellers_only=False,
    default_rules=replace(ALERT_RULES, card_conditions=NEAR_MINT),
)
