"""Conservative market values for catalog cards, and deal evaluation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .catalog import Card
from .pricecharting import PriceChartingClient, PriceChartingError
from .storage import PriceRecord, Storage, utc_now
from .tcgcsv import TcgplayerCatalog, TcgPrice, fetch_prices

if TYPE_CHECKING:
    from .game import Game


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
# An auction's current bid will rise before it ends, so it qualifies only
# when the current total is this far below value. The suggested maximum bid
# still keeps the final total MIN_DISCOUNT below value.
MIN_AUCTION_DISCOUNT = 0.40
# The most a suggested maximum bid can be, matching the eBay price filter.
MAX_BID_CENTS = 500000
# A Best Offer listing priced up to this far over value is worth an offer
# of MIN_DISCOUNT below value, which the seller may accept.
MAX_OFFER_PREMIUM = 0.10
# A TCGplayer price this many times below PriceCharting's is flagged as a
# warning on the alert, since it can mean a mismatched or stale product.
MAX_SOURCE_RATIO = 1.5
# With no raw price, a grade 5 copy stands in for a lightly played raw card
# after taking off the premium buyers pay for a graded slab.
GRADE_5_RAW_DISCOUNT = 0.2


@dataclass(frozen=True)
class CardRules:
    """Alert rules for a set or card where they differ from the defaults.
    Each game says which apply to its cards."""
    # The minimum discount for Buy It Now listings. Negative allows a total
    # up to that far over value, as do the other discounts here.
    min_discount: float = MIN_DISCOUNT
    # The most over value a Best Offer listing can be priced to alert.
    max_offer_premium: float = MAX_OFFER_PREMIUM
    # The minimum discount of an auction's current total.
    min_auction_discount: float = MIN_AUCTION_DISCOUNT
    # The discount the suggested maximum bid keeps the final total at.
    max_bid_discount: float = MIN_DISCOUNT
    # The minimum card value to alert on, in cents, e.g. to skip the many
    # promos worth only a few dollars.
    min_value_cents: int | None = None
    # For cards other cards are often listed as, such as reprints under the
    # original set's name: a discount beyond this is taken to mean a
    # different card rather than a bargain. Auctions of these cards are
    # skipped, since a low current bid says nothing about which card it is.
    max_plausible_discount: float | None = None


DEFAULT_RULES = CardRules()


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
    # For an auction, the most to bid so the total stays the card's
    # max_bid_discount below value. Without known shipping it leaves no room
    # for shipping.
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
    rules: CardRules = DEFAULT_RULES,
) -> Deal:
    """Judge a listing against a card's value.

    When shipping is unknown the total is the item price alone, and the
    alert says so rather than the listing being skipped.
    """
    discount = 1 - total_cents / valuation.value_cents

    min_discount = rules.min_discount

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    # Compared in cents, since 1 - 0.9 in floating point is just under 0.1.
    if total_cents > round(valuation.value_cents * (1 - min_discount)):
        if min_discount < 0:
            reasons.append(f"price more than {-min_discount:.0%} over value")
        else:
            reasons.append(f"discount below {min_discount:.0%}")
    min_value = rules.min_value_cents
    if min_value is not None and valuation.value_cents < min_value:
        reasons.append(f"value below ${min_value / 100:,.0f}")
    max_discount = rules.max_plausible_discount
    if (
        max_discount is not None
        and total_cents < round(valuation.value_cents * (1 - max_discount))
    ):
        reasons.append(
            f"discount above {max_discount:.0%}, likely a different card"
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
    rules: CardRules = DEFAULT_RULES,
) -> Deal:
    """Judge a Best Offer listing that isn't a deal at its price, and
    suggest an offer that would make it one."""
    discount = 1 - total_cents / valuation.value_cents
    target_cents = round(valuation.value_cents * (1 - MIN_DISCOUNT))

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    if total_cents > round(valuation.value_cents * (1 + rules.max_offer_premium)):
        reasons.append(f"price more than {rules.max_offer_premium:.0%} over value")
    # A listing already this cheap failed as a deal for another reason, such
    # as a likely reprint, which an offer doesn't change.
    if total_cents <= target_cents:
        reasons.append("price already at or below the offer")
    min_value = rules.min_value_cents
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
    rules: CardRules = DEFAULT_RULES,
) -> Deal:
    """Judge an auction's current bid against a card's value, and suggest
    the most to bid."""
    discount = 1 - total_cents / valuation.value_cents
    max_bid_cents = min(
        round(valuation.value_cents * (1 - rules.max_bid_discount))
        - shipping_cents,
        MAX_BID_CENTS,
    )

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    min_auction_discount = rules.min_auction_discount
    if total_cents > round(valuation.value_cents * (1 - min_auction_discount)):
        if min_auction_discount < 0:
            reasons.append(f"current bid more than {-min_auction_discount:.0%}"
                           " over value")
        else:
            reasons.append(f"current bid less than {min_auction_discount:.0%}"
                           " below value")
    min_value = rules.min_value_cents
    if min_value is not None and valuation.value_cents < min_value:
        reasons.append(f"value below ${min_value / 100:,.0f}")
    if rules.max_plausible_discount is not None:
        reasons.append("auctions skipped, other cards are often listed as this one")

    return Deal(
        total_cents=total_cents,
        valuation=valuation,
        discount=discount,
        qualifies=not reasons,
        reasons=tuple(reasons),
        max_bid_cents=max_bid_cents,
    )


FetchTcgplayer = Callable[[list[Card], TcgplayerCatalog], dict[str, TcgPrice]]


class Pricer:
    """Values one game's cards from cached prices, refreshing them when
    stale.

    TCGplayer prices are refreshed in bulk once a day. PriceCharting prices
    are fetched one card at a time, only for cards that need a value.
    """

    def __init__(
        self,
        storage: Storage,
        game: "Game",
        pricecharting: PriceChartingClient | None = None,
        product_ids: dict[str, str] | None = None,
        fetch_tcgplayer: FetchTcgplayer = fetch_prices,
    ):
        self.storage = storage
        self.game = game
        self.pricecharting = pricecharting
        self.product_ids = product_ids or {}
        self.fetch_tcgplayer = fetch_tcgplayer
        self._tcgplayer_attempted_at: datetime | None = None

    def valuation(
        self, card: Card, now: datetime | None = None
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
        if self.game.tcgplayer is None:
            return
        last = self.storage.latest_price_fetch(TCGPLAYER, game=self.game.key)
        if last is not None and now - last < PRICE_MAX_AGE:
            return
        attempted = self._tcgplayer_attempted_at
        if attempted is not None and now - attempted < TCGPLAYER_RETRY_AFTER:
            return
        self._tcgplayer_attempted_at = now

        logger.info("Refreshing %s TCGplayer prices", self.game.name)
        try:
            prices = self.fetch_tcgplayer(self.game.cards, self.game.tcgplayer)
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

    def refresh_pricecharting(self, card: Card, now: datetime) -> None:
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
