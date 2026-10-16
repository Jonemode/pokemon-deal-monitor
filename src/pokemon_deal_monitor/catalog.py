
from dataclasses import dataclass
from enum import Enum


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


# Initial examples only. We'll expand the catalog later.
CARDS = [
    PokemonCard(
        name="Lugia",
        set_name="Neo Genesis",
        number="9/111",
        variant=Variant.HOLO,
        first_edition_required=True,
    ),
    PokemonCard(
        name="Charizard",
        set_name="Base Set",
        number="4/102",
        variant=Variant.HOLO,
        first_edition_required=True,
    ),
    PokemonCard(
        name="Umbreon",
        set_name="Aquapolis",
        number="H29/H32",
        variant=Variant.HOLO,
    ),
    PokemonCard(
        name="Charizard",
        set_name="Legendary Collection",
        number="3/110",
        variant=Variant.REVERSE_HOLO,
    ),
]

