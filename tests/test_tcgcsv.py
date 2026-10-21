import unittest

from pokemon_deal_monitor.games.pokemon.catalog import Edition, PokemonCard, Rarity, Variant
from pokemon_deal_monitor.tcgcsv import TCGCSV_URL, fetch_prices, sub_type_name


LUGIA = PokemonCard("Lugia", "Neo Genesis", "9/111", Variant.HOLO,
                    Edition.FIRST_EDITION, Rarity.HOLO_RARE)
UMBREON = PokemonCard("Umbreon", "Aquapolis", "H29/H32", Variant.HOLO,
                      Edition.UNLIMITED, Rarity.HOLO_RARE)
ZAPDOS = PokemonCard("Zapdos", "Legendary Collection", "19/110",
                     Variant.REVERSE_HOLO, Edition.UNLIMITED, Rarity.HOLO_RARE)


def product(product_id, number):
    return {
        "productId": product_id,
        "extendedData": [{"name": "Number", "value": number}],
    }


def price(product_id, sub_type, market):
    return {"productId": product_id, "subTypeName": sub_type,
            "marketPrice": market, "lowPrice": 1.0}


class FakeTcgcsv:

    def __init__(self, groups):
        self.groups = groups
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        group_id, kind = url.removeprefix(TCGCSV_URL + "/").split("/")
        return {"results": self.groups[int(group_id)][kind]}


class TestTcgcsv(unittest.TestCase):

    def test_sub_type_names(self):
        self.assertEqual(sub_type_name(LUGIA), "1st Edition Holofoil")
        self.assertEqual(sub_type_name(UMBREON), "Holofoil")
        self.assertEqual(sub_type_name(ZAPDOS), "Reverse Holofoil")

    def test_prices_by_number_and_printing(self):
        fetch = FakeTcgcsv({
            1396: {
                "products": [product(86903, "009/111")],
                "prices": [
                    price(86903, "1st Edition Holofoil", 1300.0),
                    price(86903, "Unlimited Holofoil", 534.65),
                ],
            },
            1397: {
                "products": [product(90139, "H29/H32")],
                "prices": [price(90139, "Holofoil", 1252.62)],
            },
        })
        prices = fetch_prices([LUGIA, UMBREON], fetch=fetch)

        self.assertEqual(prices[LUGIA.identifier].market_cents, 130000)
        self.assertEqual(prices[UMBREON.identifier].market_cents, 125262)
        self.assertEqual(prices[UMBREON.identifier].product_id, 90139)

    def test_missing_printing_or_market_price(self):
        fetch = FakeTcgcsv({
            1396: {
                "products": [product(86903, "009/111")],
                "prices": [price(86903, "Unlimited Holofoil", 534.65)],
            },
            1374: {
                "products": [product(84212, "019/110")],
                "prices": [price(84212, "Reverse Holofoil", None)],
            },
        })
        self.assertEqual(fetch_prices([LUGIA, ZAPDOS], fetch=fetch), {})

    def test_duplicate_numbers_are_skipped(self):
        fetch = FakeTcgcsv({
            1396: {
                "products": [product(1, "009/111"), product(2, "009/111")],
                "prices": [
                    price(1, "1st Edition Holofoil", 1300.0),
                    price(2, "1st Edition Holofoil", 900.0),
                ],
            },
        })
        self.assertEqual(fetch_prices([LUGIA], fetch=fetch), {})

    def test_special_versions_are_ignored(self):
        rapidash = PokemonCard("Rapidash", "Wizards Black Star Promos", "51/53",
                               Variant.NORMAL, Edition.UNLIMITED, Rarity.PROMO)
        fetch = FakeTcgcsv({
            1418: {
                "products": [
                    {**product(88575, "51/53"), "name": "Rapidash (51)"},
                    {**product(244347, "51/53"),
                     "name": "Rapidash [Pokemon Center NY]"},
                ],
                "prices": [price(88575, "Normal", 55.71),
                           price(244347, "Normal", 119.87)],
            },
        })
        prices = fetch_prices([rapidash], fetch=fetch)
        self.assertEqual(prices[rapidash.identifier].market_cents, 5571)

    def test_one_download_per_set(self):
        fetch = FakeTcgcsv({1396: {"products": [], "prices": []}})
        fetch_prices([LUGIA, LUGIA], fetch=fetch)
        self.assertEqual(len(fetch.urls), 2)


if __name__ == "__main__":
    unittest.main()
