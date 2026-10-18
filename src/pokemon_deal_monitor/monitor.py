import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ebay import EbayClient, EbayError, EbayItem
from .matcher import Match, match_listing
from .storage import Storage, UpsertResult, utc_now


logger = logging.getLogger(__name__)

# One search per target set. Each poll makes one call per query, so with the
# Browse API's default 5,000 calls a day a 5 minute interval leaves headroom.
SEARCH_QUERIES = [
    "pokemon base set 1st edition",
    "pokemon neo genesis 1st edition",
    "pokemon neo discovery 1st edition",
    "pokemon neo revelation 1st edition",
    "pokemon neo destiny 1st edition",
    "pokemon expedition holo",
    "pokemon aquapolis",
    "pokemon skyridge",
    "pokemon southern islands",
    "pokemon legendary collection reverse holo",
]

DEFAULT_POLL_INTERVAL_SECONDS = 300

# Searches only return the newest listings, so a listing missing from one
# poll may still be live. Only treat it as ended after this long unseen.
ENDED_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class Candidate:
    item: EbayItem
    match: Match
    result: UpsertResult


@dataclass
class PollResult:
    items_seen: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_graded(item: EbayItem) -> bool:
    return (item.condition or "").strip().lower() == "graded"


def poll_once(
    client: EbayClient,
    storage: Storage,
    queries: list[str] = SEARCH_QUERIES,
    now: datetime | None = None,
) -> PollResult:
    """Search eBay once, store every listing, and return alert candidates.

    A candidate is a matched listing that is new or changed price and has
    not already been alerted on at this price.
    """
    now = now or utc_now()
    poll = PollResult()
    seen = set()

    for query in queries:
        try:
            items = client.search(query)
        except EbayError as error:
            logger.warning("Search %r failed: %s", query, error)
            poll.errors.append(f"{query}: {error}")
            if error.status == 429:
                # Rate limited: further searches this poll would fail too.
                break
            continue

        for item in items:
            if item.item_id in seen:
                continue
            seen.add(item.item_id)

            matches = [] if is_graded(item) else match_listing(item.title)
            best = matches[0] if matches else None

            listing = item.to_listing(
                card_identifier=best.card.identifier if best else None,
                match_confidence=best.confidence if best else None,
            )
            result = storage.upsert_listing(listing, now=now)

            if (
                best is not None
                and result != UpsertResult.UNCHANGED
                and storage.should_alert(item.item_id)
            ):
                poll.candidates.append(Candidate(item, best, result))

    poll.items_seen = len(seen)
    storage.mark_ended(not_seen_since=now - ENDED_AFTER, now=now)
    return poll
