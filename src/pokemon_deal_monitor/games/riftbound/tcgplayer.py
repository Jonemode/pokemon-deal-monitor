"""Where Riftbound's signature cards are on TCGplayer."""

from ...tcgcsv import TcgplayerCatalog, product_number_field
from .catalog import RiftboundCard


class RiftboundTcgplayerCatalog(TcgplayerCatalog):

    category_id = 89
    group_ids = {"Origins": 24344, "Spiritforged": 24519}

    def card_number(self, card: RiftboundCard) -> str:
        return card.number

    def product_number(self, product: dict) -> str | None:
        # Signature products are numbered with a star, as the catalog is.
        return product_number_field(product)

    def sub_type_name(self, card: RiftboundCard) -> str:
        return "Foil"


TCGPLAYER = RiftboundTcgplayerCatalog()
