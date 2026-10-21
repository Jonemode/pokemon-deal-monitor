import unittest

from pokemon_deal_monitor.games.pokemon.matcher import RULES
from pokemon_deal_monitor.matcher import normalize


# Realistic eBay titles and the catalog identifiers they should match.
MATCHING_TITLES = [
    # Base Set
    ("Charizard 4/102 Base Set 1st Edition Holo NM",
     ["pokemon:Base Set:4/102:holo:1st"]),
    ("1999 Pokemon Base Set 1st Edition Shadowless Charizard 4/102 Holo",
     ["pokemon:Base Set:4/102:holo:1st"]),
    ("Blastoise 2/102 1st-Edition Base Set Holo Rare",
     ["pokemon:Base Set:2/102:holo:1st"]),
    ("Pokemon 1st Edition Base Mewtwo Holo #10 LP",
     ["pokemon:Base Set:10/102:holo:1st"]),
    # Neo Genesis
    ("Pokemon Lugia 9/111 Neo Genesis 1st Edition Holo LP",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("1st Edition Lugia Neo Genesis Holo Rare WOTC 2000",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("Lugia 9/111 1st Ed Holo Pokemon Card",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("LUGIA 009/111 NEO GENESIS 1ST EDITION HOLO NM",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("Pokémon 1st Edition Neo Gen Lugia Holo #9",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("Typhlosion 17/111 Neo Genesis 1st Edition Holo",
     ["pokemon:Neo Genesis:17/111:holo:1st"]),
    ("Feraligatr Neo Genesis 1st Edition Holo Rare",
     ["pokemon:Neo Genesis:4/111:holo:1st", "pokemon:Neo Genesis:5/111:holo:1st"]),
    # Neo Discovery
    ("Unown [A] 14/75 Neo Discovery 1st Edition Holo",
     ["pokemon:Neo Discovery:14/75:holo:1st"]),
    ("Umbreon 13/75 Neo Discovery 1st Edition Holo Rare WOTC",
     ["pokemon:Neo Discovery:13/75:holo:1st"]),
    # Neo Revelation
    ("Ho-oh 7/64 Neo Revelation 1st Edition Holo",
     ["pokemon:Neo Revelation:7/64:holo:1st"]),
    ("1st Edition Hooh Neo Revelation Holo Rare",
     ["pokemon:Neo Revelation:7/64:holo:1st"]),
    ("Shining Gyarados 65/64 Neo Revelation 1st Edition",
     ["pokemon:Neo Revelation:65/64:holo:1st"]),
    ("Porygon2 Neo Revelation 1st Edition Holo 12/64",
     ["pokemon:Neo Revelation:12/64:holo:1st"]),
    # Neo Destiny
    ("Shining Charizard 107/105 1st Edition Neo Destiny",
     ["pokemon:Neo Destiny:107/105:holo:1st"]),
    ("1st Edition Dark Tyranitar Neo Destiny Holo",
     ["pokemon:Neo Destiny:11/105:holo:1st"]),
    ("Light Dragonite 14/105 Neo Destiny 1st Edition Holo",
     ["pokemon:Neo Destiny:14/105:holo:1st"]),
    # Expedition
    ("Charizard 6/165 Expedition Base Set Holo LP",
     ["pokemon:Expedition:6/165:holo:unlimited"]),
    ("Expedition Charizard Holo Rare Pokemon",
     ["pokemon:Expedition:6/165:holo:unlimited"]),
    # Aquapolis
    ("Umbreon H29/H32 Aquapolis Holo LP",
     ["pokemon:Aquapolis:H29/H32:holo:unlimited"]),
    ("Aquapolis Umbreon H29 Holo",
     ["pokemon:Aquapolis:H29/H32:holo:unlimited"]),
    ("Kingdra Aquapolis Holo Rare",
     ["pokemon:Aquapolis:H14/H32:holo:unlimited"]),
    ("Crystal Kingdra Aquapolis Pokemon Card",
     ["pokemon:Aquapolis:148/147:holo:unlimited"]),
    ("Lugia 149/147 Aquapolis Secret Rare",
     ["pokemon:Aquapolis:149/147:holo:unlimited"]),
    # Crystals without the word: the number, or a name no holo shares.
    ("Kingdra 148/147 Aquapolis Holo",
     ["pokemon:Aquapolis:148/147:holo:unlimited"]),
    ("Lugia Aquapolis Pokemon Card NM",
     ["pokemon:Aquapolis:149/147:holo:unlimited"]),
    ("Kabutops Skyridge Holo Rare",
     ["pokemon:Skyridge:H13/H32:holo:unlimited"]),
    # Skyridge
    ("Crystal Charizard Skyridge Pokemon Card NM",
     ["pokemon:Skyridge:146/144:holo:unlimited"]),
    ("Charizard Skyridge Holo WOTC 2003",
     ["pokemon:Skyridge:146/144:holo:unlimited"]),
    ("Gengar H9/H32 Skyridge Holo NM",
     ["pokemon:Skyridge:H9/H32:holo:unlimited"]),
    ("Poliwrath #9 Neo Discovery 1st Edition Holo",
     ["pokemon:Neo Discovery:9/75:holo:1st"]),
    # Wizards Black Star Promos: the number tells the four Pikachus apart.
    ("Pokemon Mewtwo #3 Black Star Promo WOTC Movie",
     ["pokemon:Wizards Black Star Promos:3/53:normal:unlimited"]),
    ("Pikachu #4 WOTC Black Star Promo NM",
     ["pokemon:Wizards Black Star Promos:4/53:normal:unlimited"]),
    ("Pokemon Pikachu Promo No. 26 Snap",
     ["pokemon:Wizards Black Star Promos:26/53:normal:unlimited"]),
    ("Birthday Pikachu #24 Black Star Promo Holo",
     ["pokemon:Wizards Black Star Promos:24/53:holo:unlimited"]),
    ("_____'s Pikachu #24 WOTC Promo",
     ["pokemon:Wizards Black Star Promos:24/53:holo:unlimited"]),
    ("Team Rocket's Meowth #18 Black Star Promo",
     ["pokemon:Wizards Black Star Promos:18/53:normal:unlimited"]),
    ("Flying Pikachu #25 Wizards Promo",
     ["pokemon:Wizards Black Star Promos:25/53:normal:unlimited"]),
    ("Pokemon Ho-Oh Black Star Promo #52 Pokemon 3",
     ["pokemon:Wizards Black Star Promos:52/53:normal:unlimited"]),
    # Condition words don't reject a title; eBay's Card Condition is used.
    ("Lugia 9/111 Neo Genesis 1st Edition Holo HP",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    ("Lugia 9/111 Neo Genesis 1st Edition Holo MP Damaged",
     ["pokemon:Neo Genesis:9/111:holo:1st"]),
    # Southern Islands
    ("Southern Islands Mew 01/18 Reverse Holo Promo",
     ["pokemon:Southern Islands:1/18:reverse_holo:unlimited"]),
    ("Mew 1/18 Southern Islands Promo",
     ["pokemon:Southern Islands:1/18:reverse_holo:unlimited"]),
    ("Togepi Southern Islands WOTC 2001",
     ["pokemon:Southern Islands:4/18:reverse_holo:unlimited"]),
    ("Marill 11/18 Southern Islands Holo",
     ["pokemon:Southern Islands:11/18:reverse_holo:unlimited"]),
    ("Mew 1/18 Southern Islands Reverse Cosmo Holo WOTC 2001",
     ["pokemon:Southern Islands:1/18:reverse_holo:unlimited"]),
    ("Pokémon TCG Slowking Southern Islands 14/18 Reverse Holo SWIRL 🌀 Promo Card",
     ["pokemon:Southern Islands:14/18:reverse_holo:unlimited"]),
    ("Nintendo Vileplume 17/18 Southern Islands Holo Rare English 2001 70 HP",
     ["pokemon:Southern Islands:17/18:reverse_holo:unlimited"]),
    # Legendary Collection
    ("Charizard 3/110 Legendary Collection Reverse Holo",
     ["pokemon:Legendary Collection:3/110:reverse_holo:unlimited"]),
    ("Legendary Collection Dark Blastoise 4/110 Reverse Foil",
     ["pokemon:Legendary Collection:4/110:reverse_holo:unlimited"]),
    ("Pikachu Legendary Collection Reverse Holo Pokemon",
     ["pokemon:Legendary Collection:86/110:reverse_holo:unlimited"]),
    # Real eBay titles
    ("2002 Pokemon Legendary Collection Zapdos Reverse Holo #19/110",
     ["pokemon:Legendary Collection:19/110:reverse_holo:unlimited"]),
    ("Jolteon 14/110 Legendary Collection Reverse Holo Rare Vintage Pokemon",
     ["pokemon:Legendary Collection:14/110:reverse_holo:unlimited"]),
    ("2002 Pokemon Legendary Collection Flareon Reverse Holo #10/110",
     ["pokemon:Legendary Collection:10/110:reverse_holo:unlimited"]),
    ("Articuno 2/110 Legendary Collection Reverse Holo",
     ["pokemon:Legendary Collection:2/110:reverse_holo:unlimited"]),
    ("2002 POKEMON LEGENDARY COLLECTION #86 PIKACHU-REVERSE FOIL - LP",
     ["pokemon:Legendary Collection:86/110:reverse_holo:unlimited"]),
    ("Pokemon - Legendary LC - Haunter - 46/110 - LP - Reverse Holo",
     ["pokemon:Legendary Collection:46/110:reverse_holo:unlimited"]),
    ("VTG 2001 Pokemon Southern Islands Slowking 14/18 Reverse Holo Promo W/ Swirl LP",
     ["pokemon:Southern Islands:14/18:reverse_holo:unlimited"]),
    ("Machamp [1st Edition] #8 Holo Rare Pokemon Base Set",
     ["pokemon:Base Set:8/102:holo:1st"]),
    ("Pokemon TCG Machamp 8/102 1st Edition Base Set 1999 SEALED NM",
     ["pokemon:Base Set:8/102:holo:1st"]),
    ("Hypno Holo Pokemon e-Card Series Aquapolis #H12 2003",
     ["pokemon:Aquapolis:H12/H32:holo:unlimited"]),
]

# Titles that must not match any catalog card.
REJECTED_TITLES = [
    "Pokemon Lugia 9/111 Neo Genesis Unlimited Holo",
    "No 1st Edition Lugia 9/111 Neo Genesis Holo",
    "Charizard 4/102 Base Set Holo Shadowless",
    "Charizard 4/102 Base Set Unlimited Holo",
    "PSA 7 Lugia Neo Genesis 1st Edition Holo",
    "CGC 9 Charizard 4/102 Base Set 1st Edition",
    "Charizard 4/102 Celebrations Classic Collection",
    " Lugia 149/147 Holo Rare English Aquapolis Pokemon TCG 30th Anniversary ",
    "Charizard 4/130 Base Set 2 Holo",
    "Charizard Base Set 2 Holo Rare",
    "Dark Charizard Team Rocket 1st Edition Holo",
    "Charizard Neo Destiny 1st Edition",
    "Charizard 3/110 Legendary Collection Holo",
    "Charizard 40/165 Expedition Non Holo",
    "Charizard Expedition Pokemon Card Rare",
    "Umbreon H29/H32 Aquapolis Reverse Holo",
    "Japanese Lugia Neo Genesis 1st Edition Holo",
    "Lugia 9/111 Neo Genesis 1st Edition Holo Proxy",
    "Pokemon Neo Genesis 1st Edition Holo Lot x5",
    "Lugia 1st Edition Holo",
    "Charizard 1st Edition Holo Pokemon",
    # Real eBay titles
    "Mew 019/165 Expedition Base Set Reverse Holo Rare - NM/MINT",
    "Rare Item PSA7 Mew Old Back Southern Island O16",
    "PSA10 Pidgeot Old Back Southern Island Pokemon Pokeca O16",
    "Mew Movie Release Commemoration Pack Southern Island O16",
    "Nintendo Pokémon TCG Steelix Haganeeru Neo Genesis JP 1st Ed Holo No.208",
    "Pokemon Southern Islands Rainbow Island 9 Card Set Mew Sealed 1999",
    "VILEPLUME SOUTHERN ISLANDS PROMO POKEMON 3 CARD SET 1998 US SELLER FAST SHIPPING",
    "Abra, Alakazam, Hypno & Wartortle legendary collection collection reverse holo !",
    "Pokemon Alakazam 33/165 Expedition Holo Rare Stage 2 100 HP EN 2002",
    "Nintendo Pokemon TCG Expedition Typhlosion 65/165 Holo Rare 2002 100HP",
    "Ninetales 12/102 Base Set Shadowless Holo Pokemon vintage (Not 1st edition)LP-MP",
    "WOTC Magnemite 91/147 Aquapolis Reverse Holo foreign 🇮🇹 ITA",
    # The non-holo Poliwrath; the holo is 9/75.
    "Poliwrath 1st Ed. Pokemon Neo Discovery #28 2001",
    # Promos: no number, a stamped version, or a modern Black Star Promo.
    "Pikachu Black Star Promo WOTC Vintage",
    "Mewtwo #3 Black Star Promo Prerelease Stamp",
    "Pikachu #26 Black Star Promo W Stamped",
    "Pikachu SWSH020 Black Star Promo",
    "Mewtwo SM 210 Black Star Promo",
    "Pikachu #4 Nintendo Black Star Promo",
    "Pokémon Mega Venusaur EX Black Star Promo 013 Mega Evolution NM",
    "Charizard MEP 005 Black Star Promo",
    # Southern Islands cards that only come as non-holo, or "Regular".
    "Butterfree 09/18 Southern Islands Regular",
    "Pidgeot 02/18 Southern Islands - Pokemon TCG Vintage",
    "Pokémon TCG Pidgeot Southern Islands Regular Stage 2 70 HP English 2/18 2001",
    "Pokémon TCG DOUBLE SWIRL 💫 Vileplume #17 SOUTHERN ISLANDS NM-MT 8",
]


class TestListingMatcher(unittest.TestCase):

    def test_matching_titles(self):
        for title, expected in MATCHING_TITLES:
            with self.subTest(title=title):
                matches = RULES.match(title)
                self.assertEqual(
                    sorted(match.card.identifier for match in matches),
                    sorted(expected),
                )

    def test_rejected_titles(self):
        for title in REJECTED_TITLES:
            with self.subTest(title=title):
                self.assertEqual(RULES.match(title), [])

    def test_confidence_with_all_evidence(self):
        (match,) = RULES.match("Lugia 9/111 Neo Genesis 1st Edition Holo")
        self.assertEqual(match.confidence, 1.0)

    def test_confidence_without_set(self):
        (match,) = RULES.match("Lugia 9/111 1st Edition Holo")
        self.assertEqual(match.confidence, 0.7)

    def test_confidence_without_number(self):
        (match,) = RULES.match("Lugia Neo Genesis 1st Edition Holo")
        self.assertEqual(match.confidence, 0.6)

    def test_unexpected_first_edition_lowers_confidence(self):
        (match,) = RULES.match("Umbreon H29/H32 Aquapolis 1st Edition Holo")
        self.assertEqual(match.confidence, 0.8)

    def test_normalize(self):
        self.assertEqual(
            normalize("Pokémon  Ho-Oh [1st-Edition] #7"),
            "pokemon ho oh 1st edition #7",
        )


if __name__ == "__main__":
    unittest.main()
