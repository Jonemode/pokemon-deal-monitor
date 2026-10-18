import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from pokemon_deal_monitor.catalog import Edition, PokemonCard, Rarity, Variant
from pokemon_deal_monitor.pricecharting import (
    PriceChartingClient,
    PriceChartingError,
    load_product_ids,
    parse_product,
    search_query,
    select_products,
)


LUGIA = PokemonCard("Lugia", "Neo Genesis", "9/111", Variant.HOLO,
                    Edition.FIRST_EDITION, Rarity.HOLO_RARE)
UMBREON = PokemonCard("Umbreon", "Aquapolis", "H29/H32", Variant.HOLO,
                      Edition.UNLIMITED, Rarity.HOLO_RARE)
MEW_SI = PokemonCard("Mew", "Southern Islands", "1/18", Variant.REVERSE_HOLO,
                     Edition.UNLIMITED, Rarity.PROMO)
CHARIZARD_BASE = PokemonCard("Charizard", "Base Set", "4/102", Variant.HOLO,
                             Edition.FIRST_EDITION, Rarity.HOLO_RARE)
CHARIZARD_LC = PokemonCard("Charizard", "Legendary Collection", "3/110",
                           Variant.REVERSE_HOLO, Edition.UNLIMITED,
                           Rarity.HOLO_RARE)


def pc_product(product_id, console, name, tcg_id=None):
    return {"id": product_id, "console-name": console,
            "product-name": name, "tcg-id": tcg_id}


CLOUDFLARE_PAGE = b"<!DOCTYPE html><title>Just a moment...</title>"
EMPTY_SEARCH = {"status": "success", "products": []}


class FakeTransport:

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, payload = response
        if isinstance(payload, bytes):
            return status, payload
        return status, json.dumps(payload).encode()


class FakeClock:

    def __init__(self):
        self.now = 100.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class TestParsing(unittest.TestCase):

    def test_parse_product(self):
        price = parse_product({
            "id": "6910", "product-name": "Lugia [1st Edition] #9",
            "loose-price": 250000, "condition-15-price": 300000,
            "cib-price": 450000, "sales-volume": "37",
        })
        self.assertEqual(price.product_id, "6910")
        self.assertEqual(price.ungraded_cents, 250000)
        self.assertEqual(price.grade_5_cents, 300000)
        self.assertEqual(price.grade_7_cents, 450000)
        self.assertEqual(price.sales_volume, 37)

    def test_missing_prices(self):
        price = parse_product({"id": 1, "loose-price": ""})
        self.assertIsNone(price.ungraded_cents)
        self.assertIsNone(price.grade_7_cents)

    def test_load_product_ids_skips_unmapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ids.json"
            path.write_text(json.dumps({
                "a": {"product_id": "1", "status": "matched"},
                "b": {"product_id": None, "status": "unresolved"},
            }))
            self.assertEqual(load_product_ids(path), {"a": "1"})
            self.assertEqual(load_product_ids(Path(directory) / "none"), {})


class TestProductSelection(unittest.TestCase):

    def test_search_query(self):
        self.assertEqual(search_query(LUGIA), "Lugia Neo Genesis #9")
        self.assertEqual(search_query(UMBREON), "Umbreon Aquapolis #H29")

    def test_first_edition_chosen_over_unlimited(self):
        products = [
            pc_product(1, "Pokemon Neo Genesis", "Lugia #9"),
            pc_product(2, "Pokemon Neo Genesis", "Lugia [1st Edition] #9"),
            pc_product(3, "Pokemon Japanese Neo Genesis", "Lugia [1st Edition] #9"),
            pc_product(4, "Pokemon Neo Genesis", "Lugia [1st Edition Error] #9"),
        ]
        self.assertEqual([p["id"] for p in select_products(LUGIA, products)], [2])

    def test_reverse_holo_required(self):
        products = [
            pc_product(1, "Pokemon Legendary Collection", "Charizard #3"),
            pc_product(2, "Pokemon Legendary Collection", "Charizard [Reverse Holo] #3"),
        ]
        self.assertEqual(
            [p["id"] for p in select_products(CHARIZARD_LC, products)], [2]
        )

    def test_non_english_consoles_excluded(self):
        products = [
            pc_product(1, "Pokemon Base Set", "Charizard [1st Edition] #4"),
            pc_product(2, "Pokemon Korean Base Set", "Charizard [1st Edition] #4"),
            pc_product(3, "Pokemon Chinese Base Set", "Charizard [1st Edition] #4"),
        ]
        self.assertEqual(
            [p["id"] for p in select_products(CHARIZARD_BASE, products)], [1]
        )

    def test_single_printing_set_needs_no_reverse_tag(self):
        products = [
            pc_product(1, "Pokemon Southern Islands", "Mew #1"),
            pc_product(2, "Pokemon Japanese Southern Islands", "Mew #151"),
            pc_product(3, "Pokemon Southern Islands", "Mew [Error] #1"),
        ]
        self.assertEqual([p["id"] for p in select_products(MEW_SI, products)], [1])

    def test_number_and_name_must_match(self):
        products = [
            pc_product(1, "Pokemon Aquapolis", "Umbreon #H30"),
            pc_product(2, "Pokemon Aquapolis", "Espeon #H29"),
            pc_product(3, "Pokemon Aquapolis", "Umbreon #H29"),
        ]
        self.assertEqual([p["id"] for p in select_products(UMBREON, products)], [3])

    def test_tcg_id_breaks_ties(self):
        products = [
            pc_product(1, "Pokemon Neo Genesis", "Lugia [1st Edition] #9", tcg_id=111),
            pc_product(2, "Pokemon Neo Genesis", "Lugia [1st Edition] #9", tcg_id=86903),
        ]
        matches = select_products(LUGIA, products, tcg_product_id=86903)
        self.assertEqual([p["id"] for p in matches], [2])


class TestClient(unittest.TestCase):

    def test_product_request(self):
        transport = FakeTransport((200, {
            "status": "success", "id": "6910", "loose-price": 250000,
        }))
        price = PriceChartingClient("tok", transport=transport).product("6910")

        self.assertEqual(price.ungraded_cents, 250000)
        params = urllib.parse.parse_qs(
            urllib.parse.urlsplit(transport.requests[0].full_url).query
        )
        self.assertEqual(params, {"t": ["tok"], "id": ["6910"]})

    def test_error_response(self):
        transport = FakeTransport(
            (401, {"status": "error", "error-message": "Invalid token"})
        )
        with self.assertRaises(PriceChartingError) as context:
            PriceChartingClient("bad", transport=transport).product("1")
        self.assertEqual(context.exception.status, 401)
        self.assertIn("Invalid token", str(context.exception))

    def test_calls_are_spaced_one_second_apart(self):
        clock = FakeClock()
        transport = FakeTransport(
            (200, {"status": "success", "products": []}),
            (200, {"status": "success", "products": []}),
        )
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep
        )
        client.search("a")
        clock.now += 0.25
        client.search("b")

        self.assertEqual(clock.slept, [0.75])

    def test_custom_spacing(self):
        clock = FakeClock()
        transport = FakeTransport((200, EMPTY_SEARCH), (200, EMPTY_SEARCH))
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep,
            min_seconds_between_calls=3.0,
        )
        client.search("a")
        client.search("b")

        self.assertEqual(clock.slept, [3.0])

    def test_rate_limit_is_retried_with_backoff(self):
        clock = FakeClock()
        transport = FakeTransport(
            (429, CLOUDFLARE_PAGE), (429, CLOUDFLARE_PAGE), (200, EMPTY_SEARCH)
        )
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep
        )

        self.assertEqual(client.search("a"), [])
        self.assertEqual(clock.slept, [30.0, 60.0])
        self.assertEqual(len(transport.requests), 3)

    def test_rate_limit_gives_up_after_retries(self):
        clock = FakeClock()
        transport = FakeTransport(*[(429, CLOUDFLARE_PAGE)] * 5)
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep
        )

        with self.assertRaises(PriceChartingError) as context:
            client.search("a")
        self.assertEqual(context.exception.status, 429)
        self.assertIn("rate limited", str(context.exception))
        self.assertEqual(clock.slept, [30.0, 60.0, 120.0, 240.0])

    def test_dropped_connection_is_retried(self):
        clock = FakeClock()
        transport = FakeTransport((200, EMPTY_SEARCH))
        transport.responses.insert(0, OSError("EOF occurred in violation of protocol"))
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep
        )

        self.assertEqual(client.search("a"), [])
        self.assertEqual(clock.slept, [30.0])

    def test_repeated_dropped_connections_raise(self):
        clock = FakeClock()
        transport = FakeTransport(*[OSError("connection reset")] * 5)
        client = PriceChartingClient(
            "tok", transport=transport, clock=clock, sleep=clock.sleep
        )

        with self.assertRaises(OSError):
            client.search("a")
        self.assertEqual(clock.slept, [30.0, 60.0, 120.0, 240.0])

    def test_other_errors_are_not_retried(self):
        transport = FakeTransport((500, b"oops"))
        with self.assertRaises(PriceChartingError) as context:
            PriceChartingClient("tok", transport=transport).search("a")
        self.assertEqual(context.exception.status, 500)
        self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
