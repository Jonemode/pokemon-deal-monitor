"""Generate data/cards.json from the PokemonTCG/pokemon-tcg-data repository.

Run with `make catalog`. The source data is pinned to a commit so the
generated catalog is reproducible; bump SOURCE_COMMIT to pick up fixes.
"""

import json
import urllib.request
from pathlib import Path

SOURCE_COMMIT = "39a26a144c8b6ef6c2fb17b2c29d0bb7121e3a11"
SOURCE_URL = (
    "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/"
    f"{SOURCE_COMMIT}"
)

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "cards.json"

RARITY_MAP = {
    "Common": "common",
    "Uncommon": "uncommon",
    "Rare": "rare",
    "Rare Holo": "holo_rare",
    "Rare Shining": "shining",
    # The only secret rares in Aquapolis and Skyridge are Crystal cards.
    "Rare Secret": "crystal",
}

NAME_FIXES = {
    "Unown [A]": "Unown A",
    "Unown [J]": "Unown J",
    "Ho-oh": "Ho-Oh",
    # Promo #24, printed with a blank to write a name in.
    "_____'s Pikachu": "Birthday Pikachu",
}

# (source set id, set name, edition, variant, source rarities to include).
# A rarity set of None includes every card in the set.
TARGET_SETS = [
    ("base1", "Base Set", "1st_edition", "holo", {"Rare Holo"}),
    ("neo1", "Neo Genesis", "1st_edition", "holo", {"Rare Holo"}),
    ("neo2", "Neo Discovery", "1st_edition", "holo", {"Rare Holo"}),
    ("neo3", "Neo Revelation", "1st_edition", "holo", {"Rare Holo", "Rare Shining"}),
    ("neo4", "Neo Destiny", "1st_edition", "holo", {"Rare Holo", "Rare Shining"}),
    ("ecard1", "Expedition", "unlimited", "holo", {"Rare Holo"}),
    ("ecard2", "Aquapolis", "unlimited", "holo", {"Rare Holo", "Rare Secret"}),
    ("ecard3", "Skyridge", "unlimited", "holo", {"Rare Holo", "Rare Secret"}),
    ("si1", "Southern Islands", "unlimited", "reverse_holo", None),
    ("base6", "Legendary Collection", "unlimited", "reverse_holo", None),
    # A variant of None takes each card's printing from VARIANTS.
    ("basep", "Wizards Black Star Promos", "unlimited", None, None),
]

# Per-card printings, for sets whose cards differ, keyed by card number.
# Each promo has a single printing; these follow TCGplayer's listings and
# every other promo is non-holo.
VARIANTS = {
    "basep": {
        **{n: "holo" for n in ("9", "10", "11", "13", "15", "17", "24")},
        **{n: "reverse_holo" for n in ("34", "35")},
    },
}
DEFAULT_VARIANTS = {"basep": "normal"}

PROMO_SETS = {"si1", "basep"}


# Card numbers to keep, for sets the source data can't filter by rarity.
# Each English Southern Islands card has a single printing: six are reverse
# holos and the other twelve are non-holo, so only those six are targeted.
INCLUDED_NUMBERS = {
    "si1": {"1", "4", "7", "11", "14", "17"},
}


def fetch_json(path: str):
    with urllib.request.urlopen(f"{SOURCE_URL}/{path}", timeout=30) as response:
        return json.load(response)


def format_number(number: str, printed_total: int, holo_total: int) -> str:
    # e-Card holo rares use their own H-numbered series, e.g. H29/H32.
    if number.startswith("H"):
        return f"{number}/H{holo_total}"
    return f"{number}/{printed_total}"


def build_set(set_info: dict, target: tuple) -> list[dict]:
    set_id, set_name, edition, variant, rarities = target
    cards = fetch_json(f"cards/en/{set_id}.json")
    holo_total = sum(1 for card in cards if card["number"].startswith("H"))

    entries = []
    for card in cards:
        source_rarity = card.get("rarity")
        if rarities is not None and source_rarity not in rarities:
            continue
        if set_id in INCLUDED_NUMBERS and card["number"] not in INCLUDED_NUMBERS[set_id]:
            continue

        rarity = "promo" if set_id in PROMO_SETS else RARITY_MAP[source_rarity]
        entries.append({
            "name": NAME_FIXES.get(card["name"], card["name"]),
            "set_name": set_name,
            "number": format_number(
                card["number"], set_info["printedTotal"], holo_total
            ),
            "variant": variant or VARIANTS[set_id].get(
                card["number"], DEFAULT_VARIANTS[set_id]
            ),
            "edition": edition,
            "rarity": rarity,
        })

    return entries


def main() -> None:
    sets = {entry["id"]: entry for entry in fetch_json("sets/en.json")}

    catalog = []
    for target in TARGET_SETS:
        entries = build_set(sets[target[0]], target)
        print(f"{target[1]}: {len(entries)} cards")
        catalog.extend(entries)

    OUTPUT_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(catalog)} cards to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
