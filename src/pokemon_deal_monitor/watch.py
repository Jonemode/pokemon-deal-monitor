"""Watched cards: any new listing alerts, at any price, with no valuation.

For cards outside the Pokémon catalog, searched in every eBay category.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from .ebay import EbayClient, EbayError, EbayItem
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

    @property
    def identifier(self) -> str:
        """Stored as the listing's card, apart from catalog cards."""
        return f"watch:{self.name}"

    def matches(self, title: str) -> bool:
        return (all(p.search(title) for p in self.required)
                and not any(p.search(title) for p in self.rejected))


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
]


@dataclass(frozen=True)
class WatchHit:
    watch: Watch
    item: EbayItem


@dataclass
class WatchResult:
    hits: list[WatchHit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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
            items = client.search_everywhere(watch.query)
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
            if storage.should_alert(item.item_id):
                result.hits.append(WatchHit(watch, item))
        logger.info("Watched %s: %d listings, %d to alert",
                    watch.name, len(matched),
                    sum(hit.watch is watch for hit in result.hits))
    return result
