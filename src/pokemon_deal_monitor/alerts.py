"""Deal alert messages, and sending them for a poll's candidates."""

import html
import logging
import urllib.parse
from collections.abc import Callable
from datetime import datetime, tzinfo

from .ebay import EbayItem, ItemDetails
from .games.pokemon.catalog import CARDS
from .matcher import Match
from .monitor import AUCTION_WINDOW, Candidate, PollResult
from .storage import PriceRecord, Storage, UpsertResult, utc_now
from .telegram import TelegramError
from .valuation import (
    PRICECHARTING,
    TCGPLAYER,
    evaluate_deal,
    value_card,
)
from .watch import WatchHit


logger = logging.getLogger(__name__)

def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def format_whole_dollars(cents: int, round_down: bool = False) -> str:
    """Dollars without cents, for alerts. Rounds to the nearest dollar, or
    down, so a suggested maximum never rounds up past its target."""
    dollars = cents // 100 if round_down else (cents + 50) // 100
    return f"${dollars:,}"


def listing_url(url: str) -> str:
    """Drop the search tracking eBay adds, e.g. "?_skw=...&hash=...", which
    the listing doesn't need."""
    return urllib.parse.urlunsplit(urllib.parse.urlsplit(url)._replace(
        query="", fragment=""))


def format_time_left(
    ends_at: datetime | None, now: datetime, timezone: tzinfo | None = None
) -> str:
    """Return e.g. "1h 25m left", or with a timezone, the local end
    time of an auction further off, e.g. "ends 3:10am", as found by the
    evening sweep."""
    if ends_at is None:
        return "end unknown"
    if timezone is not None and ends_at - now > AUCTION_WINDOW:
        local = ends_at.astimezone(timezone)
        return f"ends {local.hour % 12 or 12}:{local:%M}{local:%p}".lower()
    minutes = max(0, int((ends_at - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m left" if hours else f"{minutes}m left"


def format_alert(
    candidate: Candidate,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> str:
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
    total = format_whole_dollars(deal.total_cents)
    shipping_known = item.shipping_cents is not None
    # Sets allowed over value can alert on a price above it.
    if deal.discount < 0:
        versus = f"{-deal.discount:.0%} over"
    else:
        versus = f"{deal.discount:.0%} off"

    if item.auction:
        # The max bid leaves 10% under value once shipping is paid,
        # so with shipping unknown it is before shipping.
        bid = total if shipping_known else f"{total} + ship"
        max_bid = format_whole_dollars(deal.max_bid_cents, round_down=True)
        line = (
            f"Bid {bid} · "
            f"{format_time_left(item.ends_at, now or utc_now(), timezone)}"
            f" · max {max_bid}" + ("" if shipping_known else " + ship")
        )
    elif deal.offer_cents is not None:
        asking = total if shipping_known else f"{total} + ship"
        line = f"{asking} obo · {versus}"
    else:
        price = f"{total} shipped" if shipping_known else f"{total} + ship"
        line = f"{versus} · {price}"
    return f"{heading}\n{line}"


def format_watch_alert(hit: WatchHit, now: datetime | None = None) -> str:
    """Return a two-line alert for a watched card's listing: the card,
    linked to the listing, then its price."""
    item = hit.item
    url = html.escape(listing_url(item.url))
    heading = f'<a href="{url}"><b>{html.escape(hit.watch.name)}</b></a>'
    if item.shipping_cents is None:
        price = f"{format_whole_dollars(item.price_cents)} + ship"
    else:
        total = item.price_cents + item.shipping_cents
        price = f"{format_whole_dollars(total)} shipped"
    if item.auction:
        line = (f"Bid {price} · "
                f"{format_time_left(item.ends_at, now or utc_now())}")
    else:
        line = f"Listed {price}"
    return f"{heading}\n{line}"


def send_each(
    messages: list[tuple[str, str]],
    storage: Storage,
    send: Callable[[str], None],
    now: datetime,
) -> int:
    """Send (item ID, text) messages in order, recording each alert only
    once it has been sent, so a failed send is retried on the next poll.
    Returns the number sent."""
    sent = 0
    for item_id, text in messages:
        try:
            send(text)
        except (TelegramError, OSError) as error:
            # Telegram is down or rate limiting: the rest would fail too.
            logger.warning("Sending alert for %s failed: %s", item_id, error)
            break
        storage.record_alert(item_id, now=now)
        sent += 1
    return sent


def send_alerts(
    poll: PollResult,
    storage: Storage,
    send: Callable[[str], None],
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> int:
    """Send an alert for each qualifying deal, best discount first.
    Returns the number of alerts sent."""
    now = now or utc_now()
    deals = sorted(
        (c for c in poll.candidates if c.deal is not None and c.deal.qualifies),
        key=lambda c: c.deal.discount,
        reverse=True,
    )
    return send_each([(c.item.item_id, format_alert(c, now, timezone))
                      for c in deals],
                     storage, send, now)


def send_watch_alerts(
    hits: list[WatchHit],
    storage: Storage,
    send: Callable[[str], None],
    now: datetime | None = None,
) -> int:
    """Send an alert for each watched card's new listing. Returns the
    number of alerts sent."""
    now = now or utc_now()
    return send_each([(h.item.item_id, format_watch_alert(h, now)) for h in hits],
                     storage, send, now)


def sample_alert() -> str:
    """Return an example alert built from made-up prices, for testing setup."""
    card = next(c for c in CARDS
                if c.identifier == "pokemon:Neo Genesis:9/111:holo:1st")
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
