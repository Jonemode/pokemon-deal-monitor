"""Conservative market values for catalog cards, and deal evaluation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .catalog import CARDS, PokemonCard
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
MIN_DISCOUNT = 0.25
# Two raw price sources must agree within this ratio for a confident value.
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


@dataclass(frozen=True)
class Deal:
    total_cents: int
    valuation: Valuation
    discount: float
    qualifies: bool
    # Why the listing does not qualify; empty when it does.
    reasons: tuple[str, ...] = ()


def value_card(prices: dict[str, PriceRecord]) -> Valuation | None:
    """Return a conservative value for a card from its cached prices.

    The value is the lowest raw estimate, capped at the grade 7 price since
    a raw card rarely sells above a graded near mint copy.
    """
    pricecharting = prices.get(PRICECHARTING)
    tcgplayer = prices.get(TCGPLAYER)

    estimates = {}
    if pricecharting and pricecharting.raw_cents:
        estimates[PRICECHARTING] = pricecharting.raw_cents
    if tcgplayer and tcgplayer.raw_cents:
        estimates[TCGPLAYER] = tcgplayer.raw_cents

    notes = []
    if estimates:
        value = min(estimates.values())
        ratio = max(estimates.values()) / value
        confident = len(estimates) > 1 and ratio <= MAX_SOURCE_RATIO
        if len(estimates) == 1:
            notes.append("only one price source")
        elif not confident:
            notes.append(f"sources disagree by {ratio:.1f}x")
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
    )


def evaluate_deal(
    total_cents: int, shipping_known: bool, valuation: Valuation
) -> Deal:
    discount = 1 - total_cents / valuation.value_cents

    reasons = []
    if not valuation.confident:
        reasons.append("value not confident")
    if not shipping_known:
        reasons.append("shipping cost unknown")
    if discount < MIN_DISCOUNT:
        reasons.append(f"discount below {MIN_DISCOUNT:.0%}")

    return Deal(
        total_cents=total_cents,
        valuation=valuation,
        discount=discount,
        qualifies=not reasons,
        reasons=tuple(reasons),
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
