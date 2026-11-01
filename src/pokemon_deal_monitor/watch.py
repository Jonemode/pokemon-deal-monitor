"""Watched cards: any new listing alerts, with no valuation, unless the watch
sets a price limit or languages.

For cards outside the catalogs, searched in every eBay category.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from .ebay import EbayClient, EbayError, EbayItem
from .game import JAPANESE
from .storage import Storage, utc_now


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Watch:
    # Shown as the alert's heading.
    name: str
    query: str
    # A title must match every one of these, and none of rejected.
    required: tuple[re.Pattern, ...]
    rejected: tuple[re.Pattern, ...] = ()
    # A listing costing this much or more, with any shipping, doesn't alert.
    max_cents: int | None = None
    # eBay Language values to accept, lowercased, looked up once per listing
    # that would otherwise alert. A blank Language is accepted too.
    languages: frozenset[str] | None = None
    # A title matching this needs no lookup: some sellers leave eBay's default
    # Language of English on foreign cards.
    language_title: re.Pattern | None = None
    # False for cards mostly sold from abroad.
    us_sellers_only: bool = True
    # Searched every poll, rather than only when auctions are.
    every_poll: bool = False

    @property
    def identifier(self) -> str:
        """Stored as the listing's card, apart from catalog cards."""
        return f"watch:{self.name}"

    def matches(self, title: str) -> bool:
        return (all(p.search(title) for p in self.required)
                and not any(p.search(title) for p in self.rejected))

    def within_price(self, item: EbayItem) -> bool:
        return (self.max_cents is None
                or item.price_cents + (item.shipping_cents or 0) < self.max_cents)


WATCHES = [
    # A plain "cornholio" search finds hundreds of shirts and other items,
    # crowding out the card, so eBay's OR syntax narrows it. The title check
    # then drops animation cels and the 1994 Topps MTV card.
    Watch(
        name="Cornholio · 1995 Fleer Ultra MTV Animation",
        query="cornholio (fleer, ultra, animation)",
        required=(
            re.compile(r"\bcornholio\b", re.IGNORECASE),
            re.compile(r"\b(?:fleer|ultra|mtv animation)\b", re.IGNORECASE),
        ),
        rejected=(re.compile(r"\btopps\b", re.IGNORECASE),),
    ),
    # Japanese listings say "Foil Stamped" where English ones copy TCGplayer's
    # "Gold Stamped". Asking prices are about twice the limit, so one under it
    # won't last, hence every poll. "-don" drops the set's Gold DON!! cards,
    # which would otherwise fill the results.
    Watch(
        name="Nami · EB05-055 Gold Stamp · Japanese",
        query="nami (eb05, yabuki) (stamp, stamped, signed, signature, gold) -don",
        required=(
            re.compile(r"\bnami\b", re.IGNORECASE),
            re.compile(r"\beb-?05\W?055\b|\(055\)|\byabuki\b", re.IGNORECASE),
            re.compile(r"\b(?:stamp|stamped|signed|signature|gold)\b",
                       re.IGNORECASE),
        ),
        rejected=(re.compile(
            r"\b(?:english|eng|en|chinese|korean|don|"
            r"proxy|custom|orica|fake|replica)\b", re.IGNORECASE),),
        max_cents=70000,
        languages=JAPANESE,
        language_title=re.compile(r"\b(?:japanese|japan|jpn|jp)\b", re.IGNORECASE),
        us_sellers_only=False,
        every_poll=True,
    ),
]


@dataclass(frozen=True)
class WatchHit:
    watch: Watch
    item: EbayItem


@dataclass
class WatchResult:
    hits: list[WatchHit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def language_accepted(
    client: EbayClient, storage: Storage, watch: Watch, item: EbayItem,
    now: datetime,
) -> bool:
    if watch.languages is None:
        return True
    if watch.language_title and watch.language_title.search(item.title):
        return True
    stored = storage.get_listing(item.item_id)
    if stored.details_fetched_at is not None:
        language = stored.language
    else:
        details = client.item_details(item.item_id)
        storage.save_details(item.item_id, details.card_condition,
                             details.language, now=now)
        language = details.language
    return language is None or language.lower() in watch.languages


def poll_watches(
    client: EbayClient,
    storage: Storage,
    watches: list[Watch] = WATCHES,
    now: datetime | None = None,
) -> WatchResult:
    """Search each watched card and return listings not yet alerted on."""
    now = now or utc_now()
    result = WatchResult()
    for watch in watches:
        try:
            items = client.search_everywhere(
                watch.query, us_sellers_only=watch.us_sellers_only)
        except (EbayError, OSError) as error:
            logger.warning("Watch search %r failed: %s", watch.query, error)
            result.errors.append(f"{watch.query}: {error}")
            continue

        matched = [item for item in items if watch.matches(item.title)]
        for item in matched:
            storage.upsert_listing(
                item.to_listing(card_identifier=watch.identifier,
                                match_confidence=1.0),
                now=now,
            )
            if not (storage.should_alert(item.item_id)
                    and watch.within_price(item)):
                continue
            try:
                if language_accepted(client, storage, watch, item, now):
                    result.hits.append(WatchHit(watch, item))
            except (EbayError, OSError) as error:
                logger.warning("Details for %s failed: %s", item.item_id, error)
                result.errors.append(f"details {item.item_id}: {error}")
        logger.info("Watched %s: %d listings, %d to alert",
                    watch.name, len(matched),
                    sum(hit.watch is watch for hit in result.hits))
    return result
