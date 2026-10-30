import unittest

from pokemon_deal_monitor.games.pokemon.catalog import CARDS, Variant
from pokemon_deal_monitor.games.pokemon.game import ALERT_RULES, POKEMON, REVERSE_HOLO_ART_RULES


def card(set_name, number):
    (found,) = [c for c in CARDS if c.set_name == set_name and c.number == number
                and c.variant == Variant.REVERSE_HOLO]
    return found


def in_catalog(set_name, number):
    return any(c.set_name == set_name and c.number == number
               and c.variant == Variant.REVERSE_HOLO for c in CARDS)


def matches(title):
    return [(m.card.set_name, m.card.number, m.card.variant)
            for m in POKEMON.title_rules.match(title)]


class TestReverseHolosWithUniqueArt(unittest.TestCase):

    def test_cards_no_holo_shares_art_with_are_targeted(self):
        for set_name, number in (
            ("Aquapolis", "57/147"),    # Scyther
            ("Aquapolis", "106/147"),   # The other Scyther.
            ("Expedition", "121/165"),  # Meowth
            ("Expedition", "36/165"),   # A different Blastoise from the holo's.
            ("Expedition", "39/165"),   # A different Charizard from the holo's.
            ("Skyridge", "1/144"),      # Aerodactyl, with no holo at all.
        ):
            self.assertTrue(in_catalog(set_name, number), number)

    def test_cards_sharing_a_holos_art_are_not(self):
        for set_name, number in (
            ("Expedition", "6/165"),    # The holo itself.
            ("Expedition", "40/165"),   # Charizard, with the holo's art.
            ("Aquapolis", "2/147"),     # Arcanine, with H2's art.
            ("Skyridge", "10/144"),     # Gengar, with H9's art.
        ):
            self.assertFalse(in_catalog(set_name, number), number)

    def test_matches_how_sellers_title_them(self):
        for title, expected in (
            ("Scyther 57/147 Aquapolis Reverse Holo Pokemon Card",
             ("Aquapolis", "57/147")),
            ("Meowth 121/165 Expedition Base Set Reverse Holo",
             ("Expedition", "121/165")),
            ("Hoothoot Reverse Foil Pokemon e-Card Series Skyridge #65 2003",
             ("Skyridge", "65/144")),
        ):
            self.assertEqual(matches(title), [(*expected, Variant.REVERSE_HOLO)], title)

    def test_other_printings_are_not_matched(self):
        for title in (
            # The regular copy, with the same number.
            "Meowth 121/165 Expedition Base Set",
            "Meowth 121/165 Expedition Non Reverse",
            # Without a number it could be another reverse holo of the name.
            "Charizard Reverse Holo Expedition",
            # Reverse holos sharing a holo's art.
            "Charizard 40/165 Expedition Reverse Holo",
            "Alakazam 1/165 Reverse Holo Expedition",
        ):
            self.assertEqual(matches(title), [], title)

    def test_holos_still_match(self):
        self.assertEqual(matches("Charizard 6/165 Expedition Holo"),
                         [("Expedition", "6/165", Variant.HOLO)])

    def test_alert_only_at_50_dollars_or_more(self):
        self.assertIs(POKEMON.rules_for(card("Expedition", "121/165")),
                      REVERSE_HOLO_ART_RULES)
        self.assertEqual(REVERSE_HOLO_ART_RULES.min_value_cents, 5000)
        (holo,) = [c for c in CARDS if c.set_name == "Expedition"
                   and c.number == "6/165"]
        self.assertIs(POKEMON.rules_for(holo), ALERT_RULES)
