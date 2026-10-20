"""Deal alert messages, and sending them for a poll's candidates."""

import html
import logging
import urllib.parse
from collections.abc import Callable
from datetime import datetime

from .catalog import CARDS
from .ebay import EbayItem, ItemDetails
from .matcher import Match
from .monitor import Candidate, PollResult
from .storage import PriceRecord, Storage, UpsertResult, utc_now
from .telegram import TelegramError
from .valuation import (
    MIN_DISCOUNT,
    PRICECHARTING,
    TCGPLAYER,
    evaluate_deal,
    value_card,
)


logger = logging.getLogger(__name__)

def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def listing_url(url: str) -> str:
    """Drop the search tracking eBay adds, e.g. "?_skw=...&hash=...", which
    the listing doesn't need."""
    return urllib.parse.urlunsplit(urllib.parse.urlsplit(url)._replace(
        query="", fragment=""))


def format_time_left(ends_at: datetime | None, now: datetime) -> str:
    if ends_at is None:
        return "end time unknown"
    minutes = max(0, int((ends_at - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"ends in {hours}h {minutes}m" if hours else f"ends in {minutes}m"


def format_alert(candidate: Candidate, now: datetime | None = None) -> str:
    """Return a two-line Telegram HTML message: the card and set, linked to
    the listing, then the price against value.

    Prices include shipping, as the value comparison does. An auction gives
    its current bid, time left and suggested maximum bid; a Best Offer
    listing its asking price against value.
    """
    card = candidate.match.card
    deal = candidate.deal
    item = candidate.item
    url = html.escape(listing_url(item.url))
    heading = (
        f'<a href="{url}"><b>{html.escape(card.name)} · '
        f"{html.escape(card.set_name)}</b></a>"
    )
    total = format_dollars(deal.total_cents)
    shipping_known = item.shipping_cents is not None

    if item.auction:
        under = f"{MIN_DISCOUNT:.0%} under" + ("" if shipping_known else " before shipping")
        bid = total if shipping_known else f"{total} + shipping"
        line = (
            f"Bid {bid}, {format_time_left(item.ends_at, now or utc_now())}"
            f" · max bid {format_dollars(deal.max_bid_cents)} ({under})"
        )
    elif deal.offer_cents is not None:
        if deal.discount < 0:
            versus = f"{-deal.discount:.0%} over value"
        else:
            versus = f"{deal.discount:.0%} under value"
        asking = total if shipping_known else f"{total} + shipping"
        line = f"Asking {asking} or best offer, {versus}"
    else:
        price = f"{total} with shipping" if shipping_known else f"{total} + shipping"
        line = f"{deal.discount:.0%} off · {price}"
    return f"{heading}\n{line}"


def send_alerts(
    poll: PollResult,
    storage: Storage,
    send: Callable[[str], None],
    now: datetime | None = None,
) -> int:
    """Send an alert for each qualifying deal, best discount first.

    An alert is recorded only once it has been sent, so a failed send is
    retried on the next poll. Returns the number of alerts sent.
    """
    now = now or utc_now()
    deals = sorted(
        (c for c in poll.candidates if c.deal is not None and c.deal.qualifies),
        key=lambda c: c.deal.discount,
        reverse=True,
    )

    sent = 0
    for candidate in deals:
        try:
            send(format_alert(candidate, now))
        except (TelegramError, OSError) as error:
            # Telegram is down or rate limiting: the rest would fail too.
            logger.warning("Sending alert for %s failed: %s",
                           candidate.item.item_id, error)
            break
        storage.record_alert(candidate.item.item_id, now=now)
        sent += 1
    return sent


def sample_alert() -> str:
    """Return an example alert built from made-up prices, for testing setup."""
    card = next(c for c in CARDS if c.identifier == "Neo Genesis:9/111:holo:1st")
    now = utc_now()
    valuation = value_card({
        PRICECHARTING: PriceRecord(card.identifier, PRICECHARTING, now,
                                   raw_cents=250000),
        TCGPLAYER: PriceRecord(card.identifier, TCGPLAYER, now, raw_cents=230000),
    })
    item = EbayItem(
        item_id="0",
        title="TEST ALERT: Lugia 9/111 Neo Genesis 1st Edition Holo NM",
        url="https://www.ebay.com/",
        price_cents=170000,
        currency="USD",
        shipping_cents=500,
        condition="Ungraded",
    )
    candidate = Candidate(
        item=item,
        match=Match(card, 1.0),
        result=UpsertResult.NEW,
        deal=evaluate_deal(170500, True, valuation),
        details=ItemDetails("Near mint or better", "English"),
    )
    return "🧪 <b>Test alert</b>, not a real listing\n" + format_alert(candidate)
