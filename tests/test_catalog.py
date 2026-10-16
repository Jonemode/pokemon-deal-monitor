
import json
import tempfile
import unittest
from pathlib import Path

from pokemon_deal_monitor.catalog import (
    PokemonCard,
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
                "first_edition_required": True,
            }
        ])

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].name, "Lugia")
        self.assertEqual(cards[0].variant, Variant.HOLO)
        self.assertTrue(cards[0].first_edition_required)

    def test_default_catalog(self):
        cards = load_catalog()
        self.assertEqual(len(cards), 4)

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
                    "first_edition_required": True,
                }
            ])

    def test_invalid_edition_type(self):
        with self.assertRaises(ValueError):
            self.load_from_data([
                {
                    "name": "Lugia",
                    "set_name": "Neo Genesis",
                    "number": "9/111",
                    "variant": "holo",
                    "first_edition_required": "yes",
                }
            ])

    def test_duplicate_identifier(self):
        card = {
            "name": "Lugia",
            "set_name": "Neo Genesis",
            "number": "9/111",
            "variant": "holo",
            "first_edition_required": True,
        }

        with self.assertRaises(ValueError):
            self.load_from_data([card, card])

    def test_card_identifier(self):
        card = PokemonCard(
            name="Lugia",
            set_name="Neo Genesis",
            number="9/111",
            variant=Variant.HOLO,
            first_edition_required=True,
        )

        self.assertEqual(
            card.identifier,
            "Neo Genesis:9/111:holo:1st",
        )


if __name__ == "__main__":
    unittest.main()

