"""Cards to monitor, shared by every game's catalog."""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


# Resolve the repository root relative to this source file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Card:
    """A catalog card. Each game subclasses it with the fields that tell
    its printings apart, and sets game."""
    name: str
    set_name: str
    number: str

    # The game's key, e.g. "pokemon", which starts every identifier so
    # cards from different games never share one.
    game: ClassVar[str]

    @property
    def printing(self) -> str:
        """What tells this printing apart from others with the same set and
        number, e.g. "holo:1st"."""
        raise NotImplementedError

    @property
    def identifier(self) -> str:
        return f"{self.game}:{self.set_name}:{self.number}:{self.printing}"
