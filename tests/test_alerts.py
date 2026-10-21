import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pokemon_deal_monitor.alerts import (
    format_alert,
    format_whole_dollars,
    sample_alert,
    send_alerts,
)
from pokemon_deal_monitor.games.pokemon.catalog import Edition, PokemonCard, Rarity, Variant
from pokemon_deal_monitor.ebay import EbayItem, ItemDetails
from pokemon_deal_monitor.matcher import Match
from pokemon_deal_monitor.monitor import Candidate, PollResult
from pokemon_deal_monitor.storage import PriceRecord, Storage, UpsertResult
from pokemon_deal_monitor.telegram import TelegramError
from pokemon_deal_monitor.valuation import (
    PRICECHARTING,
    TCGPLAYER,
    evaluate_auction,
    evaluate_deal,
    evaluate_offer,
    value_card,
)


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

LUGIA = PokemonCard("Lugia", "Neo Genesis", "9/111", Variant.HOLO,
                    Edition.FIRST_EDITION, Rarity.HOLO_RARE)


def candidate(item_id, price_cents, pricecharting=200000, tcgplayer=200000,
              title="Lugia 9/111 Neo Genesis 1st Edition Holo"):
    prices = {PRICECHARTING: PriceRecord(LUGIA.identifier, PRICECHARTING, START,
                                         raw_cents=pricecharting)}
    if tcgplayer:
        prices[TCGPLAYER] = PriceRecord(LUGIA.identifier, TCGPLAYER, START,
                                        raw_cents=tcgplayer)
    item = EbayItem(item_id=item_id, title=title,
                    url=f"https://www.ebay.com/itm/{item_id}",
                    price_cents=price_cents, currency="USD", shipping_cents=500,
                    condition="Ungraded")
    return Candidate(item, Match(LUGIA, 1.0), UpsertResult.NEW,
                     evaluate_deal(price_cents + 500, True, value_card(prices)))


def auction_candidate(bid_cents, shipping_cents=500, bids=3,
                      reserve_met=None):
    valuation = value_card({PRICECHARTING: PriceRecord(
        LUGIA.identifier, PRICECHARTING, START, raw_cents=200000)})
    item = EbayItem(item_id="1", title="Lugia 9/111 Neo Genesis 1st Edition",
                    url="https://www.ebay.com/itm/1", price_cents=bid_cents,
                    currency="USD", shipping_cents=shipping_cents,
                    auction=True, ends_at=START + timedelta(hours=1, minutes=25),
                    bid_count=bids)
    total = bid_cents + (shipping_cents or 0)
    return Candidate(item, Match(LUGIA, 1.0), UpsertResult.NEW,
                     evaluate_auction(total, shipping_cents or 0, valuation),
                     ItemDetails(reserve_met=reserve_met))


HEADING = '<a href="https://www.ebay.com/itm/1"><b>Lugia · Neo Genesis</b></a>\n'


class TestFormatAlert(unittest.TestCase):

    def test_alert_contents(self):
        self.assertEqual(
            format_alert(candidate("1", 140000)),
            HEADING + "30% off · $1,405 shipped",
        )

    def test_over_value_alert(self):
        c = candidate("1", 205000)
        deal = evaluate_deal(205500, True, c.deal.valuation)
        text = format_alert(Candidate(c.item, c.match, c.result, deal))
        self.assertTrue(text.endswith("\n3% over · $2,055 shipped"))

    def test_unknown_shipping(self):
        c = candidate("1", 140000)
        item = EbayItem(**{**c.item.__dict__, "shipping_cents": None})
        deal = evaluate_deal(140000, False, c.deal.valuation)
        text = format_alert(Candidate(item, c.match, c.result, deal))
        self.assertTrue(text.endswith("\n30% off · $1,400 + ship"))

    def test_best_offer_alert(self):
        valuation = value_card({PRICECHARTING: PriceRecord(
            LUGIA.identifier, PRICECHARTING, START, raw_cents=200000)})
        item = EbayItem(item_id="1", title="Lugia 9/111 Neo Genesis 1st Edition",
                        url="https://www.ebay.com/itm/1", price_cents=209500,
                        currency="USD", shipping_cents=500, best_offer=True)
        candidate = Candidate(item, Match(LUGIA, 1.0), UpsertResult.NEW,
                              evaluate_offer(210000, 500, valuation))
        self.assertEqual(
            format_alert(candidate),
            HEADING + "$2,100 obo · 5% over",
        )

    def test_auction_alert(self):
        self.assertEqual(
            format_alert(auction_candidate(80000), now=START),
            HEADING + "Bid $805 · 1h 25m left · max $1,795",
        )

    def test_overnight_auction_gives_local_end_time(self):
        c = auction_candidate(80000)
        item = EbayItem(**{**c.item.__dict__,
                           "ends_at": START + timedelta(hours=10, minutes=10)})
        text = format_alert(Candidate(item, c.match, c.result, c.deal),
                            now=START, timezone=ZoneInfo("America/Los_Angeles"))
        # 22:10 UTC is 3:10pm Pacific daylight time.
        self.assertTrue(text.endswith("\nBid $805 · ends 3:10pm"
                                      " · max $1,795"), text)

    def test_auction_ending_soon_keeps_time_left(self):
        text = format_alert(auction_candidate(80000), now=START,
                            timezone=ZoneInfo("America/Los_Angeles"))
        self.assertIn("1h 25m left", text)

    def test_auction_alert_without_shipping(self):
        text = format_alert(auction_candidate(80000, None), now=START)
        self.assertTrue(text.endswith(
            "\nBid $800 + ship · 1h 25m left · max $1,800 + ship"
        ))

    def test_whole_dollars(self):
        self.assertEqual(format_whole_dollars(140549), "$1,405")
        self.assertEqual(format_whole_dollars(140550), "$1,406")
        self.assertEqual(format_whole_dollars(140599, round_down=True), "$1,405")

    def test_alerts_are_two_lines(self):
        for text in (format_alert(candidate("1", 140000)),
                     format_alert(auction_candidate(80000), now=START),
                     sample_alert().split("\n", 1)[1]):
            self.assertEqual(len(text.split("\n")), 2, text)

    def test_search_tracking_is_dropped_from_link(self):
        c = candidate("1", 140000)
        url = ("https://www.ebay.com/itm/198707140511?_skw=pokemon+base+set"
               "&hash=item2e43de579f:g:9HoAAeSwXgVqy8VZ")
        c = Candidate(EbayItem(**{**c.item.__dict__, "url": url}),
                      c.match, c.result, c.deal)
        self.assertTrue(format_alert(c).startswith(
            '<a href="https://www.ebay.com/itm/198707140511">'))

    def test_sample_alert(self):
        self.assertIn("Test alert", sample_alert())


class TestSendAlerts(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)
        self.sent = []

    def poll(self, *candidates):
        for c in candidates:
            self.storage.upsert_listing(c.item.to_listing(LUGIA.identifier, 1.0),
                                        now=START)
        return PollResult(items_seen=len(candidates), candidates=list(candidates))

    def test_sends_qualifying_deals_best_first(self):
        poll = self.poll(candidate("small", 140000), candidate("big", 100000),
                         candidate("none", 190000))

        sent = send_alerts(poll, self.storage, self.sent.append, now=START)

        self.assertEqual(sent, 2)
        self.assertIn("50% off", self.sent[0])
        self.assertIn("30% off", self.sent[1])
        self.assertFalse(self.storage.should_alert("big"))
        self.assertTrue(self.storage.should_alert("none"))

    def test_failed_send_is_not_recorded(self):
        poll = self.poll(candidate("1", 100000), candidate("2", 140000))

        def fail(text):
            raise TelegramError(429, "Too Many Requests")

        self.assertEqual(send_alerts(poll, self.storage, fail, now=START), 0)
        self.assertTrue(self.storage.should_alert("1"))
        self.assertTrue(self.storage.should_alert("2"))


if __name__ == "__main__":
    unittest.main()
