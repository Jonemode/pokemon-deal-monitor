import json
import unittest
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.ebay import EbayClient, parse_auction_result
from pokemon_deal_monitor.monitor import RESULT_DELAY, fetch_auction_results
from pokemon_deal_monitor.storage import Listing, Storage

from .fakes import CONFIG, FakeTransport


ENDS = datetime(2026, 11, 12, 4, 2, tzinfo=timezone.utc)
AFTER = ENDS + RESULT_DELAY + timedelta(seconds=1)


def ended_item(price="4050.00", bids=23, sold_quantity=1, reserve_met=None):
    item = {
        "price": {"value": price, "currency": "USD"},
        "currentBidPrice": {"value": price, "currency": "USD"},
        "bidCount": bids,
        "buyingOptions": ["AUCTION"],
        "estimatedAvailabilities": [{
            "estimatedAvailabilityStatus": "OUT_OF_STOCK",
            "estimatedSoldQuantity": sold_quantity,
        }],
    }
    if reserve_met is not None:
        item["reservePriceMet"] = reserve_met
    return item


def response(item):
    return 200, json.dumps(item).encode()


class TestParseAuctionResult(unittest.TestCase):

    def test_sold(self):
        result = parse_auction_result(ended_item())
        self.assertEqual((result.final_cents, result.bid_count, result.sold),
                         (405000, 23, True))

    def test_unsold(self):
        self.assertFalse(parse_auction_result(ended_item(sold_quantity=0)).sold)
        self.assertFalse(parse_auction_result(ended_item(reserve_met=False)).sold)

    def test_unknown_when_eBay_doesnt_say(self):
        item = ended_item()
        del item["estimatedAvailabilities"]
        self.assertIsNone(parse_auction_result(item).sold)


class TestFetchAuctionResults(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def add(self, item_id, auction=True, ends_at=ENDS, alerted=True):
        self.storage.upsert_listing(Listing(
            item_id, f"Gengar PSA 6 {item_id}", "https://example.com",
            337700, 795, auction=auction, ends_at=ends_at,
        ), now=ENDS - timedelta(hours=1))
        if alerted:
            self.storage.record_alert(item_id, now=ENDS - timedelta(hours=1))

    def fetch(self, items=None, now=AFTER):
        self.transport = FakeTransport(items=items or {})
        client = EbayClient(CONFIG, transport=self.transport)
        return fetch_auction_results(client, self.storage, now=now)

    def test_stores_the_result_once(self):
        self.add("1")
        self.assertEqual(self.fetch({"1": response(ended_item())}), 1)
        listing = self.storage.get_listing("1")
        self.assertEqual((listing.final_cents, listing.bid_count, listing.sold),
                         (405000, 23, True))
        self.assertEqual(listing.result_fetched_at, AFTER)
        self.assertEqual(self.fetch(), 0)

    def test_only_alerted_auctions_after_they_end(self):
        self.add("not alerted", alerted=False)
        self.add("buy it now", auction=False, ends_at=None)
        self.add("no end", ends_at=None)
        self.add("just ended", ends_at=AFTER - RESULT_DELAY + timedelta(seconds=1))
        self.add("ending", ends_at=AFTER + timedelta(hours=1))
        self.assertEqual(self.fetch(), 0)
        self.assertEqual(self.transport.item_requests, [])

    def test_removed_listings_are_not_looked_up_again(self):
        self.add("1")
        self.assertEqual(self.fetch({"1": (404, b"{}")}), 1)
        listing = self.storage.get_listing("1")
        self.assertIsNone(listing.final_cents)
        self.assertIsNotNone(listing.result_fetched_at)
        self.assertEqual(self.fetch(), 0)

    def test_failures_are_retried(self):
        self.add("1")
        self.assertEqual(self.fetch({"1": (500, b"{}")}), 0)
        self.assertEqual(self.fetch({"1": response(ended_item())}), 1)

    def test_rate_limits_stop_lookups(self):
        self.add("1")
        self.add("2")
        self.fetch({"1": (429, b"{}"), "2": response(ended_item())})
        self.assertEqual(len(self.transport.item_requests), 1)


if __name__ == "__main__":
    unittest.main()
