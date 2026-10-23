import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.games import GAMES
from pokemon_deal_monitor.games.pokemon.game import ALERT_RULES, POKEMON
from pokemon_deal_monitor.storage import PriceRecord, Storage
from pokemon_deal_monitor.valuation import (
    CardRules,
    TCGPLAYER,
    Pricer,
    Valuation,
    evaluate_auction,
    evaluate_deal,
    evaluate_offer,
)


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
        self.assertEqual(rules.min_discount, -0.20)
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
        self.assertEqual(rules.min_discount, -0.20)
        self.assertEqual(rules.min_value_cents, 5000)

    def test_legendary_collection_rules(self):
        charizard = card("pokemon:Legendary Collection:3/110:reverse_holo:unlimited")
        rules = POKEMON.rules_for(charizard)
        value = Valuation(10000, True, {})

        self.assertTrue(evaluate_deal(12000, True, value, rules).qualifies)
        self.assertFalse(evaluate_deal(12001, True, value, rules).qualifies)
        self.assertFalse(evaluate_offer(12001, 0, value, rules).qualifies)

        auction = evaluate_auction(7500, 500, value, rules)
        self.assertTrue(auction.qualifies)
        self.assertEqual(auction.max_bid_cents, 11500)
        self.assertEqual(evaluate_auction(8001, 0, value, rules).reasons,
                         ("current bid less than 20% below value",))

    def test_every_card_alerts_up_to_20_percent_over_and_auctions_20_under(self):
        for c in POKEMON.cards:
            rules = POKEMON.rules_for(c)
            self.assertEqual((rules.min_discount, rules.max_offer_premium,
                              rules.min_auction_discount, rules.max_bid_discount),
                             (-0.20, 0.20, 0.20, -0.20), c.identifier)

    def test_aquapolis_lugia_keeps_its_discount_limit(self):
        rules = POKEMON.rules_for(card("pokemon:Aquapolis:149/147:holo:unlimited"))
        self.assertEqual(rules.min_discount, -0.20)
        self.assertEqual(rules.max_plausible_discount, 0.50)

    def test_default_rules(self):
        charizard = card("pokemon:Base Set:4/102:holo:1st")
        self.assertIs(POKEMON.rules_for(charizard), ALERT_RULES)

    def test_up_to_over_value(self):
        rules = CardRules.up_to_over_value(0.15)
        self.assertEqual((rules.min_discount, rules.max_offer_premium,
                          rules.min_auction_discount, rules.max_bid_discount),
                         (-0.15, 0.15, -0.15, -0.15))


class TestSearchesDue(unittest.TestCase):

    game = replace(POKEMON, searches=["busy", "quiet"],
                   search_intervals={"quiet": timedelta(minutes=15)})

    def due(self, last_searched, now):
        return self.game.searches_due(last_searched, now, poll_interval=300)

    def test_every_search_runs_first(self):
        self.assertEqual(self.due({}, 0), ["busy", "quiet"])

    def test_quiet_search_runs_every_third_poll(self):
        last = {"busy": 0, "quiet": 0}
        self.assertEqual(self.due(last, 300), ["busy"])
        self.assertEqual(self.due(last, 600), ["busy"])
        # A sleep waking slightly early still counts.
        self.assertEqual(self.due(last, 899.5), ["busy", "quiet"])

    def test_pokemon_intervals_name_its_searches(self):
        self.assertLessEqual(set(POKEMON.search_intervals), set(POKEMON.searches))


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
