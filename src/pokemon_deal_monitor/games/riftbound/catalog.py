"""Riftbound's signature cards: overnumbered champions printed with a
signature, numbered with a star, e.g. 299*/298."""

import json
from dataclasses import dataclass
from pathlib import Path

from ...catalog import DATA_DIR, Card


GAME = "riftbound"


@dataclass(frozen=True)
class RiftboundCard(Card):

    game = GAME

    @property
    def printing(self) -> str:
        return "signature"

    @property
    def champion(self) -> str:
        """The champion, e.g. "Kai'Sa" for "Kai'Sa, Daughter of the
        Void"."""
        return self.name.split(",")[0]

    @property
    def title(self) -> str:
        """The champion's title, e.g. "Daughter of the Void"."""
        return self.name.partition(", ")[2]


DEFAULT_CATALOG_PATH = DATA_DIR / GAME / "cards.json"


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[RiftboundCard]:
    with path.open(encoding="utf-8") as file:
        return [RiftboundCard(entry["name"], entry["set_name"], entry["number"])
                for entry in json.load(file)]


CARDS = load_catalog()
