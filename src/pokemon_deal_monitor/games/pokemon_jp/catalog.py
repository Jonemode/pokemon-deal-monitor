"""Japanese Pokémon cards, kept apart from the English catalog since their
titles, languages and prices differ."""

from dataclasses import dataclass

from ...catalog import Card


GAME = "pokemon_jp"


@dataclass(frozen=True)
class JapanesePokemonCard(Card):
    variant: str = "holo"

    game = GAME

    @property
    def printing(self) -> str:
        return self.variant


# Few enough to list by hand.
CARDS = [
    # The Shining Mew given away with CoroCoro Comic's May 2001 issue,
    # numbered 151.
    JapanesePokemonCard("Shining Mew", "CoroCoro Promo", "151"),
]
