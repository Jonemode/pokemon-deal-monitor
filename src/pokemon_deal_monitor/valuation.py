"""Conservative market values for catalog cards, and deal evaluation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .games.pokemon.catalog import CARDS, PokemonCard
from .pricecharting import PriceChartingClient, PriceChartingError
from .storage import PriceRecord, Storage, utc_now
from .tcgcsv import TcgPrice, fetch_prices


logger = logging.getLogger(__name__)

PRICECHARTING = "pricecharting"
TCGPLAYER = "tcgplayer"

# Prices older than this are refreshed before use.
PRICE_MAX_AGE = timedelta(hours=24)
# If a refresh fails, cached prices up to this old are still used.
PRICE_STALE_LIMIT = timedelta(days=7)
# After a failed bulk TCGplayer refresh, wait this long before retrying.
TCGPLAYER_RETRY_AFTER = timedelta(hours=1)

# A listing qualifies when its total is at least this far below value.
MIN_DISCOUNT = 0.10
# Sets with their own minimum discount for Buy It Now listings. Negative
# allows a total up to that far over value.
MIN_DISCOUNTS = {
    "Wizards Black Star Promos": -0.05,
    "Legendary Collection": -0.05,
}
# An auction's current bid will rise before it ends, so it qualifies only
# when the current total is this far below value. The suggested maximum bid
# still keeps the final total MIN_DISCOUNT below value.
MIN_AUCTION_DISCOUNT = 0.40
# The most a suggested maximum bid can be, matching the eBay price filter.
MAX_BID_CENTS = 500000
# A Best Offer listing priced up to this far over value is worth an offer
# of MIN_DISCOUNT below value, which the seller may accept.
MAX_OFFER_PREMIUM = 0.10
# Sets with a minimum card value to alert on, in cents, to skip the many
# promos worth only a few dollars.
MIN_VALUE_CENTS = {
    "Wizards Black Star Promos": 5000,
}
# Cards often sold as reprints under the original set's name, with nothing
# in the listing to tell them apart. A discount beyond the limit is taken to
# mean a reprint rather than a bargain. Auctions of these cards are skipped,
# since a low current bid says nothing about whether it's a reprint.
MAX_PLAUSIBLE_DISCOUNTS = {
    # 30th Anniversary Lugia reprints listed as Aquapolis.
    "pokemon:Aquapolis:149/147:holo:unlimited": 0.50,
}
# A TCGplayer price this many times below PriceCharting's is flagged as a
# warning on the alert, since it can mean a mismatched or stale product.
MAX_SOURCE_RATIO = 1.5
# With no raw price, a grade 5 copy stands in for a lightly played raw card
# after taking off the premium buyers pay for a graded slab.
GRADE_5_RAW_DISCOUNT = 0.2


@dataclass(frozen=True)
class Valuation:
    value_cents: int
    confident: bool
    # The estimate from each source that went into the value, in cents.
    estimates: dict[str, int]
    notes: tuple[str, ...] = ()
    # Problems worth showing on an alert; they don't stop it qualifying.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Deal:
    total_cents: int
    valuation: Valuation
    discount: float
    qualifies: bool
    # Why the listing does not qualify; empty when it does.
    reasons: tuple[str, ...] = ()
    # For an auction, the most to bid so the total stays MIN_DISCOUNT below
    # value. Without known shipping it leaves no room for shipping.
    max_bid_cents: int | None = None
    # For a Best Offer listing, the offer that keeps the total MIN_DISCOUNT
    # below value, likewise before any unknown shipping.
    offer_cents: int | None = None


def value_card(prices: dict[str, PriceRecord]) -> Valuation | None:
    """Return a value for a card from its cached prices.

    PriceCharting's ungraded price is the value, capped at its grade 7 price
    since a raw card rarely sells above a graded near mint copy. TCGplayer is
    a cross-check: a much lower TCGplayer price adds a warning. Without a
    PriceCharting raw price, the TCGplayer price or a grade 5 estimate is
    shown but is never confident enough to alert on.
    """
    pricecharting = prices.get(PRICECHARTING)
    tcgplayer = prices.get(TCGPLAYER)

    estimates = {}
    if pricecharting and pricecharting.raw_cents:
        estimates[PRICECHARTING] = pricecharting.raw_cents
    if tcgplayer and tcgplayer.raw_cents:
        estimates[TCGPLAYER] = tcgplayer.raw_cents

    notes = []
    warnings = []
    if PRICECHARTING in estimates:
        value = estimates[PRICECHARTING]
        confident = True
        if TCGPLAYER in estimates:
            ratio = value / estimates[TCGPLAYER]
            if ratio > MAX_SOURCE_RATIO:
                warnings.append(
                    f"sources disagree: TCGplayer is {ratio:.1f}x lower"
                )
        else:
            notes.append("no TCGplayer price")
    elif TCGPLAYER in estimates:
        value = estimates[TCGPLAYER]
        confident = False
        notes.append("no PriceCharting price")
    elif pricecharting and pricecharting.grade_5_cents:
        value = round(pricecharting.grade_5_cents * (1 - GRADE_5_RAW_DISCOUNT))
        estimates["pricecharting_grade_5"] = value
        confident = False
        notes.append("estimated from grade 5 price")
    else:
        return None

    if pricecharting and pricecharting.grade_7_cents:
        if value > pricecharting.grade_7_cents:
            value = pricecharting.grade_7_cents
            notes.append("capped at grade 7 price")

    return Valuation(
        value_cents=value,
        confident=confident,
        estimates=estimates,
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


def evaluate_deal(
    total_cents: int,
    shipping_known: bool,
    valuation: Valuation,
    card: PokemonCard | None = None,
) -> Deal:
    """Judge a listing against a card's value.

    When shipping is unknown the total is the item price alone, and the
    alert says so rather than the listing being skipped.
    """
    discount = 1 - total_cents / valuation.value_cents

    min_discount = MIN_DISCOUNT
    if card is not None:
        min_discount = MIN_DISCOUNTS.get(card.set_name, MIN_DISCOUNT)

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    # Compared in cents, since 1 - 0.9 in floating point is just under 0.1.
    if total_cents > round(valuation.value_cents * (1 - min_discount)):
        if min_discount < 0:
            reasons.append(f"price more than {-min_discount:.0%} over value")
        else:
            reasons.append(f"discount below {min_discount:.0%}")
    min_value = MIN_VALUE_CENTS.get(card.set_name) if card else None
    if min_value is not None and valuation.value_cents < min_value:
        reasons.append(f"value below ${min_value / 100:,.0f}")
    max_discount = MAX_PLAUSIBLE_DISCOUNTS.get(card.identifier) if card else None
    if (
        max_discount is not None
        and total_cents < round(valuation.value_cents * (1 - max_discount))
    ):
        reasons.append(
            f"discount above {max_discount:.0%}, likely a misrepresented reprint"
        )

    return Deal(
        total_cents=total_cents,
        valuation=valuation,
        discount=discount,
        qualifies=not reasons,
        reasons=tuple(reasons),
    )


def evaluate_offer(
    total_cents: int,
    shipping_cents: int,
    valuation: Valuation,
    card: PokemonCard | None = None,
) -> Deal:
    """Judge a Best Offer listing that isn't a deal at its price, and
    suggest an offer that would make it one."""
    discount = 1 - total_cents / valuation.value_cents
    target_cents = round(valuation.value_cents * (1 - MIN_DISCOUNT))

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    if total_cents > round(valuation.value_cents * (1 + MAX_OFFER_PREMIUM)):
        reasons.append(f"price more than {MAX_OFFER_PREMIUM:.0%} over value")
    # A listing already this cheap failed as a deal for another reason, such
    # as a likely reprint, which an offer doesn't change.
    if total_cents <= target_cents:
        reasons.append("price already at or below the offer")
    min_value = MIN_VALUE_CENTS.get(card.set_name) if card else None
    if min_value is not None and valuation.value_cents < min_value:
        reasons.append(f"value below ${min_value / 100:,.0f}")

    return Deal(
        total_cents=total_cents,
        valuation=valuation,
        discount=discount,
        qualifies=not reasons,
        reasons=tuple(reasons),
        offer_cents=target_cents - shipping_cents,
    )


def evaluate_auction(
    total_cents: int,
    shipping_cents: int,
    valuation: Valuation,
    card: PokemonCard | None = None,
) -> Deal:
    """Judge an auction's current bid against a card's value, and suggest
    the most to bid."""
    discount = 1 - total_cents / valuation.value_cents
    max_bid_cents = min(
        round(valuation.value_cents * (1 - MIN_DISCOUNT)) - shipping_cents,
        MAX_BID_CENTS,
    )

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    if total_cents > round(valuation.value_cents * (1 - MIN_AUCTION_DISCOUNT)):
        reasons.append(f"current bid less than {MIN_AUCTION_DISCOUNT:.0%} below value")
    min_value = MIN_VALUE_CENTS.get(card.set_name) if card else None
    if min_value is not None and valuation.value_cents < min_value:
        reasons.append(f"value below ${min_value / 100:,.0f}")
    if card is not None and card.identifier in MAX_PLAUSIBLE_DISCOUNTS:
        reasons.append("auctions skipped, reprints are often sold as this card")

    return Deal(
        total_cents=total_cents,
        valuation=valuation,
        discount=discount,
        qualifies=not reasons,
        reasons=tuple(reasons),
        max_bid_cents=max_bid_cents,
    )


class Pricer:
    """Values cards from cached prices, refreshing them when stale.

    TCGplayer prices are refreshed in bulk once a day. PriceCharting prices
    are fetched one card at a time, only for cards that need a value.
    """

    def __init__(
        self,
        storage: Storage,
        pricecharting: PriceChartingClient | None = None,
        product_ids: dict[str, str] | None = None,
        fetch_tcgplayer: Callable[[list[PokemonCard]], dict[str, TcgPrice]] = fetch_prices,
        cards: list[PokemonCard] = CARDS,
    ):
        self.storage = storage
        self.pricecharting = pricecharting
        self.product_ids = product_ids or {}
        self.fetch_tcgplayer = fetch_tcgplayer
        self.cards = cards
        self._tcgplayer_attempted_at: datetime | None = None

    def valuation(
        self, card: PokemonCard, now: datetime | None = None
    ) -> Valuation | None:
        now = now or utc_now()
        self.refresh_tcgplayer(now)
        self.refresh_pricecharting(card, now)

        prices = {
            source: record
            for source, record in self.storage.get_prices(card.identifier).items()
            if now - record.fetched_at <= PRICE_STALE_LIMIT
        }
        return value_card(prices)

    def refresh_tcgplayer(self, now: datetime) -> None:
        last = self.storage.latest_price_fetch(TCGPLAYER)
        if last is not None and now - last < PRICE_MAX_AGE:
            return
        attempted = self._tcgplayer_attempted_at
        if attempted is not None and now - attempted < TCGPLAYER_RETRY_AFTER:
            return
        self._tcgplayer_attempted_at = now

        logger.info("Refreshing TCGplayer prices")
        try:
            prices = self.fetch_tcgplayer(self.cards)
        except Exception as error:
            logger.warning("TCGplayer price refresh failed: %s", error)
            return

        for identifier, price in prices.items():
            self.storage.save_price(PriceRecord(
                card_identifier=identifier,
                source=TCGPLAYER,
                fetched_at=now,
                raw_cents=price.market_cents,
            ))

    def refresh_pricecharting(self, card: PokemonCard, now: datetime) -> None:
        product_id = self.product_ids.get(card.identifier)
        if self.pricecharting is None or product_id is None:
            return

        cached = self.storage.get_prices(card.identifier).get(PRICECHARTING)
        if cached is not None and now - cached.fetched_at < PRICE_MAX_AGE:
            return

        logger.info("Fetching PriceCharting price for %s", card.identifier)
        try:
            price = self.pricecharting.product(product_id)
        except (PriceChartingError, OSError) as error:
            logger.warning("PriceCharting lookup for %s failed: %s",
                           card.identifier, error)
            return

        self.storage.save_price(PriceRecord(
            card_identifier=card.identifier,
            source=PRICECHARTING,
            fetched_at=now,
            raw_cents=price.ungraded_cents,
            grade_5_cents=price.grade_5_cents,
            grade_7_cents=price.grade_7_cents,
            sales_volume=price.sales_volume,
        ))
