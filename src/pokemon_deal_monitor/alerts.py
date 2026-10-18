"""Deal alert messages, and sending them for a poll's candidates."""

import html
import logging
from collections.abc import Callable
from datetime import datetime

from .catalog import CARDS, PokemonCard, Variant
from .ebay import EbayItem
from .matcher import Match
from .monitor import Candidate, PollResult
from .storage import PriceRecord, Storage, UpsertResult, utc_now
from .telegram import TelegramError
from .valuation import PRICECHARTING, TCGPLAYER, evaluate_deal, value_card


logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    PRICECHARTING: "PriceCharting",
    TCGPLAYER: "TCGplayer",
    "pricecharting_grade_5": "PriceCharting grade 5 estimate",
}


def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def describe_card(card: PokemonCard) -> str:
    """Return e.g. "Lugia 9/111 · Neo Genesis · 1st Edition Holo"."""
    printing = "Reverse Holo" if card.variant == Variant.REVERSE_HOLO else "Holo"
    if card.first_edition_required:
        printing = f"1st Edition {printing}"
    return f"{card.name} {card.number} · {card.set_name} · {printing}"


def format_alert(candidate: Candidate) -> str:
    """Return a Telegram HTML message for a qualifying deal."""
    item = candidate.item
    deal = candidate.deal
    valuation = deal.valuation
    shipping = item.shipping_cents or 0

    sources = " · ".join(
        f"{SOURCE_LABELS.get(source, source)} {format_dollars(cents)}"
        for source, cents in valuation.estimates.items()
    )
    lines = [
        f"<b>{deal.discount:.0%} below value</b>",
        f"<b>{html.escape(describe_card(candidate.match.card))}</b>",
        f"{format_dollars(item.price_cents)} + {format_dollars(shipping)} shipping"
        f" = <b>{format_dollars(deal.total_cents)}</b>",
        f"Value {format_dollars(valuation.value_cents)} ({sources})",
    ]
    lines.extend(f"⚠️ {html.escape(warning)}" for warning in valuation.warnings)
    if candidate.result == UpsertResult.PRICE_CHANGED:
        lines.append("Price dropped since last seen")
    if item.condition:
        lines.append(f"Condition: {html.escape(item.condition)}")
    lines.append(f"<i>{html.escape(item.title)}</i>")
    lines.append(f'<a href="{html.escape(item.url)}">View on eBay</a>')
    return "\n".join(lines)


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
            send(format_alert(candidate))
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
    )
    return "🧪 <b>Test alert</b>, not a real listing\n\n" + format_alert(candidate)
