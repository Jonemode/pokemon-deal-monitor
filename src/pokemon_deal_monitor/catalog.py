
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Variant(str, Enum):
    HOLO = "holo"
    REVERSE_HOLO = "reverse_holo"


@dataclass(frozen=True)
class PokemonCard:
    name: str
    set_name: str
    number: str
    variant: Variant
    first_edition_required: bool = False

    @property
    def identifier(self) -> str:
        edition = "1st" if self.first_edition_required else "unlimited"
        return (
            f"{self.set_name}:{self.number}:"
            f"{self.variant.value}:{edition}"
        )


# Resolve the repository root relative to this source file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "cards.json"


def load_catalog(path: Path | None = None) -> list[PokemonCard]:
    """Load and validate the Pokemon card catalog from JSON."""
    catalog_path = path if path is not None else DEFAULT_CATALOG_PATH

    with catalog_path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Catalog must be a JSON array")

    cards = []
    identifiers = set()

    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Card at index {index} must be an object")

        try:
            name = entry["name"]
            set_name = entry["set_name"]
            number = entry["number"]
            variant = Variant(entry["variant"])
            first_edition_required = entry["first_edition_required"]
        except (KeyError, ValueError) as error:
            raise ValueError(
                f"Invalid card at index {index}: {error}"
            ) from error

        for field_name, value in (
            ("name", name),
            ("set_name", set_name),
            ("number", number),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Card at index {index} has invalid {field_name}"
                )

        if type(first_edition_required) is not bool:
            raise ValueError(
                f"Card at index {index} has invalid first_edition_required"
            )

        card = PokemonCard(
            name=name.strip(),
            set_name=set_name.strip(),
            number=number.strip(),
            variant=variant,
            first_edition_required=first_edition_required,
        )

        if card.identifier in identifiers:
            raise ValueError(
                f"Duplicate card identifier: {card.identifier}"
            )

        identifiers.add(card.identifier)
        cards.append(card)

    return cards


CARDS = load_catalog()

