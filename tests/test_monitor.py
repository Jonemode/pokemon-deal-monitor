import unittest
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.ebay import EbayClient
from pokemon_deal_monitor.monitor import poll_once
from pokemon_deal_monitor.storage import PriceRecord, Storage, UpsertResult
from pokemon_deal_monitor.valuation import PRICECHARTING, TCGPLAYER, value_card

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

    def test_authentication_failure_stops_poll(self):
        client = EbayClient(CONFIG, transport=FakeTransport(
            {"neo": search_response(), "aquapolis": search_response()},
            token=(401, b'{"error": "invalid_client"}'),
        ))
        poll = poll_once(client, self.storage, queries=["neo", "aquapolis"])

        self.assertEqual(len(poll.errors), 1)

    def test_candidates_are_valued(self):
        class FixedPricer:
            def valuation(self, card, now=None):
                return value_card({
                    source: PriceRecord(card.identifier, source, START,
                                        raw_cents=200000)
                    for source in (PRICECHARTING, TCGPLAYER)
                })

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

    def test_unsent_deal_stays_candidate_until_alerted(self):
        class FixedPricer:
            def valuation(self, card, now=None):
                return value_card({
                    source: PriceRecord(card.identifier, source, START,
                                        raw_cents=200000)
                    for source in (PRICECHARTING, TCGPLAYER)
                })

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
