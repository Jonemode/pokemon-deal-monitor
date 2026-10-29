"""Build data/riftbound/pricecharting_ids.json, mapping Riftbound's
signature cards to PriceCharting products.

Run once PRICECHARTING_TOKEN is set. Entries already mapped, including
ones edited by hand, are kept; pass --refresh to redo them. Cards marked
"unresolved" or "ambiguous" list candidate products to choose from by hand.
"""

import argparse
import json
import sys

from pokemon_deal_monitor.config import load_pricecharting_token
from pokemon_deal_monitor.games.riftbound.catalog import CARDS
from pokemon_deal_monitor.games.riftbound.game import PRODUCT_IDS_PATH
from pokemon_deal_monitor.pricecharting import PriceChartingClient, PriceChartingError


SECONDS_BETWEEN_SEARCHES = 3.0


def describe(product: dict) -> str:
    return f"{product['id']}: {product.get('console-name')} / {product.get('product-name')}"


def is_product(card, product: dict) -> bool:
    """PriceCharting names them e.g. "Kai'Sa - Daughter of the Void
    [Signature] #299" under "Riftbound Origins"."""
    name = product.get("product-name", "")
    numerator = card.number.split("*")[0].lstrip("0")
    return (product.get("console-name") == f"Riftbound {card.set_name}"
            and "[Signature]" in name
            and name.endswith(f"#{numerator}"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Search again for cards that are already mapped")
    args = parser.parse_args()

    token = load_pricecharting_token()
    if token is None:
        sys.exit("Set PRICECHARTING_TOKEN in .env first.")
    client = PriceChartingClient(
        token, min_seconds_between_calls=SECONDS_BETWEEN_SEARCHES
    )
    entries = (
        json.loads(PRODUCT_IDS_PATH.read_text(encoding="utf-8"))
        if PRODUCT_IDS_PATH.exists() else {}
    )

    for index, card in enumerate(CARDS, 1):
        if entries.get(card.identifier, {}).get("product_id") and not args.refresh:
            continue
        query = f"riftbound {card.champion} signature {card.number.split('*')[0]}"
        try:
            products = client.search(query)
        except PriceChartingError as error:
            sys.exit(f"Stopped at {card.identifier}: {error}")
        matches = [p for p in products if is_product(card, p)]
        if len(matches) == 1:
            entries[card.identifier] = {
                "product_id": str(matches[0]["id"]),
                "product_name": describe(matches[0]),
                "status": "matched",
            }
        else:
            entries[card.identifier] = {
                "product_id": None,
                "status": "ambiguous" if matches else "unresolved",
                "candidates": [describe(p) for p in (matches or products)][:10],
            }
        print(f"[{index}/{len(CARDS)}] {card.identifier}: "
              f"{entries[card.identifier]['status']}")
        PRODUCT_IDS_PATH.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
