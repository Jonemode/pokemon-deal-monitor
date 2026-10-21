import unittest
from collections import Counter

from pokemon_deal_monitor.games.pokemon.catalog import Edition, Rarity, Variant, load_catalog


EXPECTED_SET_COUNTS = {
    "Base Set": 16,
    "Neo Genesis": 19,
    "Neo Discovery": 17,
    "Neo Revelation": 16,
    "Neo Destiny": 24,
    "Expedition": 32,
    "Aquapolis": 35,
    "Skyridge": 38,
    "Southern Islands": 6,
    "Legendary Collection": 110,
    "Wizards Black Star Promos": 53,
}

PROMOS = "Wizards Black Star Promos"

FIRST_EDITION_SETS = {
    "Base Set",
    "Neo Genesis",
    "Neo Discovery",
    "Neo Revelation",
    "Neo Destiny",
}


class TestCardData(unittest.TestCase):
    """Integrity checks for the shipped data/pokemon/cards.json catalog."""

    @classmethod
    def setUpClass(cls):
        cls.cards = load_catalog()

    def find(self, set_name, number):
        return [
            card for card in self.cards
            if card.set_name == set_name and card.number == number
        ]

    def test_set_counts(self):
        counts = Counter(card.set_name for card in self.cards)
        self.assertEqual(dict(counts), EXPECTED_SET_COUNTS)

    def test_editions(self):
        for card in self.cards:
            expected = (
                Edition.FIRST_EDITION
                if card.set_name in FIRST_EDITION_SETS
                else Edition.UNLIMITED
            )
            self.assertEqual(card.edition, expected, card.identifier)

    def test_variants(self):
        for card in self.cards:
            if card.set_name == PROMOS:
                continue
            expected = (
                Variant.REVERSE_HOLO
                if card.set_name in ("Legendary Collection", "Southern Islands")
                else Variant.HOLO
            )
            self.assertEqual(card.variant, expected, card.identifier)

    def test_promo_variants(self):
        variants = {card.number: card.variant
                    for card in self.cards if card.set_name == PROMOS}
        self.assertEqual(variants["3/53"], Variant.NORMAL)
        self.assertEqual(variants["9/53"], Variant.HOLO)
        self.assertEqual(variants["24/53"], Variant.HOLO)
        self.assertEqual(variants["35/53"], Variant.REVERSE_HOLO)

    def test_numbers_are_unique_within_set(self):
        counts = Counter((card.set_name, card.number) for card in self.cards)
        duplicates = [key for key, count in counts.items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_known_cards(self):
        expected = [
            ("Base Set", "4/102", "Charizard", Rarity.HOLO_RARE),
            ("Neo Genesis", "9/111", "Lugia", Rarity.HOLO_RARE),
            ("Neo Discovery", "14/75", "Unown A", Rarity.HOLO_RARE),
            ("Neo Revelation", "65/64", "Shining Gyarados", Rarity.SHINING),
            ("Neo Destiny", "107/105", "Shining Charizard", Rarity.SHINING),
            ("Expedition", "6/165", "Charizard", Rarity.HOLO_RARE),
            ("Aquapolis", "H29/H32", "Umbreon", Rarity.HOLO_RARE),
            ("Aquapolis", "149/147", "Lugia", Rarity.CRYSTAL),
            ("Skyridge", "146/144", "Charizard", Rarity.CRYSTAL),
            ("Southern Islands", "1/18", "Mew", Rarity.PROMO),
            ("Legendary Collection", "3/110", "Charizard", Rarity.HOLO_RARE),
            (PROMOS, "24/53", "Birthday Pikachu", Rarity.PROMO),
            (PROMOS, "38/53", "Unown J", Rarity.PROMO),
        ]

        for set_name, number, name, rarity in expected:
            with self.subTest(set_name=set_name, number=number):
                matches = self.find(set_name, number)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].name, name)
                self.assertEqual(matches[0].rarity, rarity)

    def test_regular_holo_sets_exclude_non_holos(self):
        allowed = {Rarity.HOLO_RARE, Rarity.SHINING, Rarity.CRYSTAL}
        for card in self.cards:
            if card.set_name in ("Southern Islands", "Legendary Collection", PROMOS):
                continue
            self.assertIn(card.rarity, allowed, card.identifier)


if __name__ == "__main__":
    unittest.main()
