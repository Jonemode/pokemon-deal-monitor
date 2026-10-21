import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.alerts import format_watch_alert, send_watch_alerts
from pokemon_deal_monitor.ebay import EbayClient
from pokemon_deal_monitor.storage import Storage
from pokemon_deal_monitor.watch import WATCHES, WatchHit, poll_watches

from .fakes import CONFIG, FakeTransport, auction_summary, item_summary, search_response


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
CORNHOLIO = WATCHES[0]
FLEER = "1995 FLEER ULTRA MTV ANIMATION #29 CORNHOLIO PSA 10"


class TestWatchMatching(unittest.TestCase):

    def test_cornholio_titles(self):
        for title in (FLEER, "1995 Ultra MTV Animation Cornholio #29 Beavis"):
            self.assertTrue(CORNHOLIO.matches(title), title)
        for title in (
            "1994 Topps MTV Beavis And Butthead Trading Cards I Am Cornholio",
            "Vintage MTV 2011 Beavis Butthead I Am The Great Cornholio Pinback Button",
            "1995 Fleer Ultra MTV Animation #30 Beavis",
            "BEAVIS and BUTTHEAD Sericel The Great Cornholio MTV Sericel Animation Art Cel",
        ):
            self.assertFalse(CORNHOLIO.matches(title), title)


class TestPollWatches(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def poll(self, *summaries, now=START):
        self.transport = FakeTransport({"cornholio (fleer, ultra, animation)": search_response(*summaries)})
        client = EbayClient(CONFIG, transport=self.transport)
        return poll_watches(client, self.storage, now=now)

    def test_searches_every_category_at_any_price(self):
        self.poll()
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(
            self.transport.search_requests[0].full_url).query)
        self.assertNotIn("category_ids", params)
        self.assertEqual(params["filter"], ["buyingOptions:{FIXED_PRICE|AUCTION}"])

    def test_new_matching_listings_alert_once(self):
        result = self.poll(item_summary("1", FLEER, "3499.99"),
                           item_summary("2", "1994 Topps MTV Cornholio"))
        self.assertEqual([h.item.item_id for h in result.hits], ["1"])
        self.assertEqual(self.storage.get_listing("1").card_identifier,
                         CORNHOLIO.identifier)

        sent = []
        send_watch_alerts(result.hits, self.storage, sent.append, now=START)
        self.assertEqual(len(sent), 1)

        later = self.poll(item_summary("1", FLEER, "3499.99"),
                          now=START + timedelta(minutes=15))
        self.assertEqual(later.hits, [])

    def test_unsent_alert_is_retried(self):
        self.poll(item_summary("1", FLEER))
        later = self.poll(item_summary("1", FLEER), now=START + timedelta(minutes=15))
        self.assertEqual(len(later.hits), 1)

    def test_failed_search(self):
        self.transport = FakeTransport({"cornholio (fleer, ultra, animation)": (500, b"error")})
        result = poll_watches(EbayClient(CONFIG, transport=self.transport),
                              self.storage)
        self.assertEqual(len(result.errors), 1)


class TestWatchAlert(unittest.TestCase):

    def poll_item(self, summary):
        transport = FakeTransport({"cornholio (fleer, ultra, animation)": search_response(summary)})
        with Storage(":memory:") as storage:
            return poll_watches(EbayClient(CONFIG, transport=transport),
                                storage).hits[0].item

    def test_listing(self):
        item = self.poll_item(item_summary("1", FLEER, "3499.99", "5.00"))
        self.assertEqual(
            format_watch_alert(WatchHit(CORNHOLIO, item)),
            '<a href="https://www.ebay.com/itm/1">'
            "<b>Cornholio · 1995 Fleer Ultra MTV Animation</b></a>\n"
            "Listed $3,505 shipped",
        )

    def test_auction(self):
        item = self.poll_item(auction_summary("1", FLEER, bid="20.00", shipping=None,
                                              ends="2026-10-17T13:30:00.000Z"))
        self.assertTrue(format_watch_alert(WatchHit(CORNHOLIO, item), now=START)
                        .endswith("\nBid $20 + ship · 1h 30m left"))


if __name__ == "__main__":
    unittest.main()
