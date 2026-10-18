import base64
import json
import urllib.parse
import urllib.request
import unittest
from datetime import datetime, timezone
from unittest import mock

from pokemon_deal_monitor.config import EbayConfig
from pokemon_deal_monitor.ebay import (
    USER_AGENT,
    EbayClient,
    EbayError,
    parse_item,
    to_cents,
    urllib_transport,
)

from .fakes import (
    CONFIG,
    FakeTransport,
    auction_summary,
    item_response,
    item_summary,
    search_response,
    token_response,
)


class FakeClock:

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestParsing(unittest.TestCase):

    def test_to_cents(self):
        self.assertEqual(to_cents("1234.56"), 123456)
        self.assertEqual(to_cents("5"), 500)
        self.assertEqual(to_cents("0.995"), 100)

    def test_parse_item(self):
        item = parse_item(item_summary("v1|1|0", "Lugia 9/111", "999.99", "4.50"))

        self.assertEqual(item.item_id, "v1|1|0")
        self.assertEqual(item.price_cents, 99999)
        self.assertEqual(item.shipping_cents, 450)
        self.assertEqual(item.condition, "Ungraded")
        self.assertEqual(item.image_url, "https://i.ebayimg.com/v1|1|0.jpg")

    def test_cheapest_shipping_option(self):
        summary = item_summary("1", "Lugia")
        summary["shippingOptions"].append({
            "shippingCostType": "FIXED",
            "shippingCost": {"value": "1.25", "currency": "USD"},
        })
        self.assertEqual(parse_item(summary).shipping_cents, 125)

    def test_unknown_shipping(self):
        item = parse_item(item_summary("1", "Lugia", shipping=None))
        self.assertIsNone(item.shipping_cents)
        self.assertEqual(item.to_listing().shipping_cents, 0)
        self.assertFalse(item.to_listing().shipping_known)

    def test_listing_keeps_condition(self):
        item = parse_item(item_summary("1", "Lugia", condition="Graded"))
        listing = item.to_listing()
        self.assertEqual(listing.condition, "Graded")
        self.assertTrue(listing.shipping_known)

    def test_missing_price_is_skipped(self):
        summary = item_summary("1", "Lugia")
        del summary["price"]
        self.assertIsNone(parse_item(summary))


class TestUrllibTransport(unittest.TestCase):

    def test_sets_user_agent(self):
        request = urllib.request.Request("https://example.invalid/")
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            urllib_transport(request)

        self.assertEqual(request.get_header("User-agent"), USER_AGENT)

    def test_keeps_existing_user_agent(self):
        request = urllib.request.Request(
            "https://example.invalid/", headers={"User-Agent": "custom"}
        )
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            urllib_transport(request)

        self.assertEqual(request.get_header("User-agent"), "custom")


class TestEbayClient(unittest.TestCase):

    def test_token_request(self):
        transport = FakeTransport()
        EbayClient(CONFIG, transport=transport).access_token()

        (request,) = transport.token_requests
        self.assertEqual(
            request.full_url, "https://api.ebay.com/identity/v1/oauth2/token"
        )
        expected = base64.b64encode(b"test-app:test-cert").decode()
        self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
        body = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(body["grant_type"], ["client_credentials"])

    def test_token_is_cached_until_expiry(self):
        transport = FakeTransport()
        clock = FakeClock()
        client = EbayClient(CONFIG, transport=transport, clock=clock)

        client.access_token()
        clock.now += 7000
        client.access_token()
        self.assertEqual(len(transport.token_requests), 1)

        # Within the refresh margin of the 7200 second expiry.
        clock.now += 150
        client.access_token()
        self.assertEqual(len(transport.token_requests), 2)

    def test_token_failure(self):
        transport = FakeTransport(token=(401, b'{"error": "invalid_client"}'))
        with self.assertRaises(EbayError) as context:
            EbayClient(CONFIG, transport=transport).access_token()
        self.assertEqual(context.exception.status, 401)

    def test_search_request(self):
        transport = FakeTransport({
            "pokemon aquapolis": search_response(
                item_summary("1", "Umbreon H29/H32 Aquapolis Holo"),
            ),
        })
        items = EbayClient(CONFIG, transport=transport).search("pokemon aquapolis")

        self.assertEqual([item.title for item in items],
                         ["Umbreon H29/H32 Aquapolis Holo"])

        (request,) = transport.search_requests
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(params["category_ids"], ["183454"])
        self.assertEqual(params["sort"], ["newlyListed"])
        self.assertIn("buyingOptions:{FIXED_PRICE}", params["filter"][0])
        self.assertIn("price:[..5000]", params["filter"][0])
        self.assertNotIn("aspect_filter", params)
        self.assertEqual(request.get_header("Authorization"), "Bearer token-1")
        self.assertEqual(
            request.get_header("X-ebay-c-marketplace-id"), "EBAY_US"
        )

    def test_search_with_no_results(self):
        transport = FakeTransport({"q": (200, b"{}")})
        self.assertEqual(EbayClient(CONFIG, transport=transport).search("q"), [])

    def test_search_retries_once_after_401(self):
        transport = FakeTransport({
            "q": [(401, b"expired"), search_response(item_summary("1", "Lugia"))],
        })
        items = EbayClient(CONFIG, transport=transport).search("q")

        self.assertEqual(len(items), 1)
        self.assertEqual(len(transport.token_requests), 2)

    def test_item_details(self):
        transport = FakeTransport(items={
            "v1|123|0": item_response("Lightly played (Excellent)", "English"),
        })
        details = EbayClient(CONFIG, transport=transport).item_details("v1|123|0")

        self.assertEqual(details.card_condition, "Lightly played (Excellent)")
        self.assertEqual(details.language, "English")
        self.assertTrue(transport.item_requests[0].full_url.endswith(
            "/buy/browse/v1/item/v1%7C123%7C0"
        ))

    def test_item_details_left_blank(self):
        transport = FakeTransport(items={"1": item_response(None, None)})
        details = EbayClient(CONFIG, transport=transport).item_details("1")
        self.assertIsNone(details.card_condition)
        self.assertIsNone(details.language)

    def test_item_details_from_another_ebay_site(self):
        item = {
            "conditionDescriptors": [{
                "name": "Condizione della carta",
                "values": [{"content": "Heavily Played (Poor)"}],
            }],
            "localizedAspects": [
                {"type": "STRING", "name": "Lingua", "value": "Italiano"},
            ],
        }
        transport = FakeTransport(items={"1": (200, json.dumps(item).encode())})
        details = EbayClient(CONFIG, transport=transport).item_details("1")
        self.assertEqual(details.card_condition, "Heavily Played (Poor)")
        self.assertEqual(details.language, "Italiano")

    def test_grade_descriptors_are_not_card_condition(self):
        item = {"conditionDescriptors": [
            {"name": "Professional Grader", "values": [{"content": "PSA"}]},
            {"name": "Grade", "values": [{"content": "9"}]},
        ]}
        transport = FakeTransport(items={"1": (200, json.dumps(item).encode())})
        details = EbayClient(CONFIG, transport=transport).item_details("1")
        self.assertIsNone(details.card_condition)

    def test_auction_search(self):
        transport = FakeTransport({"auction:q": search_response(
            auction_summary("1", "Lugia", bid="250.00", bids=4,
                            ends="2026-10-17T13:30:00.000Z"),
        )})
        (item,) = EbayClient(CONFIG, transport=transport).search(
            "q", auctions_ending_before=datetime(2026, 10, 17, 14, 0,
                                                 tzinfo=timezone.utc),
        )

        params = urllib.parse.parse_qs(
            urllib.parse.urlsplit(transport.search_requests[0].full_url).query
        )
        self.assertEqual(params["filter"][0],
                         "buyingOptions:{AUCTION},"
                         "itemEndDate:[..2026-10-17T14:00:00Z],"
                         "price:[..5000],priceCurrency:USD")
        self.assertEqual(params["sort"][0], "endingSoonest")
        self.assertTrue(item.auction)
        self.assertEqual(item.price_cents, 25000)
        self.assertEqual(item.bid_count, 4)
        self.assertEqual(item.ends_at,
                         datetime(2026, 10, 17, 13, 30, tzinfo=timezone.utc))

    def test_auction_current_bid_not_buy_it_now_price(self):
        summary = auction_summary("1", "Lugia", bid="250.00")
        summary["price"] = {"value": "900.00", "currency": "USD"}
        transport = FakeTransport({"auction:q": search_response(summary)})
        (item,) = EbayClient(CONFIG, transport=transport).search(
            "q", auctions_ending_before=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        self.assertEqual(item.price_cents, 25000)

    def test_reserve_met(self):
        transport = FakeTransport(items={"1": item_response(reserve_met=False),
                                         "2": item_response()})
        client = EbayClient(CONFIG, transport=transport)
        self.assertIs(client.item_details("1").reserve_met, False)
        self.assertIsNone(client.item_details("2").reserve_met)

    def test_search_failure(self):
        transport = FakeTransport({"q": (429, b"rate limited")})
        with self.assertRaises(EbayError) as context:
            EbayClient(CONFIG, transport=transport).search("q")
        self.assertEqual(context.exception.status, 429)

    def test_sandbox_host(self):
        transport = FakeTransport()
        config = EbayConfig("app", "cert", environment="sandbox")
        EbayClient(config, transport=transport).access_token()
        self.assertTrue(
            transport.token_requests[0].full_url.startswith(
                "https://api.sandbox.ebay.com/"
            )
        )

    def test_expires_in_drives_refresh(self):
        transport = FakeTransport(token=token_response(expires_in=120))
        clock = FakeClock()
        client = EbayClient(CONFIG, transport=transport, clock=clock)

        client.access_token()
        clock.now += 61
        client.access_token()
        self.assertEqual(len(transport.token_requests), 2)


if __name__ == "__main__":
    unittest.main()
