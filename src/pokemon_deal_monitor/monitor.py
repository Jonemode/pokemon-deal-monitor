import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ebay import EbayClient, EbayError, EbayItem, ItemDetails
from .matcher import Match, match_listing
from .storage import Listing, Storage, UpsertResult, utc_now
from .valuation import Deal, Pricer, evaluate_deal


logger = logging.getLogger(__name__)

# One search per target set, two for promos since sellers call them either
# Black Star or WOTC promos. Each poll makes one call per query, so with the
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
    "pokemon black star promo",
    "pokemon wotc promo",
]

DEFAULT_POLL_INTERVAL_SECONDS = 300

# Searches only return the newest listings, so a listing missing from one
# poll may still be live. Only treat it as ended after this long unseen.
ENDED_AFTER = timedelta(hours=24)

# eBay "Card Condition" values to keep, lowercased. Listings that leave it
# blank are kept too: the title isn't used to guess, since "HP" in a title
# usually means hit points rather than heavily played.
ACCEPTED_CARD_CONDITIONS = {"near mint or better", "lightly played (excellent)"}
# A blank Language is kept; the matcher rejects non-English titles anyway.
ACCEPTED_LANGUAGES = {"english"}


@dataclass(frozen=True)
class Candidate:
    item: EbayItem
    match: Match
    result: UpsertResult
    # None when no pricer was given or the card has no known value.
    deal: Deal | None = None
    details: ItemDetails | None = None


@dataclass
class PollResult:
    items_seen: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_graded(item: EbayItem) -> bool:
    return (item.condition or "").strip().lower() == "graded"


def details_rejection(details: ItemDetails) -> str | None:
    """Return why a listing's details rule it out, or None if they don't."""
    condition = details.card_condition
    if condition is not None and condition.lower() not in ACCEPTED_CARD_CONDITIONS:
        return f"card condition {condition}"
    language = details.language
    if language is not None and language.lower() not in ACCEPTED_LANGUAGES:
        return f"language {language}"
    return None


def stored_details(storage: Storage, item_id: str) -> ItemDetails | None:
    stored = storage.get_listing(item_id)
    if stored is None or stored.details_fetched_at is None:
        return None
    return ItemDetails(stored.card_condition, stored.language)


def value_listing(
    pricer: Pricer | None, match: Match, listing: Listing, now: datetime
) -> Deal | None:
    if pricer is None:
        return None
    valuation = pricer.valuation(match.card, now=now)
    if valuation is None:
        return None
    return evaluate_deal(listing.total_cents, listing.shipping_known, valuation,
                         match.card)


def poll_once(
    client: EbayClient,
    storage: Storage,
    queries: list[str] = SEARCH_QUERIES,
    now: datetime | None = None,
    pricer: Pricer | None = None,
) -> PollResult:
    """Search eBay once, store every listing, and return alert candidates.

    A candidate is a matched listing not yet alerted on at this price that
    is new, changed price, or qualifies as a deal. Unchanged deals stay
    candidates so an alert that failed to send is retried.
    """
    now = now or utc_now()
    poll = PollResult()
    seen = set()
    # Cleared when eBay rate limits or rejects a details lookup, since the
    # rest would fail too. Listings without details wait for the next poll.
    can_fetch_details = True

    for index, query in enumerate(queries, 1):
        progress = f"[{index}/{len(queries)}]"
        logger.info("%s Searching %r", progress, query)
        try:
            items = client.search(query)
        except EbayError as error:
            logger.warning("Search %r failed: %s", query, error)
            poll.errors.append(f"{query}: {error}")
            if error.status in (401, 429):
                # Bad credentials or rate limited: further searches this
                # poll would fail too.
                break
            continue

        # Per-search counts, logged as progress once the search is processed.
        new_items = matched = looked_up = 0
        candidates_before = len(poll.candidates)

        for item in items:
            if item.item_id in seen:
                continue
            seen.add(item.item_id)
            new_items += 1

            matches = [] if is_graded(item) else match_listing(item.title)
            best = matches[0] if matches else None

            listing = item.to_listing(
                card_identifier=best.card.identifier if best else None,
                match_confidence=best.confidence if best else None,
            )
            result = storage.upsert_listing(listing, now=now)

            if best is None or not storage.should_alert(item.item_id):
                continue
            matched += 1

            # Each listing's details are fetched once, then read from storage.
            details = stored_details(storage, item.item_id)
            if details is None:
                if not can_fetch_details:
                    continue
                try:
                    details = client.item_details(item.item_id)
                except EbayError as error:
                    logger.warning("Details for %s failed: %s", item.item_id, error)
                    poll.errors.append(f"details {item.item_id}: {error}")
                    if error.status in (401, 429):
                        can_fetch_details = False
                    continue
                looked_up += 1
                storage.save_details(item.item_id, details.card_condition,
                                     details.language, now=now)
            if details_rejection(details) is not None:
                continue

            deal = value_listing(pricer, best, listing, now)
            if result != UpsertResult.UNCHANGED or (deal and deal.qualifies):
                poll.candidates.append(
                    Candidate(item, best, result, deal, details)
                )

        logger.info(
            "%s %d listings, %d matched cards, %d detail lookups, %d candidates",
            progress, new_items, matched, looked_up,
            len(poll.candidates) - candidates_before,
        )

    poll.items_seen = len(seen)
    storage.mark_ended(not_seen_since=now - ENDED_AFTER, now=now)
    return poll
