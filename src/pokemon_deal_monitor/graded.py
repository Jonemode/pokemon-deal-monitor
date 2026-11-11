"""Reading a graded card's grade from its eBay title.

Graded listings are valued against PriceCharting's price for their grade,
which covers every grading company. Only the grades with their own price
are read: whole grades, and 7.5 and 8.5, which PriceCharting prices with
7 and 8. Half grades below 7 have no price of their own, so they aren't
alerted on.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Grade:
    # As alerts show it, e.g. "PSA".
    grader: str
    # As the title writes it, e.g. "7.5".
    label: str
    # The PriceCharting grade it's valued at, e.g. 7 for 7.5.
    price_grade: int

    def __str__(self) -> str:
        return f"{self.grader} {self.label}"


GRADERS = {"psa": "PSA", "bgs": "BGS", "beckett": "BGS", "cgc": "CGC",
           "sgc": "SGC"}

# "PSA 7", "PSA7", "PSA-7", "BGS 7.5". Not "PSA 7/110", a card number.
GRADE_PATTERN = re.compile(
    r"\b(psa|bgs|beckett|cgc|sgc)\s*-?\s*(10|[1-9](?:\.5)?)\b(?![./]\d)",
    re.IGNORECASE,
)

# Words a graded title carries that the card matcher rejects, to strip
# before matching the card itself.
GRADED_WORDS = re.compile(
    r"\b(?:psa|bgs|beckett|cgc|sgc|graded|slabbed|slab)\b", re.IGNORECASE
)


def parse_grade(title: str) -> Grade | None:
    """Return a title's grade, or None if it has none or several, as a
    listing of more than one slab does."""
    found = {(GRADERS[grader.lower()], label)
             for grader, label in GRADE_PATTERN.findall(title)}
    if len(found) != 1:
        return None
    ((grader, label),) = found
    value = float(label)
    if value != int(value) and value not in (7.5, 8.5):
        return None
    return Grade(grader, label, int(value))


def strip_grade(title: str) -> str:
    """Return a graded title without its grade, for matching the card."""
    return GRADED_WORDS.sub(" ", GRADE_PATTERN.sub(" ", title))
