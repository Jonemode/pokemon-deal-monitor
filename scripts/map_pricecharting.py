"""Build data/pokemon/pricecharting_ids.json, mapping catalog cards to products.

Run with `make pricecharting-ids` once PRICECHARTING_TOKEN is set. Searches
one card every few seconds to stay clear of Cloudflare's rate limiting, so a
full run takes about fifteen minutes. Progress is saved after every card, so
an interrupted run resumes where it stopped. Entries already mapped,
including ones edited by hand, are kept; pass --refresh to redo them.

Review the output: cards marked "unresolved" or "ambiguous" list candidate
products, and a correct product_id can be filled in by hand.
"""

import argparse
import json
import sys

from pokemon_deal_monitor.config import load_pricecharting_token
from pokemon_deal_monitor.games.pokemon.catalog import CARDS
from pokemon_deal_monitor.games.pokemon.pricecharting import (
    PRODUCT_IDS_PATH,
    search_query,
    select_products,
)
from pokemon_deal_monitor.games.pokemon.tcgplayer import TCGPLAYER
from pokemon_deal_monitor.pricecharting import PriceChartingClient, PriceChartingError
from pokemon_deal_monitor.tcgcsv import fetch_prices


# Bulk searches are spaced further apart than the API's one-per-second limit:
# about 50 searches at that rate triggered Cloudflare's rate limiting.
SECONDS_BETWEEN_SEARCHES = 3.0


def describe(product: dict) -> str:
    return f"{product['id']}: {product.get('console-name')} / {product.get('product-name')}"


def save(entries: dict) -> None:
    PRODUCT_IDS_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    # Drop entries for cards no longer in the catalog.
    identifiers = {card.identifier for card in CARDS}
    entries = {k: v for k, v in entries.items() if k in identifiers}
    tcg_prices = fetch_prices(CARDS, TCGPLAYER)

    for index, card in enumerate(CARDS, 1):
        existing = entries.get(card.identifier, {})
        if existing.get("product_id") and not args.refresh:
            continue

        try:
            products = client.search(search_query(card))
        except PriceChartingError as error:
            mapped = sum(1 for entry in entries.values() if entry.get("product_id"))
            sys.exit(
                f"Stopped at {card.identifier}: {error}\n"
                f"{mapped} cards are mapped and saved. Run again later to resume."
            )
        tcg = tcg_prices.get(card.identifier)
        matches = select_products(card, products, tcg.product_id if tcg else None)

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
        # Save as we go so an interrupted run can resume.
        save(entries)

    mapped = sum(1 for entry in entries.values() if entry.get("product_id"))
    print(f"Mapped {mapped} of {len(CARDS)} cards to {PRODUCT_IDS_PATH}")


if __name__ == "__main__":
    main()
