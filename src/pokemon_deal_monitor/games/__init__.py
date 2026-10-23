"""The trading card games monitored, one package each."""

from .pokemon.game import POKEMON
from .pokemon_jp.game import POKEMON_JP


GAMES = [POKEMON, POKEMON_JP]
