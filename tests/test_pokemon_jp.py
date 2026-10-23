import unittest
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.game import ENGLISH
from pokemon_deal_monitor.games import GAMES
from pokemon_deal_monitor.games.pokemon.game import ALERT_RULES, POKEMON
from pokemon_deal_monitor.games.pokemon_jp.game import POKEMON_JP
from pokemon_deal_monitor.monitor import details_rejection
from pokemon_deal_monitor.ebay import ItemDetails
from pokemon_deal_monitor.pricecharting import load_product_ids
from pokemon_deal_monitor.storage import PriceRecord, Storage
from pokemon_deal_monitor.valuation import TCGPLAYER


(MEW,) = POKEMON_JP.cards


def matches(title):
    return [match.card for match in POKEMON_JP.title_rules.match(title)]


class TestCoroCoroMew(unittest.TestCase):

    def test_identifier(self):
        self.assertEqual(MEW.identifier, "pokemon_jp:CoroCoro Promo:151:holo")

    def test_monitored_as_its_own_game(self):
        self.assertIn(POKEMON_JP, GAMES)
        self.assertNotEqual(POKEMON_JP.key, POKEMON.key)

    def test_matches_how_sellers_title_it(self):
        for title in (
            "Shining Mew No.151 2001 Coro Coro Comics Promo Japanese Pokemon Card",
            "Shining Mew Corocoro Promotional Card Holo (Japanese)",
            "Pokemon TCG Shining Mew Corocoro Promo 151/151 Holo Japanese 2001",
            "Shiny Mew CoroCoro Comic May 2001 Issue",
            "Hikaru Mew CoroCoro Promo Old Back",
            # Sellers' own stock numbers.
            "Shining Mew Monthly CoroCoro Comic May 2001 Bonus Card PROMO 105",
            "Shining Mew CoroCoro Comics Promo Holo MP Japanese Pokemon Card #5",
        ):
            self.assertEqual(matches(title), [MEW], title)

    def test_other_mews_and_graded_copies_are_not_matched(self):
        for title in (
            # Shining Legends' Shining Mew.
            "041/072 Pokemon Card Shining Mew CoroCoro Promo Holo Japanese",
            "Shining Mew Shining Legends SM3+ Japanese",
            "Pokemon Card Japanese Mew Lv.23 Glossy CoroCoro Promo Holo Old Back",
            "Shining Mewtwo CoroCoro Promo",
            "Shining Mew CoroCoro Comic Promo PSA4 105",
            "Pokemon Coro Coro Mew Promo Extended Artwork Case",
        ):
            self.assertEqual(matches(title), [], title)

    def test_japanese_and_english_listings_are_kept(self):
        for language in ("Japanese", "English", None):
            self.assertIsNone(details_rejection(
                ItemDetails(None, language), POKEMON_JP.languages))
        self.assertIsNotNone(details_rejection(
            ItemDetails(None, "Korean"), POKEMON_JP.languages))
        # The English game still rejects Japanese listings.
        self.assertIsNotNone(details_rejection(
            ItemDetails(None, "Japanese"), ENGLISH))

    def test_searched_every_15_minutes(self):
        self.assertEqual(POKEMON_JP.search_intervals["corocoro shining mew"],
                         timedelta(minutes=15))

    def test_alerts_like_every_pokemon_set(self):
        self.assertIs(POKEMON_JP.rules_for(MEW), ALERT_RULES)

    def test_priced_by_pricecharting(self):
        ids = load_product_ids(POKEMON_JP.pricecharting_ids_path)
        self.assertEqual(ids, {MEW.identifier: "4247789"})
        self.assertIsNone(POKEMON_JP.tcgplayer)

    def test_english_title_rules_still_reject_it(self):
        self.assertEqual(POKEMON.title_rules.match(
            "Shining Mew No.151 CoroCoro Comic Promo Japanese"), [])

    def test_english_price_fetches_ignore_japanese_cards(self):
        with Storage(":memory:") as storage:
            storage.save_price(PriceRecord(
                MEW.identifier, TCGPLAYER,
                datetime(2026, 10, 17, tzinfo=timezone.utc), raw_cents=1))
            self.assertIsNone(storage.latest_price_fetch(TCGPLAYER, game="pokemon"))
