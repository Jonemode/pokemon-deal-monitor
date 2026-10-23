"""What the monitor needs to know about each trading card game."""

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .catalog import Card
from .matcher import TitleRules
from .tcgcsv import TcgplayerCatalog
from .valuation import DEFAULT_RULES, CardRules


# eBay Language values for English, lowercased. Sellers on other eBay sites
# name English in their own language.
ENGLISH = frozenset({"english", "inglese", "englisch", "anglais", "inglés",
                     "ingles", "engels"})


@dataclass(frozen=True)
class Game:
    # Starts the identifiers of the game's cards, e.g. "pokemon".
    key: str
    name: str
    cards: list[Card]
    title_rules: TitleRules
    # eBay searches, each one call per poll, so their number sets how much
    # of eBay's daily call limit the game uses.
    searches: list[str]
    # How often a Buy It Now search runs, by search, when less often than
    # every poll. A quiet search's newest results reach back many hours, so
    # searching it less often delays its alerts without missing listings.
    search_intervals: dict[str, timedelta] = field(default_factory=dict)
    # None when TCGplayer prices aren't used.
    tcgplayer: TcgplayerCatalog | None = None
    # The file mapping card identifiers to PriceCharting product IDs.
    pricecharting_ids_path: Path | None = None
    # eBay Language values to accept, lowercased. A blank Language is
    # accepted too.
    languages: frozenset[str] = ENGLISH
    # Alert rules differing from the defaults, by set name or, replacing
    # the set's, by card identifier.
    set_rules: dict[str, CardRules] = field(default_factory=dict)
    card_rules: dict[str, CardRules] = field(default_factory=dict)

    def rules_for(self, card: Card) -> CardRules:
        return self.card_rules.get(
            card.identifier, self.set_rules.get(card.set_name, DEFAULT_RULES)
        )

    def searches_due(
        self, last_searched: dict[str, float], now: float, poll_interval: float
    ) -> list[str]:
        """Return the Buy It Now searches due at a time.monotonic() time,
        given when each last ran. A second's leeway allows for a sleep
        waking slightly early."""
        return [
            query for query in self.searches
            if query not in last_searched
            or now - last_searched[query] >= self.search_intervals.get(
                query, timedelta(seconds=poll_interval)
            ).total_seconds() - 1
        ]
