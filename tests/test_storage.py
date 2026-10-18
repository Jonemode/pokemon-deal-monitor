import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pokemon_deal_monitor.storage import (
    DB_PATH_ENV_VAR,
    MIGRATIONS,
    Listing,
    PriceRecord,
    Storage,
    UpsertResult,
    default_db_path,
)


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

LUGIA = Listing(
    item_id="123456789",
    title="Lugia 9/111 Neo Genesis 1st Edition Holo LP",
    url="https://www.ebay.com/itm/123456789",
    price_cents=100_000,
    shipping_cents=500,
    card_identifier="Neo Genesis:9/111:holo:1st",
    match_confidence=1.0,
)


class TestStorage(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def test_schema_is_migrated(self):
        self.assertEqual(self.storage.schema_version, len(MIGRATIONS))

    def test_reopening_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.db"
            with Storage(path) as storage:
                storage.upsert_listing(LUGIA, now=START)

            with Storage(path) as storage:
                self.assertEqual(storage.schema_version, len(MIGRATIONS))
                self.assertIsNotNone(storage.get_listing(LUGIA.item_id))

    def test_upgrades_version_1_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                f"{MIGRATIONS[0]} PRAGMA user_version = 1;"
            )
            connection.execute(
                "INSERT INTO listings (item_id, title, url, price_cents, "
                "shipping_cents, currency, first_seen_at, last_seen_at) "
                "VALUES ('1', 't', 'u', 100, 0, 'USD', ?, ?)",
                (START.isoformat(), START.isoformat()),
            )
            connection.commit()
            connection.close()

            with Storage(path) as storage:
                self.assertEqual(storage.schema_version, len(MIGRATIONS))
                stored = storage.get_listing("1")
                self.assertIsNone(stored.condition)
                self.assertTrue(stored.shipping_known)

    def test_condition_and_unknown_shipping(self):
        listing = replace(LUGIA, condition="Ungraded", shipping_known=False)
        self.storage.upsert_listing(listing, now=START)

        stored = self.storage.get_listing(LUGIA.item_id)
        self.assertEqual(stored.condition, "Ungraded")
        self.assertFalse(stored.shipping_known)

        self.storage.upsert_listing(replace(listing, shipping_known=True))
        self.assertTrue(self.storage.get_listing(LUGIA.item_id).shipping_known)

    def test_new_listing(self):
        result = self.storage.upsert_listing(LUGIA, now=START)
        self.assertEqual(result, UpsertResult.NEW)

        stored = self.storage.get_listing(LUGIA.item_id)
        self.assertEqual(stored.title, LUGIA.title)
        self.assertEqual(stored.total_cents, 100_500)
        self.assertEqual(stored.card_identifier, LUGIA.card_identifier)
        self.assertEqual(stored.first_seen_at, START)
        self.assertEqual(stored.last_seen_at, START)
        self.assertIsNone(stored.ended_at)

    def test_unknown_listing(self):
        self.assertIsNone(self.storage.get_listing("missing"))

    def test_repeat_sighting_is_unchanged(self):
        later = START + timedelta(minutes=5)
        self.storage.upsert_listing(LUGIA, now=START)

        result = self.storage.upsert_listing(LUGIA, now=later)
        self.assertEqual(result, UpsertResult.UNCHANGED)

        stored = self.storage.get_listing(LUGIA.item_id)
        self.assertEqual(stored.first_seen_at, START)
        self.assertEqual(stored.last_seen_at, later)

    def test_price_change(self):
        self.storage.upsert_listing(LUGIA, now=START)

        cheaper = replace(LUGIA, price_cents=90_000)
        result = self.storage.upsert_listing(cheaper, now=START)
        self.assertEqual(result, UpsertResult.PRICE_CHANGED)
        self.assertEqual(
            self.storage.get_listing(LUGIA.item_id).price_cents, 90_000
        )

    def test_shipping_change_is_price_change(self):
        self.storage.upsert_listing(LUGIA, now=START)

        free_shipping = replace(LUGIA, shipping_cents=0)
        result = self.storage.upsert_listing(free_shipping, now=START)
        self.assertEqual(result, UpsertResult.PRICE_CHANGED)

    def test_first_alert(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.assertTrue(self.storage.should_alert(LUGIA.item_id))

    def test_no_duplicate_alert(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.record_alert(LUGIA.item_id, now=START)
        self.storage.upsert_listing(LUGIA, now=START + timedelta(minutes=5))

        self.assertFalse(self.storage.should_alert(LUGIA.item_id))

    def test_small_price_drop_does_not_realert(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.record_alert(LUGIA.item_id, now=START)

        # 5% below the alerted total of $1,005.
        self.storage.upsert_listing(replace(LUGIA, price_cents=95_000))
        self.assertFalse(self.storage.should_alert(LUGIA.item_id))

    def test_large_price_drop_realerts(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.record_alert(LUGIA.item_id, now=START)

        # Exactly 10% below the alerted total of $1,005.
        self.storage.upsert_listing(
            replace(LUGIA, price_cents=90_000, shipping_cents=450)
        )
        self.assertTrue(self.storage.should_alert(LUGIA.item_id))

    def test_realert_compares_against_latest_alert(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.record_alert(LUGIA.item_id, now=START)

        self.storage.upsert_listing(replace(LUGIA, price_cents=80_000))
        self.storage.record_alert(LUGIA.item_id, now=START)

        self.storage.upsert_listing(replace(LUGIA, price_cents=75_000))
        self.assertFalse(self.storage.should_alert(LUGIA.item_id))

    def test_unknown_listing_does_not_alert(self):
        self.assertFalse(self.storage.should_alert("missing"))

    def test_record_alert_for_unknown_listing(self):
        with self.assertRaises(KeyError):
            self.storage.record_alert("missing")

    def test_mark_ended(self):
        other = replace(LUGIA, item_id="987654321")
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.upsert_listing(other, now=START + timedelta(minutes=30))

        cutoff = START + timedelta(minutes=10)
        ended_at = START + timedelta(minutes=31)
        count = self.storage.mark_ended(not_seen_since=cutoff, now=ended_at)

        self.assertEqual(count, 1)
        self.assertEqual(
            self.storage.get_listing(LUGIA.item_id).ended_at, ended_at
        )
        self.assertIsNone(self.storage.get_listing(other.item_id).ended_at)
        self.assertFalse(self.storage.should_alert(LUGIA.item_id))

    def test_ended_listing_reappears(self):
        self.storage.upsert_listing(LUGIA, now=START)
        self.storage.mark_ended(not_seen_since=START + timedelta(minutes=1))

        self.storage.upsert_listing(LUGIA, now=START + timedelta(minutes=2))
        self.assertIsNone(self.storage.get_listing(LUGIA.item_id).ended_at)

    def test_timestamps_stored_in_utc(self):
        pacific = timezone(timedelta(hours=-7))
        self.storage.upsert_listing(LUGIA, now=START.astimezone(pacific))

        stored = self.storage.get_listing(LUGIA.item_id)
        self.assertEqual(stored.first_seen_at.utcoffset(), timedelta(0))
        self.assertEqual(stored.first_seen_at, START)


class TestPriceCache(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def test_save_and_get_prices(self):
        record = PriceRecord("card", "pricecharting", START, raw_cents=100,
                             grade_5_cents=150, grade_7_cents=200,
                             sales_volume=12)
        self.storage.save_price(record)
        self.storage.save_price(PriceRecord("card", "tcgplayer", START,
                                            raw_cents=90))

        prices = self.storage.get_prices("card")
        self.assertEqual(prices["pricecharting"], record)
        self.assertEqual(prices["tcgplayer"].raw_cents, 90)
        self.assertEqual(self.storage.get_prices("other"), {})

    def test_save_replaces_existing_price(self):
        self.storage.save_price(PriceRecord("card", "tcgplayer", START,
                                            raw_cents=90))
        later = START + timedelta(days=1)
        self.storage.save_price(PriceRecord("card", "tcgplayer", later,
                                            raw_cents=95))

        self.assertEqual(self.storage.get_prices("card")["tcgplayer"].raw_cents, 95)
        self.assertEqual(self.storage.latest_price_fetch("tcgplayer"), later)

    def test_latest_fetch_without_prices(self):
        self.assertIsNone(self.storage.latest_price_fetch("tcgplayer"))


class TestDefaultDbPath(unittest.TestCase):

    def test_default_path(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(default_db_path().name, "monitor.db")

    def test_environment_override(self):
        with mock.patch.dict(os.environ, {DB_PATH_ENV_VAR: "/srv/monitor.db"}):
            self.assertEqual(default_db_path(), Path("/srv/monitor.db"))


if __name__ == "__main__":
    unittest.main()
