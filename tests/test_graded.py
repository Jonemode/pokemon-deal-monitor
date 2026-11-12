import unittest
import urllib.parse
from datetime import datetime, timezone

from pokemon_deal_monitor.alerts import format_alert
from pokemon_deal_monitor.ebay import EbayClient
from pokemon_deal_monitor.games.pokemon.game import GRADED_RULES, POKEMON
from pokemon_deal_monitor.graded import Grade, parse_grade, strip_grade
from pokemon_deal_monitor.monitor import poll_once
from pokemon_deal_monitor.pricecharting import parse_product
from pokemon_deal_monitor.storage import PriceRecord, Storage
from pokemon_deal_monitor.valuation import PRICECHARTING, value_graded

from .fakes import CONFIG, FakeTransport, auction_summary, item_summary, search_response


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
CHARMANDER = next(c for c in POKEMON.cards
                  if c.identifier == "pokemon:Legendary Collection:70/110:reverse_holo:unlimited")
SLAB = "2002 POKEMON LEGENDARY COLLECTION #70 CHARMANDER-REVERSE FOIL PSA {}"
GRADE_PRICES = {"grade_4_cents": 40000, "grade_5_cents": 50000,
                "grade_6_cents": 60000, "grade_7_cents": 70000,
                "grade_8_cents": 80000}
QUERY = "pokemon legendary collection"


def prices(**overrides):
    return {PRICECHARTING: PriceRecord(
        CHARMANDER.identifier, PRICECHARTING, START, raw_cents=1000,
        **{**GRADE_PRICES, **overrides})}


class GradedPricer:
    """Values Charmander at its grade prices, and its raw copy at $10."""

    game = POKEMON

    def __init__(self, **overrides):
        self.prices = prices(**overrides)

    def valuation(self, card, now=None):
        raise AssertionError("graded listings use graded_valuation")

    def graded_valuation(self, card, grade, now=None):
        return value_graded(self.prices, grade)


class TestParseGrade(unittest.TestCase):

    def test_grades_as_titles_write_them(self):
        for title, expected in (
            ("PSA 7 Charmander", Grade("PSA", "7", 7)),
            ("Charmander PSA7 NM", Grade("PSA", "7", 7)),
            ("Charmander PSA-5", Grade("PSA", "5", 5)),
            ("Charmander BGS 7.5", Grade("BGS", "7.5", 7)),
            ("Beckett 6 Charmander", Grade("BGS", "6", 6)),
            ("Graded CGC 4 Charmander", Grade("CGC", "4", 4)),
            ("SGC 9 Charmander", Grade("SGC", "9", 9)),
            ("Charmander BGS 8.5", Grade("BGS", "8.5", 8)),
        ):
            self.assertEqual(parse_grade(title), expected, title)

    def test_no_single_priced_grade(self):
        for title in (
            "Charmander Reverse Holo",
            # Half grades below 7 have no price of their own.
            "Charmander BGS 6.5",
            "Charmander CGC 9.5",
            # Two slabs.
            "Charmander PSA 7 and Charizard PSA 5",
        ):
            self.assertIsNone(parse_grade(title), title)

    def test_same_grade_twice_is_one(self):
        self.assertEqual(parse_grade("PSA 7 Charmander PSA 7 NM").label, "7")

    def test_strip_leaves_the_card(self):
        self.assertEqual(strip_grade("Graded PSA 7 Charmander 70/110 Slab").split(),
                         ["Charmander", "70/110"])


class TestValueGraded(unittest.TestCase):

    def test_uses_the_grades_price_alone(self):
        for grade in (4, 5, 6, 7, 8):
            valuation = value_graded(prices(), grade)
            self.assertEqual(valuation.value_cents, grade * 10000)
            self.assertTrue(valuation.confident)

    def test_none_without_the_grades_price(self):
        self.assertIsNone(value_graded(prices(grade_4_cents=None), 4))
        self.assertIsNone(value_graded(prices(), 9))
        self.assertIsNone(value_graded({}, 5))

    def test_grades_4_and_8_from_pricecharting(self):
        price = parse_product({"id": 1, "condition-14-price": 4000,
                               "new-price": 8000})
        self.assertEqual((price.grade_4_cents, price.grade_8_cents), (4000, 8000))

    def test_grades_4_and_8_are_stored(self):
        with Storage(":memory:") as storage:
            storage.save_price(prices()[PRICECHARTING])
            stored = storage.get_prices(CHARMANDER.identifier)[PRICECHARTING]
            self.assertEqual((stored.grade_4_cents, stored.grade_8_cents),
                             (40000, 80000))


class TestGradedPolls(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def poll(self, *summaries, pricer=None, auctions=False):
        key = ("auction:" if auctions else "") + QUERY
        self.transport = FakeTransport({key: search_response(*summaries)})
        client = EbayClient(CONFIG, transport=self.transport)
        return poll_once(client, self.storage, POKEMON, queries=[QUERY], now=START,
                         pricer=pricer or GradedPricer(), auctions=auctions)

    def graded(self, item_id, grade, price, shipping="0.00"):
        return item_summary(item_id, SLAB.format(grade), price, shipping,
                            condition="Graded")

    def test_searches_graded_listings_only(self):
        self.poll()
        url = urllib.parse.unquote(self.transport.search_requests[0].full_url)
        self.assertIn("conditionIds:{2750}", url)

    def test_alerts_up_to_5_percent_over_the_grades_price(self):
        poll = self.poll(
            self.graded("1", 5, "525.00"),   # 5% over $500: alerts
            self.graded("2", 5, "525.01"),   # just over
            self.graded("3", 7, "400.00"),   # well under $700
            self.graded("4", 8, "840.00"),   # 5% over $800
            self.graded("5", 8, "841.00"),
        )
        qualifies = {c.item.item_id: c.deal.qualifies for c in poll.candidates}
        self.assertEqual(qualifies, {"1": True, "2": False, "3": True, "4": True,
                                     "5": False})
        self.assertEqual(poll.candidates[0].grade, Grade("PSA", "5", 5))

    def test_never_valued_at_the_ungraded_price(self):
        # $10 raw, but a PSA 6 copy at $590 is a deal against $600.
        (candidate,) = self.poll(self.graded("1", 6, "590.00")).candidates
        self.assertEqual(candidate.deal.valuation.value_cents, 60000)
        self.assertTrue(candidate.deal.qualifies)

    def test_grades_without_a_price_are_not_valued(self):
        poll = self.poll(self.graded("1", 9, "1.00"),
                         pricer=GradedPricer(grade_4_cents=None))
        self.assertIsNone(poll.candidates[0].deal)
        poll = self.poll(self.graded("2", 4, "1.00"),
                         pricer=GradedPricer(grade_4_cents=None))
        self.assertIsNone(poll.candidates[0].deal)

    def test_only_legendary_collection_cards(self):
        poll = self.poll(item_summary(
            "1", "1999 Pokemon Base Set Charizard 4/102 Holo PSA 7", "1.00",
            condition="Graded"))
        self.assertEqual(poll.candidates, [])

    def test_ungraded_listing_in_a_graded_search_is_skipped(self):
        poll = self.poll(item_summary("1", SLAB.format(5), "1.00",
                                      condition="Ungraded"))
        self.assertEqual(poll.candidates, [])

    def test_ungraded_searches_still_skip_graded_listings(self):
        self.transport = FakeTransport({"lc": search_response(
            self.graded("1", 5, "1.00"))})
        client = EbayClient(CONFIG, transport=self.transport)
        poll = poll_once(client, self.storage, POKEMON, queries=["lc"],
                         now=START, pricer=GradedPricer())
        self.assertEqual(poll.candidates, [])

    def test_auctions(self):
        summary = auction_summary("1", SLAB.format(7), bid="500.00",
                                  shipping="0.00")
        summary["condition"] = "Graded"
        (candidate,) = self.poll(summary, auctions=True).candidates
        # A current bid 20% or more below $700, and a max bid at it.
        self.assertTrue(candidate.deal.qualifies)
        self.assertEqual(candidate.deal.max_bid_cents, 70000)

    def test_alert_names_the_grade(self):
        (candidate,) = self.poll(self.graded("1", 5, "500.00")).candidates
        heading = format_alert(candidate, START).split("\n")[0]
        self.assertIn("Charmander · Legendary Collection · reverse · PSA 5", heading)


class TestGradedRules(unittest.TestCase):

    def test_5_percent_over(self):
        self.assertEqual(GRADED_RULES.min_discount, -0.05)
        self.assertEqual(GRADED_RULES.max_offer_premium, 0.05)
        self.assertEqual(GRADED_RULES.max_bid_discount, 0.0)

    def test_legendary_collection_is_searched_graded(self):
        self.assertEqual(POKEMON.graded_searches, [QUERY])
        self.assertEqual(POKEMON.graded_sets, {"Legendary Collection"})
