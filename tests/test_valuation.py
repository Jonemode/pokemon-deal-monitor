import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.games.pokemon.catalog import Edition, PokemonCard, Rarity, Variant
from pokemon_deal_monitor.games.pokemon.game import POKEMON
from pokemon_deal_monitor.pricecharting import PriceChartingError, PriceChartingPrice
from pokemon_deal_monitor.storage import PriceRecord, Storage
from pokemon_deal_monitor.tcgcsv import TcgPrice
from pokemon_deal_monitor.valuation import (
    PRICECHARTING,
    TCGPLAYER,
    Pricer,
    evaluate_auction,
    evaluate_deal,
    evaluate_offer,
    value_card,
)


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

LUGIA = PokemonCard("Lugia", "Neo Genesis", "9/111", Variant.HOLO,
                    Edition.FIRST_EDITION, Rarity.HOLO_RARE)


def record(source, raw=None, grade_5=None, grade_7=None, fetched_at=START):
    return PriceRecord(
        card_identifier=LUGIA.identifier, source=source, fetched_at=fetched_at,
        raw_cents=raw, grade_5_cents=grade_5, grade_7_cents=grade_7,
    )


class TestValueCard(unittest.TestCase):

    def test_pricecharting_is_the_value(self):
        valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=250000),
            TCGPLAYER: record(TCGPLAYER, raw=220000),
        })
        self.assertEqual(valuation.value_cents, 250000)
        self.assertTrue(valuation.confident)
        self.assertEqual(valuation.warnings, ())
        self.assertEqual(valuation.estimates,
                         {PRICECHARTING: 250000, TCGPLAYER: 220000})

    def test_much_lower_tcgplayer_warns_but_stays_confident(self):
        valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=400000),
            TCGPLAYER: record(TCGPLAYER, raw=130000),
        })
        self.assertEqual(valuation.value_cents, 400000)
        self.assertTrue(valuation.confident)
        self.assertEqual(valuation.warnings,
                         ("sources disagree: TCGplayer is 3.1x lower",))

    def test_higher_tcgplayer_does_not_warn(self):
        valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=130000),
            TCGPLAYER: record(TCGPLAYER, raw=400000),
        })
        self.assertEqual(valuation.value_cents, 130000)
        self.assertEqual(valuation.warnings, ())

    def test_pricecharting_alone_is_confident(self):
        valuation = value_card({PRICECHARTING: record(PRICECHARTING, raw=130000)})
        self.assertTrue(valuation.confident)
        self.assertIn("no TCGplayer price", valuation.notes)

    def test_tcgplayer_alone_is_not_confident(self):
        valuation = value_card({TCGPLAYER: record(TCGPLAYER, raw=130000)})
        self.assertEqual(valuation.value_cents, 130000)
        self.assertFalse(valuation.confident)

    def test_capped_at_grade_7(self):
        valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=250000, grade_7=200000),
            TCGPLAYER: record(TCGPLAYER, raw=240000),
        })
        self.assertEqual(valuation.value_cents, 200000)
        self.assertIn("capped at grade 7 price", valuation.notes)

    def test_grade_5_fallback(self):
        valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, grade_5=100000),
        })
        self.assertEqual(valuation.value_cents, 80000)
        self.assertFalse(valuation.confident)

    def test_no_prices(self):
        self.assertIsNone(value_card({}))
        self.assertIsNone(value_card({PRICECHARTING: record(PRICECHARTING)}))


class TestEvaluateDeal(unittest.TestCase):

    def setUp(self):
        self.valuation = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=200000),
            TCGPLAYER: record(TCGPLAYER, raw=200000),
        })

    def test_qualifying_deal(self):
        deal = evaluate_deal(180000, True, self.valuation)
        self.assertAlmostEqual(deal.discount, 0.10)
        self.assertTrue(deal.qualifies)
        self.assertEqual(deal.reasons, ())

    def test_discount_too_small(self):
        deal = evaluate_deal(180001, True, self.valuation)
        self.assertFalse(deal.qualifies)
        self.assertEqual(deal.reasons, ("discount below 10%",))

    def test_unknown_shipping_still_qualifies(self):
        deal = evaluate_deal(100000, False, self.valuation)
        self.assertTrue(deal.qualifies)
        self.assertAlmostEqual(deal.discount, 0.5)

    def test_implausible_discount_on_reprinted_card(self):
        lugia = PokemonCard("Lugia", "Aquapolis", "149/147", Variant.HOLO,
                            Edition.UNLIMITED, Rarity.CRYSTAL)
        at_limit = evaluate_deal(100000, True, self.valuation, POKEMON.rules_for(lugia))
        self.assertTrue(at_limit.qualifies)

        too_cheap = evaluate_deal(99999, True, self.valuation, POKEMON.rules_for(lugia))
        self.assertFalse(too_cheap.qualifies)
        self.assertEqual(
            too_cheap.reasons,
            ("discount above 50%, likely a misrepresented reprint",),
        )

    def test_sets_allowed_over_value(self):
        mewtwo = PokemonCard("Mewtwo", "Wizards Black Star Promos", "3/53",
                             Variant.NORMAL, Edition.UNLIMITED, Rarity.PROMO)
        self.assertTrue(evaluate_deal(210000, True, self.valuation, POKEMON.rules_for(mewtwo)).qualifies)

        too_high = evaluate_deal(210001, True, self.valuation, POKEMON.rules_for(mewtwo))
        self.assertFalse(too_high.qualifies)
        self.assertEqual(too_high.reasons, ("price more than 5% over value",))

        # Other sets still need 10% below value.
        self.assertFalse(evaluate_deal(190000, True, self.valuation, POKEMON.rules_for(LUGIA)).qualifies)

    def test_other_cards_have_no_discount_ceiling(self):
        deal = evaluate_deal(20000, True, self.valuation, POKEMON.rules_for(LUGIA))
        self.assertTrue(deal.qualifies)

    def test_promo_minimum_value(self):
        mewtwo = PokemonCard("Mewtwo", "Wizards Black Star Promos", "3/53",
                             Variant.NORMAL, Edition.UNLIMITED, Rarity.PROMO)
        cheap = value_card({
            PRICECHARTING: record(PRICECHARTING, raw=4999),
        })
        deal = evaluate_deal(1000, True, cheap, POKEMON.rules_for(mewtwo))
        self.assertFalse(deal.qualifies)
        self.assertEqual(deal.reasons, ("value below $50",))

        at_minimum = value_card({PRICECHARTING: record(PRICECHARTING, raw=5000)})
        self.assertTrue(evaluate_deal(4000, True, at_minimum, POKEMON.rules_for(mewtwo)).qualifies)

    def test_offer_on_listing_up_to_10_percent_over_value(self):
        deal = evaluate_offer(220000, 500, self.valuation)
        self.assertTrue(deal.qualifies)
        self.assertAlmostEqual(deal.discount, -0.10)
        # 10% under the $2,000 value, less $5 shipping.
        self.assertEqual(deal.offer_cents, 179500)

    def test_no_offer_on_listing_further_over_value(self):
        deal = evaluate_offer(220001, 500, self.valuation)
        self.assertFalse(deal.qualifies)
        self.assertEqual(deal.reasons, ("price more than 10% over value",))

    def test_no_offer_on_listing_already_below_the_offer(self):
        deal = evaluate_offer(180000, 500, self.valuation)
        self.assertFalse(deal.qualifies)
        self.assertEqual(deal.reasons, ("price already at or below the offer",))

    def test_auction_current_bid_well_below_value(self):
        deal = evaluate_auction(120000, 500, self.valuation)
        self.assertTrue(deal.qualifies)
        self.assertAlmostEqual(deal.discount, 0.40)
        # 10% under the $2,000 value, less $5 shipping.
        self.assertEqual(deal.max_bid_cents, 179500)

    def test_auction_current_bid_not_low_enough(self):
        deal = evaluate_auction(120001, 500, self.valuation)
        self.assertFalse(deal.qualifies)
        self.assertEqual(deal.reasons, ("current bid less than 40% below value",))

    def test_auction_max_bid_capped(self):
        valuation = value_card({PRICECHARTING: record(PRICECHARTING, raw=900000)})
        deal = evaluate_auction(100000, 0, valuation)
        self.assertEqual(deal.max_bid_cents, 500000)

    def test_auctions_of_reprinted_cards_skipped(self):
        lugia = PokemonCard("Lugia", "Aquapolis", "149/147", Variant.HOLO,
                            Edition.UNLIMITED, Rarity.CRYSTAL)
        deal = evaluate_auction(50000, 500, self.valuation, POKEMON.rules_for(lugia))
        self.assertFalse(deal.qualifies)
        self.assertEqual(
            deal.reasons,
            ("auctions skipped, reprints are often sold as this card",),
        )

    def test_value_not_confident(self):
        valuation = value_card({TCGPLAYER: record(TCGPLAYER, raw=200000)})
        deal = evaluate_deal(100000, True, valuation)
        self.assertFalse(deal.qualifies)
        self.assertIn("value not confident", deal.reasons)


class FakePriceCharting:

    def __init__(self, price=None, error=None):
        self.price = price
        self.error = error
        self.calls = []

    def product(self, product_id):
        self.calls.append(product_id)
        if self.error:
            raise self.error
        return self.price


class FakeTcgplayer:

    def __init__(self, prices=None, error=None):
        self.prices = prices or {}
        self.error = error
        self.calls = 0

    def __call__(self, cards, catalog):
        self.calls += 1
        if self.error:
            raise self.error
        return self.prices


PC_PRICE = PriceChartingPrice(
    product_id="6910", product_name="Lugia [1st Edition] #9",
    ungraded_cents=250000, grade_5_cents=300000, grade_7_cents=450000,
    sales_volume=37,
)


class TestPricer(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)
        self.pricecharting = FakePriceCharting(PC_PRICE)
        self.tcgplayer = FakeTcgplayer(
            {LUGIA.identifier: TcgPrice(product_id=86903, market_cents=230000)}
        )

    def pricer(self, product_ids=None):
        return Pricer(
            self.storage,
            replace(POKEMON, cards=[LUGIA]),
            self.pricecharting,
            {LUGIA.identifier: "6910"} if product_ids is None else product_ids,
            fetch_tcgplayer=self.tcgplayer,
        )

    def test_values_from_both_sources(self):
        valuation = self.pricer().valuation(LUGIA, now=START)

        self.assertEqual(valuation.value_cents, 250000)
        self.assertTrue(valuation.confident)
        self.assertEqual(self.pricecharting.calls, ["6910"])
        self.assertEqual(
            self.storage.get_prices(LUGIA.identifier)[PRICECHARTING].sales_volume,
            37,
        )

    def test_prices_are_cached_for_a_day(self):
        pricer = self.pricer()
        pricer.valuation(LUGIA, now=START)
        pricer.valuation(LUGIA, now=START + timedelta(hours=23))
        self.assertEqual(self.tcgplayer.calls, 1)
        self.assertEqual(len(self.pricecharting.calls), 1)

        pricer.valuation(LUGIA, now=START + timedelta(hours=25))
        self.assertEqual(self.tcgplayer.calls, 2)
        self.assertEqual(len(self.pricecharting.calls), 2)

    def test_unmapped_card_uses_tcgplayer_only(self):
        valuation = self.pricer(product_ids={}).valuation(LUGIA, now=START)

        self.assertEqual(self.pricecharting.calls, [])
        self.assertEqual(valuation.estimates, {TCGPLAYER: 230000})
        self.assertFalse(valuation.confident)

    def test_failed_refresh_uses_cached_prices(self):
        self.pricer().valuation(LUGIA, now=START)
        self.pricecharting.error = PriceChartingError(500, "down")
        self.tcgplayer.error = OSError("down")

        valuation = self.pricer().valuation(
            LUGIA, now=START + timedelta(days=2)
        )
        self.assertTrue(valuation.confident)

    def test_prices_past_stale_limit_are_ignored(self):
        self.pricer().valuation(LUGIA, now=START)
        self.pricecharting.error = PriceChartingError(500, "down")
        self.tcgplayer.error = OSError("down")

        valuation = self.pricer().valuation(
            LUGIA, now=START + timedelta(days=8)
        )
        self.assertIsNone(valuation)

    def test_failed_tcgplayer_refresh_retried_hourly(self):
        self.tcgplayer.error = OSError("down")
        pricer = self.pricer()

        pricer.valuation(LUGIA, now=START)
        pricer.valuation(LUGIA, now=START + timedelta(minutes=30))
        self.assertEqual(self.tcgplayer.calls, 1)

        pricer.valuation(LUGIA, now=START + timedelta(minutes=61))
        self.assertEqual(self.tcgplayer.calls, 2)


if __name__ == "__main__":
    unittest.main()
