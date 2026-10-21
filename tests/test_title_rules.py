import re
import unittest
from dataclasses import dataclass

from pokemon_deal_monitor.catalog import Card
from pokemon_deal_monitor.matcher import TitleRules


@dataclass(frozen=True)
class ExampleCard(Card):
    """A card from a made-up game numbered like One Piece, e.g. OP01-120."""
    alt_art: bool = False

    game = "example"

    @property
    def printing(self) -> str:
        return "alt_art" if self.alt_art else "regular"


NUMBER_PATTERN = re.compile(r"\b(op\d{2}) ?(\d{3})\b")
ALT_ART_PATTERN = re.compile(r"\b(?:alt art|parallel)\b")


class ExampleRules(TitleRules):
    set_aliases = {"Romance Dawn": ["romance dawn", "op01"]}
    other_set_aliases = ["paramount war"]
    reject_patterns = [r"\bjapanese\b"]

    def title_numbers(self, text):
        return {f"{m[1]}-{m[2]}" for m in NUMBER_PATTERN.finditer(text)}, set()

    def parse_card_number(self, number):
        return number.lower(), number.lower()

    def score_printing(self, card, text, title_full_numbers):
        if card.alt_art != bool(ALT_ART_PATTERN.search(text)):
            return None
        return 0.0


SHANKS = ExampleCard("Shanks", "Romance Dawn", "OP01-120")
SHANKS_ALT = ExampleCard("Shanks", "Romance Dawn", "OP01-120", alt_art=True)
RULES = ExampleRules([SHANKS, SHANKS_ALT])


class TestTitleRules(unittest.TestCase):

    def test_identifier_starts_with_game(self):
        self.assertEqual(SHANKS_ALT.identifier,
                         "example:Romance Dawn:OP01-120:alt_art")

    def test_matches_with_game_numbers_and_printings(self):
        (match,) = RULES.match("One Piece Shanks OP01-120 Romance Dawn SEC")
        self.assertEqual(match.card, SHANKS)
        self.assertEqual(match.confidence, 1.0)
        (match,) = RULES.match("Shanks OP01-120 Alt Art Parallel")
        self.assertEqual(match.card, SHANKS_ALT)

    def test_shared_and_game_rejections(self):
        for title in ("Shanks OP01-120 PSA 10", "Shanks OP01-120 Japanese",
                      "Shanks OP01-121 Romance Dawn",
                      "Shanks Paramount War", "Shanks alt art"):
            self.assertEqual(RULES.match(title), [], title)


if __name__ == "__main__":
    unittest.main()
