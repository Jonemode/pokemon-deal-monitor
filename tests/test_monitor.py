import unittest
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.ebay import EbayClient
from pokemon_deal_monitor.monitor import poll_once
from pokemon_deal_monitor.storage import Storage, UpsertResult

from .fakes import CONFIG, FakeTransport, item_summary, search_response


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

LUGIA = "Lugia 9/111 Neo Genesis 1st Edition Holo LP"
UMBREON = "Umbreon H29/H32 Aquapolis Holo LP"


class TestPollOnce(unittest.TestCase):

    def setUp(self):
        self.storage = Storage(":memory:")
        self.addCleanup(self.storage.close)

    def poll(self, searches, now=START):
        client = EbayClient(CONFIG, transport=FakeTransport(searches))
        return poll_once(client, self.storage, queries=list(searches), now=now)

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

    def test_long_unseen_listing_is_ended(self):
        self.poll({"neo": search_response(item_summary("1", LUGIA))})
        self.poll({"neo": search_response()}, now=START + timedelta(hours=25))

        self.assertIsNotNone(self.storage.get_listing("1").ended_at)


if __name__ == "__main__":
    unittest.main()
