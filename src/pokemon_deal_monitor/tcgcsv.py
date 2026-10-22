"""TCGplayer market prices from tcgcsv.com, which mirrors them daily."""

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .catalog import Card
from .ebay import USER_AGENT, to_cents


TCGCSV_URL = "https://tcgcsv.com/tcgplayer"


class TcgplayerCatalog:
    """Where one game's catalog cards are on TCGplayer.

    Subclasses set category_id and group_ids, and say how TCGplayer numbers
    and names each card's printing.
    """

    # TCGplayer's category for the game, e.g. 3 for Pokémon.
    category_id: int
    # TCGplayer group IDs, its sets, for each catalog set.
    group_ids: dict[str, int] = {}
    # Product names of versions priced apart from the plain card, such as
    # stamped promos sharing its number.
    excluded_names: re.Pattern | None = None

    def card_number(self, card: Card) -> str:
        """Return a catalog card's number as product_number gives it."""
        raise NotImplementedError

    def product_number(self, product: dict) -> str | None:
        """Return a TCGplayer product's card number, normalized."""
        raise NotImplementedError

    def sub_type_name(self, card: Card) -> str:
        """Return the TCGplayer printing name for a catalog card."""
        raise NotImplementedError


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


def product_number_field(product: dict) -> str | None:
    """Return the Number TCGplayer lists for a product, as written."""
    for entry in product.get("extendedData", []):
        if entry["name"] == "Number":
            return entry["value"]
    return None


def fetch_prices(
    cards: list[Card], catalog: TcgplayerCatalog, fetch: FetchJson = fetch_json
) -> dict[str, TcgPrice]:
    """Return TCGplayer prices keyed by catalog card identifier.

    Cards TCGplayer has no market price for in the right printing are left
    out.
    """
    prices = {}
    by_set: dict[str, list[Card]] = {}
    for card in cards:
        by_set.setdefault(card.set_name, []).append(card)

    for set_name, set_cards in by_set.items():
        url = f"{TCGCSV_URL}/{catalog.category_id}/{catalog.group_ids[set_name]}"
        products = fetch(f"{url}/products")["results"]
        rows = fetch(f"{url}/prices")["results"]

        product_ids_by_number: dict[str, list[int]] = {}
        for product in products:
            excluded = catalog.excluded_names
            if excluded is not None and excluded.search(product.get("name", "")):
                continue
            number = catalog.product_number(product)
            if number is not None:
                product_ids_by_number.setdefault(number, []).append(
                    product["productId"]
                )

        price_rows = {(row["productId"], row["subTypeName"]): row for row in rows}

        for card in set_cards:
            sub_type = catalog.sub_type_name(card)
            candidates = [
                price_rows[(product_id, sub_type)]
                for product_id in product_ids_by_number.get(
                    catalog.card_number(card), [])
                if (product_id, sub_type) in price_rows
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
