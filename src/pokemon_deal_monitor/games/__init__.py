"""The trading card games monitored, one package each."""

from .pokemon.game import POKEMON
from .pokemon_jp.game import POKEMON_JP
from .riftbound.game import RIFTBOUND


GAMES = [POKEMON, POKEMON_JP, RIFTBOUND]
