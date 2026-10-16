
import unittest

from pokemon_deal_monitor.matcher import match_listing


class TestListingMatcher(unittest.TestCase):

    def test_first_edition_lugia(self):
        title = "Pokemon Lugia 9/111 Neo Genesis 1st Edition Holo LP"
        matches = match_listing(title)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "Lugia")

    def test_unlimited_lugia_rejected(self):
        title = "Pokemon Lugia 9/111 Neo Genesis Unlimited Holo"
        self.assertEqual(match_listing(title), [])

    def test_graded_card_rejected(self):
        title = "PSA 7 Lugia Neo Genesis 1st Edition Holo"
        self.assertEqual(match_listing(title), [])

    def test_base_set_charizard(self):
        title = "Charizard 4/102 Base Set 1st Edition Holo NM"
        matches = match_listing(title)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "Charizard")

    def test_aquapolis_umbreon(self):
        title = "Umbreon H29/H32 Aquapolis Holo LP"
        matches = match_listing(title)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].set_name, "Aquapolis")

    def test_legendary_collection_reverse(self):
        title = "Charizard 3/110 Legendary Collection Reverse Holo"
        matches = match_listing(title)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].set_name, "Legendary Collection")

    def test_regular_holo_not_reverse(self):
        title = "Charizard 3/110 Legendary Collection Holo"
        self.assertEqual(match_listing(title), [])


if __name__ == "__main__":
    unittest.main()

