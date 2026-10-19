"""Deal alert messages, and sending them for a poll's candidates."""

import html
import logging
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


def format_time_left(ends_at: datetime | None, now: datetime) -> str:
    if ends_at is None:
        return "end time unknown"
    minutes = max(0, int((ends_at - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"ends in {hours}h {minutes}m" if hours else f"ends in {minutes}m"


def format_alert(candidate: Candidate, now: datetime | None = None) -> str:
    """Return a short Telegram HTML message: card, discount, total, link.

    An auction's alert gives the time left, bids and current bid, and leads
    with the suggested maximum bid. A Best Offer alert gives the suggested
    offer.
    """
    card = candidate.match.card
    deal = candidate.deal
    item = candidate.item
    url = html.escape(item.url)
    if item.shipping_cents is None:
        price = f"{format_dollars(deal.total_cents)} + unknown shipping"
    else:
        price = f"{format_dollars(deal.total_cents)} with shipping"
    heading = f"<b>{html.escape(card.name)}</b> · {html.escape(card.set_name)}\n"
    link = f'<a href="{url}">{url}</a>'
    if deal.offer_cents is not None:
        if deal.discount < 0:
            versus = f"{-deal.discount:.0%} over value"
        else:
            versus = f"{deal.discount:.0%} under value"
        return heading + "\n".join([
            f"<b>Best Offer</b> · listed {price} · {versus}",
            f"<b>Offer {format_dollars(deal.offer_cents)}</b> to pay"
            f" {MIN_DISCOUNT:.0%} under the"
            f" {format_dollars(deal.valuation.value_cents)} value"
            + ("" if item.shipping_cents is not None else ", before shipping"),
        ]) + "\n" + link
    if not item.auction:
        return heading + f"<b>{deal.discount:.0%} off</b> · {price}\n" + link

    bids = f"{item.bid_count} bid{'' if item.bid_count == 1 else 's'}"
    lines = [
        f"<b>Auction</b> · {format_time_left(item.ends_at, now or utc_now())}"
        f" · {bids}",
        f"Current bid {price} · {deal.discount:.0%} under value",
        f"<b>Max bid {format_dollars(deal.max_bid_cents)}</b> to pay"
        f" {MIN_DISCOUNT:.0%} under the"
        f" {format_dollars(deal.valuation.value_cents)} value"
        + ("" if item.shipping_cents is not None else ", before shipping"),
    ]
    if candidate.details is not None and candidate.details.reserve_met is False:
        lines.append("Reserve not met")
    return heading + "\n".join(lines) + "\n" + link


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
    return "🧪 <b>Test alert</b>, not a real listing\n\n" + format_alert(candidate)
