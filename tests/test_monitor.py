import json
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.ebay import EbayClient
from pokemon_deal_monitor.monitor import poll_once
from pokemon_deal_monitor.storage import PriceRecord, Storage, UpsertResult
from pokemon_deal_monitor.valuation import PRICECHARTING, TCGPLAYER, value_card

from .fakes import (
    CONFIG,
    FakeTransport,
    auction_summary,
    item_response,
    item_summary,
    search_response,
)


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

LUGIA = "Lugia 9/111 Neo Genesis 1st Edition Holo LP"
UMBREON = "Umbreon H29/H32 Aquapolis Holo LP"


class FixedPricer:
    """Values every card at $2,000."""

    def valuation(self, card, now=None):
        return value_card({
            source: PriceRecord(card.identifier, source, START, raw_cents=200000)
            for source in (PRICECHARTING, TCGPLAYER)
        })


class TestPollOnce(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def poll(self, searches, now=START, items=None):
        self.transport = FakeTransport(searches, items=items)
        client = EbayClient(CONFIG, transport=self.transport)
        return poll_once(client, self.storage, queries=list(searches), now=now)

    def test_played_card_condition_is_rejected(self):
        poll = self.poll(
            {"neo": search_response(item_summary("1", LUGIA),
                                    item_summary("2", UMBREON))},
            items={"1": item_response("Moderately played (Very good)"),
                   "2": item_response("Heavily played (Poor)")},
        )
        self.assertEqual(poll.candidates, [])
        self.assertEqual(self.storage.get_listing("1").card_condition,
                         "Moderately played (Very good)")

    def test_blank_condition_and_language_are_kept(self):
        poll = self.poll(
            {"neo": search_response(item_summary("1", LUGIA))},
            items={"1": item_response(None, None)},
        )
        (candidate,) = poll.candidates
        self.assertIsNone(candidate.details.card_condition)
        self.assertIsNone(candidate.details.language)

    def test_non_english_language_is_rejected(self):
        poll = self.poll(
            {"neo": search_response(item_summary("1", LUGIA))},
            items={"1": item_response("Near mint or better", "Japanese")},
        )
        self.assertEqual(poll.candidates, [])

    def test_listings_from_another_ebay_site(self):
        def italian_item(condition, language):
            return 200, json.dumps({
                "conditionDescriptors": [{
                    "name": "Condizione della carta",
                    "values": [{"content": condition}],
                }],
                "localizedAspects": [
                    {"type": "STRING", "name": "Lingua", "value": language},
                ],
            }).encode()

        poll = self.poll(
            {"neo": search_response(item_summary("1", LUGIA),
                                    item_summary("2", UMBREON),
                                    item_summary("3", LUGIA + " "))},
            items={"1": italian_item("Near Mint or Better", "Inglese"),
                   "2": italian_item("Moderately Played (Very Good)", "Inglese"),
                   "3": italian_item("Lightly Played (Excellent)", "Italiano")},
        )
        self.assertEqual([c.item.item_id for c in poll.candidates], ["1"])
        self.assertEqual(len(self.transport.item_requests), 3)

    def test_details_are_fetched_once(self):
        searches = {"neo": search_response(item_summary("1", LUGIA, "900.00"))}
        self.poll(searches)
        self.poll({"neo": search_response(item_summary("1", LUGIA, "800.00"))},
                  now=START + timedelta(minutes=5))

        self.assertEqual(self.transport.item_requests, [])
        self.assertIsNotNone(self.storage.get_listing("1").details_fetched_at)

    def test_unmatched_listing_details_not_fetched(self):
        self.poll({"neo": search_response(item_summary("1", "Pokemon Card Lot"))})
        self.assertEqual(self.transport.item_requests, [])

    def test_details_rate_limit_stops_lookups_until_next_poll(self):
        searches = {"neo": search_response(item_summary("1", LUGIA),
                                           item_summary("2", UMBREON))}
        poll = self.poll(searches, items={"1": (429, b"rate limited")})

        self.assertEqual(poll.candidates, [])
        self.assertEqual(len(self.transport.item_requests), 1)
        self.assertEqual(len(poll.errors), 1)

        retry = self.poll(searches, now=START + timedelta(minutes=5))
        self.assertEqual(len(self.transport.item_requests), 2)
        self.assertEqual(retry.candidates, [])

    def test_new_matched_listing_is_candidate(self):
        poll = self.poll({
            "neo": search_response(item_summary("1", LUGIA, "900.00")),
        })

        self.assertEqual(poll.items_seen, 1)
        (candidate,) = poll.candidates
        self.assertEqual(candidate.result, UpsertResult.NEW)
        self.assertEqual(
            candidate.match.card.identifier, "Neo Genesis:9/111:holo:1st"
        )

        stored = self.storage.get_listing("1")
        self.assertEqual(stored.card_identifier, "Neo Genesis:9/111:holo:1st")
        self.assertEqual(stored.match_confidence, 1.0)

    def test_unmatched_listing_is_stored_but_not_candidate(self):
        poll = self.poll({
            "neo": search_response(item_summary("1", "Pokemon Neo Genesis Lot")),
        })

        self.assertEqual(poll.candidates, [])
        self.assertIsNone(self.storage.get_listing("1").card_identifier)

    def test_graded_condition_is_not_matched(self):
        poll = self.poll({
            "neo": search_response(
                item_summary("1", LUGIA, condition="Graded")
            ),
        })
        self.assertEqual(poll.candidates, [])

    def test_repeat_poll_has_no_candidates(self):
        searches = {"neo": search_response(item_summary("1", LUGIA))}
        self.poll(searches)

        poll = self.poll(searches, now=START + timedelta(minutes=5))
        self.assertEqual(poll.candidates, [])

    def test_price_change_is_candidate(self):
        self.poll({"neo": search_response(item_summary("1", LUGIA, "900.00"))})

        poll = self.poll(
            {"neo": search_response(item_summary("1", LUGIA, "800.00"))},
            now=START + timedelta(minutes=5),
        )
        (candidate,) = poll.candidates
        self.assertEqual(candidate.result, UpsertResult.PRICE_CHANGED)

    def test_listing_in_two_searches_counted_once(self):
        summary = item_summary("1", UMBREON)
        poll = self.poll({
            "aquapolis": search_response(summary),
            "aquapolis holo": search_response(summary),
        })

        self.assertEqual(poll.items_seen, 1)
        self.assertEqual(len(poll.candidates), 1)

    def test_failed_search_continues_with_others(self):
        poll = self.poll({
            "neo": (500, b"server error"),
            "aquapolis": search_response(item_summary("2", UMBREON)),
        })

        self.assertEqual(len(poll.errors), 1)
        self.assertEqual(len(poll.candidates), 1)

    def test_rate_limit_stops_poll(self):
        poll = self.poll({
            "neo": (429, b"rate limited"),
            "aquapolis": search_response(item_summary("2", UMBREON)),
        })

        self.assertEqual(len(poll.errors), 1)
        self.assertEqual(poll.items_seen, 0)

    def test_authentication_failure_stops_poll(self):
        client = EbayClient(CONFIG, transport=FakeTransport(
            {"neo": search_response(), "aquapolis": search_response()},
            token=(401, b'{"error": "invalid_client"}'),
        ))
        poll = poll_once(client, self.storage, queries=["neo", "aquapolis"])

        self.assertEqual(len(poll.errors), 1)

    def test_candidates_are_valued(self):
        client = EbayClient(CONFIG, transport=FakeTransport({
            "neo": search_response(
                item_summary("1", LUGIA, "1400.00", "5.00"),
                item_summary("2", UMBREON, "1900.00", "5.00"),
            ),
        }))
        poll = poll_once(client, self.storage, queries=["neo"], now=START,
                         pricer=FixedPricer())

        deals = {c.item.item_id: c.deal for c in poll.candidates}
        self.assertTrue(deals["1"].qualifies)
        self.assertAlmostEqual(deals["1"].discount, 0.2975)
        self.assertFalse(deals["2"].qualifies)

    def test_auctions_ending_soon(self):
        transport = FakeTransport({
            "auction:neo": search_response(
                auction_summary("1", LUGIA, bid="900.00", shipping="5.00"),
                auction_summary("2", UMBREON, bid="1500.00", shipping="5.00"),
            ),
        })
        client = EbayClient(CONFIG, transport=transport)
        poll = poll_once(client, self.storage, queries=["neo"], now=START,
                         pricer=FixedPricer(), auctions=True)

        self.assertIn("itemEndDate:[..2026-10-17T14:00:00Z]",
                      urllib.parse.unquote(transport.search_requests[0].full_url))
        deals = {c.item.item_id: c.deal for c in poll.candidates}
        self.assertTrue(deals["1"].qualifies)
        self.assertEqual(deals["1"].max_bid_cents, 179500)
        self.assertFalse(deals["2"].qualifies)

    def test_auction_alerted_once_as_bids_rise(self):
        def poll(bid, now):
            client = EbayClient(CONFIG, transport=FakeTransport({
                "auction:neo": search_response(
                    auction_summary("1", LUGIA, bid=bid)),
            }))
            return poll_once(client, self.storage, queries=["neo"], now=now,
                             pricer=FixedPricer(), auctions=True)

        poll("500.00", START)
        self.storage.record_alert("1", now=START)
        later = poll("700.00", START + timedelta(minutes=15))
        self.assertEqual(later.candidates, [])

    def test_unsent_deal_stays_candidate_until_alerted(self):
        def poll():
            client = EbayClient(CONFIG, transport=FakeTransport({
                "neo": search_response(
                    item_summary("1", LUGIA, "1400.00", "5.00"),
                    item_summary("2", UMBREON, "1900.00", "5.00"),
                ),
            }))
            return poll_once(client, self.storage, queries=["neo"], now=START,
                             pricer=FixedPricer())

        poll()
        repeat = poll()
        self.assertEqual([c.item.item_id for c in repeat.candidates], ["1"])
        self.assertEqual(repeat.candidates[0].result, UpsertResult.UNCHANGED)

        self.storage.record_alert("1", now=START)
        self.assertEqual(poll().candidates, [])

    def test_candidates_without_pricer_have_no_deal(self):
        poll = self.poll({"neo": search_response(item_summary("1", LUGIA))})
        self.assertIsNone(poll.candidates[0].deal)

    def test_long_unseen_listing_is_ended(self):
        self.poll({"neo": search_response(item_summary("1", LUGIA))})
        self.poll({"neo": search_response()}, now=START + timedelta(hours=25))

        self.assertIsNotNone(self.storage.get_listing("1").ended_at)


if __name__ == "__main__":
    unittest.main()
