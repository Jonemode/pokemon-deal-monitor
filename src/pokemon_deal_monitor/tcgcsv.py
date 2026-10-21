"""TCGplayer market prices from tcgcsv.com, which mirrors them daily."""

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .ebay import USER_AGENT, to_cents
from .games.pokemon.catalog import PokemonCard, Variant
from .games.pokemon.matcher import card_number_key, full_numbers
from .matcher import normalize


TCGCSV_URL = "https://tcgcsv.com/tcgplayer/3"

# TCGplayer group IDs for each target set. TCGplayer files 1st Edition
# Base Set under "Base Set (Shadowless)" rather than "Base Set".
GROUP_IDS = {
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

# TCGplayer lists stamped and special versions of a promo under the same
# number as the plain card, e.g. "Rapidash [Pokemon Center NY]".
SPECIAL_VERSION_PATTERN = re.compile(
    r"\[|misprint|stamp|prerelease|corocoro|glossy", re.IGNORECASE
)

FetchJson = Callable[[str], dict]


@dataclass(frozen=True)
class TcgPrice:
    product_id: int
    # TCGplayer's market price, based on recent sales. The low and mid
    # prices are asking prices and can be wildly off for rare cards.
    market_cents: int


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def sub_type_name(card: PokemonCard) -> str:
    """Return the TCGplayer printing name for a catalog card."""
    if card.variant == Variant.REVERSE_HOLO:
        return "Reverse Holofoil"
    if card.variant == Variant.NORMAL:
        return "Normal"
    if card.first_edition_required:
        return "1st Edition Holofoil"
    return "Holofoil"


def product_number(product: dict) -> str | None:
    for entry in product.get("extendedData", []):
        if entry["name"] == "Number":
            numbers = full_numbers(normalize(entry["value"]))
            return next(iter(numbers), None)
    return None


def fetch_prices(
    cards: list[PokemonCard], fetch: FetchJson = fetch_json
) -> dict[str, TcgPrice]:
    """Return TCGplayer prices keyed by catalog card identifier.

    Cards TCGplayer has no market price for in the right printing are left
    out.
    """
    prices = {}
    by_set: dict[str, list[PokemonCard]] = {}
    for card in cards:
        by_set.setdefault(card.set_name, []).append(card)

    for set_name, set_cards in by_set.items():
        group_id = GROUP_IDS[set_name]
        products = fetch(f"{TCGCSV_URL}/{group_id}/products")["results"]
        rows = fetch(f"{TCGCSV_URL}/{group_id}/prices")["results"]

        product_ids_by_number: dict[str, list[int]] = {}
        for product in products:
            if SPECIAL_VERSION_PATTERN.search(product.get("name", "")):
                continue
            number = product_number(product)
            if number is not None:
                product_ids_by_number.setdefault(number, []).append(
                    product["productId"]
                )

        price_rows = {(row["productId"], row["subTypeName"]): row for row in rows}

        for card in set_cards:
            full, _ = card_number_key(card.number)
            candidates = [
                price_rows[(product_id, sub_type_name(card))]
                for product_id in product_ids_by_number.get(full, [])
                if (product_id, sub_type_name(card)) in price_rows
            ]
            # Skip numbers TCGplayer lists under more than one product.
            if len(candidates) != 1:
                continue

            row = candidates[0]
            if row.get("marketPrice") is None:
                continue

            prices[card.identifier] = TcgPrice(
                product_id=row["productId"],
                market_cents=to_cents(str(row["marketPrice"])),
            )

    return prices
