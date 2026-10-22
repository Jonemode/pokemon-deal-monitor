import unittest
from dataclasses import replace
from datetime import datetime, timezone

from pokemon_deal_monitor.games import GAMES
from pokemon_deal_monitor.games.pokemon.game import POKEMON
from pokemon_deal_monitor.storage import PriceRecord, Storage
from pokemon_deal_monitor.valuation import DEFAULT_RULES, TCGPLAYER, Pricer


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def card(identifier):
    return next(c for c in POKEMON.cards if c.identifier == identifier)


class TestGame(unittest.TestCase):

    def test_games_have_distinct_keys(self):
        self.assertEqual(len({g.key for g in GAMES}), len(GAMES))
        for game in GAMES:
            for c in game.cards:
                self.assertTrue(c.identifier.startswith(f"{game.key}:"), c)

    def test_set_rules(self):
        promo = card("pokemon:Wizards Black Star Promos:9/53:holo:unlimited")
        rules = POKEMON.rules_for(promo)
        self.assertEqual(rules.min_discount, -0.05)
        self.assertEqual(rules.min_value_cents, 5000)

    def test_card_rules(self):
        lugia = card("pokemon:Aquapolis:149/147:holo:unlimited")
        self.assertEqual(POKEMON.rules_for(lugia).max_plausible_discount, 0.50)

    def test_mislisted_cards_have_a_discount_limit(self):
        for identifier in ("pokemon:Neo Destiny:107/105:holo:1st",
                           "pokemon:Neo Destiny:106/105:holo:1st",
                           "pokemon:Wizards Black Star Promos:24/53:holo:unlimited"):
            self.assertEqual(
                POKEMON.rules_for(card(identifier)).max_plausible_discount,
                0.50, identifier)

    def test_birthday_pikachu_keeps_promo_rules(self):
        rules = POKEMON.rules_for(
            card("pokemon:Wizards Black Star Promos:24/53:holo:unlimited"))
        self.assertEqual(rules.min_discount, -0.05)
        self.assertEqual(rules.min_value_cents, 5000)

    def test_default_rules(self):
        charizard = card("pokemon:Base Set:4/102:holo:1st")
        self.assertIs(POKEMON.rules_for(charizard), DEFAULT_RULES)


class TestPricerPerGame(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)
        self.fetches = []

    def fetch(self, cards, catalog):
        self.fetches.append(cards)
        return {}

    def test_another_games_prices_dont_count_as_fresh(self):
        self.storage.save_price(PriceRecord("other:Set:1:regular", TCGPLAYER, START,
                                            raw_cents=100))
        self.assertEqual(self.storage.latest_price_fetch(TCGPLAYER, game="pokemon"),
                         None)
        Pricer(self.storage, POKEMON, fetch_tcgplayer=self.fetch).refresh_tcgplayer(START)
        self.assertEqual(len(self.fetches), 1)

    def test_game_without_tcgplayer_skips_it(self):
        game = replace(POKEMON, tcgplayer=None)
        Pricer(self.storage, game, fetch_tcgplayer=self.fetch).refresh_tcgplayer(START)
        self.assertEqual(self.fetches, [])


if __name__ == "__main__":
    unittest.main()
