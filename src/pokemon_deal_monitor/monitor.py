import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import QuietHours
from .ebay import (
    PAGE_LIMIT,
    EbayClient,
    EbayError,
    EbayItem,
    ItemDetails,
    parse_time,
)
from .game import ENGLISH, Game
from .graded import Grade, parse_grade, strip_grade
from .matcher import Match
from .storage import Listing, Storage, UpsertResult, utc_now
from .valuation import (
    ACCEPTED_CARD_CONDITIONS,
    Deal,
    Pricer,
    evaluate_auction,
    evaluate_deal,
    evaluate_offer,
)


logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 240

# Auctions are searched less often, keeping total calls under the daily
# limit, and only those ending within the window: late enough that the
# current bid means something, early enough to place a bid.
AUCTION_POLL_INTERVAL = timedelta(minutes=30)
AUCTION_WINDOW = timedelta(hours=2)
# In the evening, this long before quiet hours start, auctions ending any
# time during quiet hours are searched too, so bids can be placed before
# going to sleep.
EVENING_SWEEP = timedelta(hours=2)

# A Buy It Now search returns its newest listings, so a full page reaches
# back only so far. One reaching back less than this could miss listings
# while eBay's rate limit blocks searches, as it has for up to 90 minutes.
MIN_SEARCH_WINDOW = timedelta(hours=3)

# Searches only return the newest listings, so a listing missing from one
# poll may still be live. Only treat it as ended after this long unseen.
ENDED_AFTER = timedelta(hours=24)

# Alerted auctions are looked up this long after they end, for what they
# sold for, last-second bids included.
RESULT_DELAY = timedelta(minutes=2)

# A listing's Card Condition and language are looked up again after this
# long, or when a Buy It Now price changes, while it qualifies on price:
# sellers revise them, for worse or better.
DETAILS_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class Candidate:
    item: EbayItem
    match: Match
    result: UpsertResult
    # None when no pricer was given or the card has no known value.
    deal: Deal | None = None
    details: ItemDetails | None = None
    # Alerts with no confident value, under the card's alert_without_value.
    no_value: bool = False
    # A graded listing's grade, which it's valued at.
    grade: Grade | None = None


@dataclass
class PollResult:
    items_seen: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def stops_requests(error: Exception) -> bool:
    """Whether an error means further eBay calls this poll would fail too:
    bad credentials or rate limiting. A network error affects one call."""
    return isinstance(error, EbayError) and error.status in (401, 429)


def is_graded(item: EbayItem) -> bool:
    return (item.condition or "").strip().lower() == "graded"


def details_rejection(
    details: ItemDetails,
    languages: frozenset[str] = ENGLISH,
    card_conditions: frozenset[str] = ACCEPTED_CARD_CONDITIONS,
) -> str | None:
    """Return why a listing's details rule it out, or None if they don't.

    A blank Language is kept, as is a blank Card Condition.
    """
    condition = details.card_condition
    if condition is not None and condition.lower() not in card_conditions:
        return f"card condition {condition}"
    language = details.language
    if language is not None and language.lower() not in languages:
        return f"language {language}"
    return None


def stored_details(
    storage: Storage, item_id: str, now: datetime | None = None,
    price_changed: bool = False,
) -> ItemDetails | None:
    """A listing's stored details, or None if they were never fetched or,
    given now, are due to be fetched again."""
    stored = storage.get_listing(item_id)
    if stored is None or stored.details_fetched_at is None:
        return None
    if now is not None and (now - stored.details_fetched_at >= DETAILS_MAX_AGE
                            or (price_changed and not stored.auction)):
        return None
    return ItemDetails(stored.card_condition, stored.language)


def value_listing(
    pricer: Pricer | None, match: Match, item: EbayItem, listing: Listing,
    now: datetime, grade: Grade | None = None,
) -> Deal | None:
    if pricer is None:
        return None
    if grade is None:
        valuation = pricer.valuation(match.card, now=now)
        rules = pricer.game.rules_for(match.card)
    else:
        valuation = pricer.graded_valuation(match.card, grade.price_grade, now=now)
        rules = pricer.game.graded_rules
    if valuation is None:
        return None
    if item.auction:
        return evaluate_auction(listing.total_cents, listing.shipping_cents,
                                valuation, rules)
    deal = evaluate_deal(listing.total_cents, listing.shipping_known, valuation,
                         rules)
    if item.best_offer and not deal.qualifies:
        offer = evaluate_offer(listing.total_cents, listing.shipping_cents,
                               valuation, rules)
        if offer.qualifies:
            return offer
    return deal


def auction_cutoff(
    now: datetime, quiet_hours: QuietHours | None = None
) -> datetime:
    """Return when the auctions to search must end by: within
    AUCTION_WINDOW, or during the evening sweep, by the end of the coming
    quiet hours."""
    cutoff = now + AUCTION_WINDOW
    if quiet_hours is None or quiet_hours.contains(now):
        return cutoff
    start, end = quiet_hours.next_window(now)
    if start - now > EVENING_SWEEP:
        return cutoff
    return max(cutoff, end)


def search_window(items: list[EbayItem], now: datetime) -> timedelta | None:
    """Return how far back a Buy It Now search's results reach, or None if
    they don't fill a page, so the search returned every listing."""
    created = [parse_time(item.created_at) for item in items if item.created_at]
    if len(items) < PAGE_LIMIT or not created:
        return None
    return now - min(created)


def poll_once(
    client: EbayClient,
    storage: Storage,
    game: Game,
    queries: list[str] | None = None,
    now: datetime | None = None,
    pricer: Pricer | None = None,
    auctions: bool = False,
    quiet_hours: QuietHours | None = None,
) -> PollResult:
    """Search eBay once for a game's cards, store every listing, and return
    alert candidates.

    Runs the game's searches, or the queries given, for Buy It Now listings, or with auctions, auctions ending within
    AUCTION_WINDOW, or in the evening before quiet hours, by their end.

    A candidate is a matched listing not yet alerted on at this price that
    is new, changed price, or qualifies as a deal. Unchanged deals stay
    candidates so an alert that failed to send is retried.
    """
    now = now or utc_now()
    queries = game.searches + game.graded_searches if queries is None else queries
    poll = PollResult()
    seen = set()
    # Cleared when eBay rate limits or rejects a details lookup, since the
    # rest would fail too. Listings without details wait for the next poll.
    can_fetch_details = True
    ending_before = auction_cutoff(now, quiet_hours) if auctions else None
    if ending_before is not None and ending_before > now + AUCTION_WINDOW:
        logger.info("Including auctions ending overnight, by %s",
                    ending_before.isoformat(timespec="minutes"))
    kind = f"{game.name} " + ("auctions" if auctions else "Buy It Now")

    for index, query in enumerate(queries, 1):
        progress = f"[{index}/{len(queries)}]"
        logger.info("%s Searching %s %r", progress, kind, query)
        try:
            graded_search = query in game.graded_searches
            items = client.search(query, auctions_ending_before=ending_before,
                                  us_sellers_only=game.us_sellers_only,
                                  graded=graded_search)
        except (EbayError, OSError) as error:
            logger.warning("Search %r failed: %s", query, error)
            poll.errors.append(f"{query}: {error}")
            if stops_requests(error):
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

            grade = None
            if not graded_search:
                matches = [] if is_graded(item) else game.title_rules.match(item.title)
            elif is_graded(item) and (grade := parse_grade(item.title)):
                matches = [
                    match for match in game.title_rules.match(strip_grade(item.title))
                    if match.card.set_name in game.graded_sets
                ]
            else:
                matches = []
            best = matches[0] if matches else None

            listing = item.to_listing(
                card_identifier=best.card.identifier if best else None,
                match_confidence=best.confidence if best else None,
            )
            result = storage.upsert_listing(listing, now=now)

            if best is None or not storage.should_alert(item.item_id):
                continue
            matched += 1

            deal = value_listing(pricer, best, item, listing, now, grade)
            no_value = (
                grade is None
                and pricer is not None
                and pricer.game.rules_for(best.card).alert_without_value
                and (deal is None or not deal.valuation.confident)
            )
            qualifies = no_value or (deal is not None and deal.qualifies)

            # Each detail lookup is a call, so only listings that would alert
            # on price are looked up, then read from storage until they're
            # due again. One that qualifies later, after a price drop or as
            # its auction's bid changes, is looked up then.
            details = stored_details(
                storage, item.item_id, now if qualifies else None,
                price_changed=result == UpsertResult.PRICE_CHANGED)
            if details is None and qualifies:
                if not can_fetch_details:
                    continue
                try:
                    details = client.item_details(item.item_id)
                except (EbayError, OSError) as error:
                    logger.warning("Details for %s failed: %s", item.item_id, error)
                    poll.errors.append(f"details {item.item_id}: {error}")
                    if stops_requests(error):
                        can_fetch_details = False
                    continue
                looked_up += 1
                storage.save_details(item.item_id, details.card_condition,
                                     details.language, now=now)
            if details is not None and details_rejection(
                details, game.languages,
                game.rules_for(best.card).card_conditions,
            ):
                continue

            if result != UpsertResult.UNCHANGED or qualifies:
                poll.candidates.append(
                    Candidate(item, best, result, deal, details, no_value, grade)
                )

        # For tuning searches: how far back a Buy It Now search reaches,
        # and what share of its listings are target cards.
        window = None if auctions else search_window(items, now)
        reach = (
            f" reaching back {window.total_seconds() / 3600:.1f}h"
            if window is not None else ""
        )
        share = f" ({matched / new_items:.0%})" if new_items else ""
        logger.info(
            "%s %d listings%s, %d matched cards%s, %d detail lookups, "
            "%d candidates",
            progress, new_items, reach, matched, share, looked_up,
            len(poll.candidates) - candidates_before,
        )
        if window is not None and window < MIN_SEARCH_WINDOW:
            logger.warning(
                "Search %r reaches back only %.1fh; its listings may be "
                "missed if searches are blocked", query,
                window.total_seconds() / 3600,
            )

    poll.items_seen = len(seen)
    storage.mark_ended(not_seen_since=now - ENDED_AFTER, now=now)
    return poll


def fetch_auction_results(
    client: EbayClient, storage: Storage, now: datetime | None = None
) -> int:
    """Look up the final price of each alerted auction that has ended,
    once, for a record of what cards sell for. Returns the lookups made."""
    now = now or utc_now()
    looked_up = 0
    for item_id in storage.auctions_awaiting_results(now - RESULT_DELAY):
        try:
            result = client.auction_result(item_id)
        except EbayError as error:
            if error.status != 404:
                logger.warning("Result for %s failed: %s", item_id, error)
                if stops_requests(error):
                    break
                continue
            # Removed from eBay; nothing to look up again.
            storage.save_auction_result(item_id, None, None, None, now=now)
            looked_up += 1
            continue
        except OSError as error:
            logger.warning("Result for %s failed: %s", item_id, error)
            continue
        looked_up += 1
        storage.save_auction_result(item_id, result.final_cents,
                                    result.bid_count, result.sold, now=now)
        listing = storage.get_listing(item_id)
        price = (f"${result.final_cents / 100:,.2f}"
                 if result.final_cents is not None else "unknown")
        outcome = {True: "sold", False: "unsold", None: "ended"}[result.sold]
        logger.info("[result] %s at %s, %s bids | %s", outcome, price,
                    result.bid_count, listing.title if listing else item_id)
    return looked_up
