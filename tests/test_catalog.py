
import json
import tempfile
import unittest
from pathlib import Path

from pokemon_deal_monitor.games.pokemon.catalog import (
    Edition,
    PokemonCard,
    Rarity,
    Variant,
    load_catalog,
)


class TestCatalog(unittest.TestCase):

    def load_from_data(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cards.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_catalog(path)

    def test_load_valid_catalog(self):
        cards = self.load_from_data([
            {
                "name": "Lugia",
                "set_name": "Neo Genesis",
                "number": "9/111",
                "variant": "holo",
                "edition": "1st_edition",
                "rarity": "holo_rare",
            }
        ])

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].name, "Lugia")
        self.assertEqual(cards[0].variant, Variant.HOLO)
        self.assertEqual(cards[0].edition, Edition.FIRST_EDITION)
        self.assertEqual(cards[0].rarity, Rarity.HOLO_RARE)
        self.assertTrue(cards[0].first_edition_required)

    def test_invalid_root(self):
        with self.assertRaises(ValueError):
            self.load_from_data({"cards": []})

    def test_missing_required_field(self):
        with self.assertRaises(ValueError):
            self.load_from_data([
                {
                    "name": "Lugia",
                    "set_name": "Neo Genesis",
                    "number": "9/111",
                    "variant": "holo",
                }
            ])

    def test_invalid_variant(self):
        with self.assertRaises(ValueError):
            self.load_from_data([
                {
                    "name": "Lugia",
                    "set_name": "Neo Genesis",
                    "number": "9/111",
                    "variant": "non_holo",
                    "edition": "1st_edition",
                "rarity": "holo_rare",
                }
            ])

    def test_invalid_edition(self):
        with self.assertRaises(ValueError):
            self.load_from_data([
                {
                    "name": "Lugia",
                    "set_name": "Neo Genesis",
                    "number": "9/111",
                    "variant": "holo",
                    "edition": "yes",
                    "rarity": "holo_rare",
                }
            ])

    def test_invalid_rarity(self):
        with self.assertRaises(ValueError):
            self.load_from_data([
                {
                    "name": "Lugia",
                    "set_name": "Neo Genesis",
                    "number": "9/111",
                    "variant": "holo",
                    "edition": "1st_edition",
                    "rarity": "ultra_rare",
                }
            ])

    def test_duplicate_identifier(self):
        card = {
            "name": "Lugia",
            "set_name": "Neo Genesis",
            "number": "9/111",
            "variant": "holo",
            "edition": "1st_edition",
            "rarity": "holo_rare",
        }

        with self.assertRaises(ValueError):
            self.load_from_data([card, card])

    def test_card_identifier(self):
        card = PokemonCard(
            name="Lugia",
            set_name="Neo Genesis",
            number="9/111",
            variant=Variant.HOLO,
            edition=Edition.FIRST_EDITION,
            rarity=Rarity.HOLO_RARE,
        )

        self.assertEqual(
            card.identifier,
            "pokemon:Neo Genesis:9/111:holo:1st",
        )


if __name__ == "__main__":
    unittest.main()

