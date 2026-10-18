import unittest
from datetime import datetime, timezone

from pokemon_deal_monitor.alerts import format_alert, sample_alert, send_alerts
from pokemon_deal_monitor.catalog import Edition, PokemonCard, Rarity, Variant
from pokemon_deal_monitor.ebay import EbayItem
from pokemon_deal_monitor.matcher import Match
from pokemon_deal_monitor.monitor import Candidate, PollResult
from pokemon_deal_monitor.storage import PriceRecord, Storage, UpsertResult
from pokemon_deal_monitor.telegram import TelegramError
from pokemon_deal_monitor.valuation import PRICECHARTING, TCGPLAYER, evaluate_deal, value_card


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


class TestFormatAlert(unittest.TestCase):

    def test_alert_contents(self):
        self.assertEqual(
            format_alert(candidate("1", 140000)),
            "<b>Lugia</b> · Neo Genesis\n"
            "<b>30% off</b> · $1,405.00 with shipping\n"
            '<a href="https://www.ebay.com/itm/1">https://www.ebay.com/itm/1</a>',
        )

    def test_unknown_shipping(self):
        c = candidate("1", 140000)
        item = EbayItem(**{**c.item.__dict__, "shipping_cents": None})
        deal = evaluate_deal(140000, False, c.deal.valuation)
        text = format_alert(Candidate(item, c.match, c.result, deal))
        self.assertIn("<b>30% off</b> · $1,400.00 + unknown shipping", text)

    def test_url_is_escaped(self):
        c = candidate("1", 140000)
        c = Candidate(EbayItem(**{**c.item.__dict__,
                                  "url": "https://www.ebay.com/itm/1?a=1&b=2"}),
                      c.match, c.result, c.deal)
        self.assertIn('href="https://www.ebay.com/itm/1?a=1&amp;b=2"', format_alert(c))

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
