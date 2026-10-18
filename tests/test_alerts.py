import unittest
from datetime import datetime, timezone

from pokemon_deal_monitor.alerts import describe_card, format_alert, sample_alert, send_alerts
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
ZAPDOS = PokemonCard("Zapdos", "Legendary Collection", "19/110",
                     Variant.REVERSE_HOLO, Edition.UNLIMITED, Rarity.HOLO_RARE)


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

    def test_describe_card(self):
        self.assertEqual(describe_card(LUGIA),
                         "Lugia 9/111 · Neo Genesis · 1st Edition Holo")
        self.assertEqual(describe_card(ZAPDOS),
                         "Zapdos 19/110 · Legendary Collection · Reverse Holo")

    def test_alert_contents(self):
        text = format_alert(candidate("1", 140000))

        self.assertIn("<b>30% below value</b>", text)
        self.assertIn("$1,400.00 + $5.00 shipping = <b>$1,405.00</b>", text)
        self.assertIn("Value $2,000.00 (PriceCharting $2,000.00 · TCGplayer $2,000.00)",
                      text)
        self.assertIn("Condition: Ungraded", text)
        self.assertIn('<a href="https://www.ebay.com/itm/1">View on eBay</a>', text)
        self.assertNotIn("⚠️", text)

    def test_disagreement_warning(self):
        text = format_alert(candidate("1", 140000, tcgplayer=100000))
        self.assertIn("⚠️ sources disagree: TCGplayer is 2.0x lower", text)

    def test_title_is_escaped(self):
        text = format_alert(candidate("1", 140000, title="Lugia <NM> & more"))
        self.assertIn("<i>Lugia &lt;NM&gt; &amp; more</i>", text)

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
        self.assertIn("50% below value", self.sent[0])
        self.assertIn("30% below value", self.sent[1])
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
