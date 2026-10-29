import unittest

from pokemon_deal_monitor.games import GAMES
from pokemon_deal_monitor.games.pokemon.game import ALERT_RULES
from pokemon_deal_monitor.games.riftbound.game import RIFTBOUND
from pokemon_deal_monitor.pricecharting import load_product_ids
from pokemon_deal_monitor.tcgcsv import fetch_prices


CARDS = {card.number: card for card in RIFTBOUND.cards}
JINX = CARDS["301*/298"]


def matches(title):
    return [match.card.number for match in RIFTBOUND.title_rules.match(title)]


class TestRiftboundSignatures(unittest.TestCase):

    def test_every_origins_and_spiritforged_signature(self):
        self.assertEqual(len(RIFTBOUND.cards), 24)
        self.assertEqual(
            {card.set_name for card in RIFTBOUND.cards}, {"Origins", "Spiritforged"})
        self.assertEqual(JINX.identifier, "riftbound:Origins:301*/298:signature")
        self.assertIn(RIFTBOUND, GAMES)

    def test_matches_how_sellers_title_them(self):
        for title, number in (
            ("Jinx - Loose Cannon - Signature Overnumber 301*/298 - Riftbound - Origins (NM)",
             "301*/298"),
            ("Riftbound Swift Scout Teemo OGN 307*/298 over numbered signature",
             "307*/298"),
            ("2025 RIFTBOUND ORIGINS SIGNATURE OVERNUMBER #309* MISS FORTUNE",
             "309*/298"),
            ("Riftbound : League of Legends Darius, Executioner SFD·236*/221 Signature",
             "236*/221"),
            ("2026 Riftbound Spiritforged Yone Blademaster Signature Overnumber #SFD-233*",
             "233*/221"),
            # Without the star, but saying signature.
            ("Riftbound League of Legends TCG Ahri Nine-Tailed Fox Signature Card OGN 303/298",
             "303*/298"),
            ("2026 Riftbound SFD Spiritforged EN Signature Overnumber #230 Teemo",
             "230*/221"),
        ):
            self.assertEqual(matches(title), [number], title)

    def test_other_cards_and_printings_are_not_matched(self):
        for title in (
            # The unsigned overnumber, a far cheaper card with the same number.
            "Riftbound Jinx Loose Cannon Overnumbered 301/298 Origins",
            # Other languages.
            "Leona 2025 League of Legends Riftbound Chinese TCG Signature OGN 306*/298",
            "Riftbound Origins Teemo Swift Scout Signature Foil 307/298 Korean LoL TCG",
            # Later sets' signatures, and signature spells.
            "Riftbound Sett Kingpin Signature Overnumber 183*/167",
            "Riftbound Origins - Matriarch of War Ambessa 196*/166 - Foil - Signature",
            "Defiant Dance (SFD 196/221) Riftbound Irelia Signature Spell",
        ):
            self.assertEqual(matches(title), [], title)

    def test_alerts_like_every_pokemon_set(self):
        for card in RIFTBOUND.cards:
            self.assertIs(RIFTBOUND.rules_for(card), ALERT_RULES)

    def test_every_card_is_on_pricecharting(self):
        ids = load_product_ids(RIFTBOUND.pricecharting_ids_path)
        self.assertEqual(set(ids), {card.identifier for card in RIFTBOUND.cards})
        self.assertEqual(ids[JINX.identifier], "10560942")

    def test_tcgplayer_prices_the_signed_printing(self):
        def fetch(url):
            if url.endswith("/products"):
                return {"results": [
                    {"productId": 1, "name": "Jinx, Loose Cannon (Overnumbered)",
                     "extendedData": [{"name": "Number", "value": "301/298"}]},
                    {"productId": 2, "name": "Jinx, Loose Cannon (Signature)",
                     "extendedData": [{"name": "Number", "value": "301*/298"}]},
                ]}
            return {"results": [
                {"productId": 1, "subTypeName": "Foil", "marketPrice": 121.07},
                {"productId": 2, "subTypeName": "Foil", "marketPrice": 2275.00},
            ]}

        prices = fetch_prices([JINX], RIFTBOUND.tcgplayer, fetch)
        self.assertEqual(prices[JINX.identifier].market_cents, 227500)


if __name__ == "__main__":
    unittest.main()
