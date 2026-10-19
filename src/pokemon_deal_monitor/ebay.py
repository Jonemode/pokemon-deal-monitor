import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from .config import EbayConfig
from .storage import Listing


API_HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}
BROWSE_SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE_ID = "EBAY_US"
CCG_INDIVIDUAL_CARDS_CATEGORY = "183454"
MAX_PRICE_USD = 5000
PAGE_LIMIT = 200

# Refresh the access token this many seconds before eBay says it expires.
TOKEN_EXPIRY_MARGIN = 60

# Sent on every request. Cloudflare, in front of PriceCharting, rejects
# Python's default "Python-urllib" agent with error 1010.
USER_AGENT = "pokemon-deal-monitor/0.1 (+https://github.com/Jonemode/pokemon-deal-monitor)"

Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


class EbayError(Exception):

    def __init__(self, status: int, body: bytes):
        super().__init__(f"eBay API returned HTTP {status}: {body[:500]!r}")
        self.status = status


def urllib_transport(request: urllib.request.Request) -> tuple[int, bytes]:
    if not request.has_header("User-agent"):
        request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@dataclass(frozen=True)
class EbayItem:
    item_id: str
    title: str
    url: str
    price_cents: int
    currency: str
    # None when eBay reports calculated shipping without a cost.
    shipping_cents: int | None
    condition: str | None = None
    image_url: str | None = None
    created_at: str | None = None
    # For an auction, price_cents is the current bid.
    auction: bool = False
    ends_at: datetime | None = None
    bid_count: int | None = None
    # A Buy It Now listing that also takes offers.
    best_offer: bool = False

    def to_listing(
        self,
        card_identifier: str | None = None,
        match_confidence: float | None = None,
    ) -> Listing:
        return Listing(
            item_id=self.item_id,
            title=self.title,
            url=self.url,
            price_cents=self.price_cents,
            shipping_cents=self.shipping_cents or 0,
            currency=self.currency,
            card_identifier=card_identifier,
            match_confidence=match_confidence,
            condition=self.condition,
            shipping_known=self.shipping_cents is not None,
        )


def to_cents(value: str) -> int:
    cents = Decimal(value) * 100
    return int(cents.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_shipping(summary: dict) -> int | None:
    """Return the cheapest listed shipping cost in cents, if any."""
    costs = [
        to_cents(option["shippingCost"]["value"])
        for option in summary.get("shippingOptions", [])
        if "shippingCost" in option
    ]
    return min(costs) if costs else None


@dataclass(frozen=True)
class ItemDetails:
    """Fields only the full listing has, not search results.

    Search filters can't select listings that leave these blank, so they
    are looked up per listing instead.
    """
    # The "Card Condition" of an ungraded card, e.g. "Near mint or better".
    card_condition: str | None = None
    language: str | None = None
    # An auction's reserve: None when it has none or eBay doesn't say.
    reserve_met: bool | None = None


# eBay's Card Condition values. Sellers on other eBay sites get descriptor
# names in their own language, e.g. "Condizione della carta", but the values
# stay in English, so a descriptor with one of these values is the condition.
CARD_CONDITIONS = {
    "near mint or better",
    "lightly played (excellent)",
    "moderately played (very good)",
    "heavily played (poor)",
}

# "Language" as other eBay sites name it.
LANGUAGE_NAMES = {"language", "lingua", "sprache", "langue", "idioma", "taal"}


def parse_details(item: dict) -> ItemDetails:
    card_condition = next(
        (
            value["content"]
            for descriptor in item.get("conditionDescriptors", [])
            for value in descriptor.get("values", [])
            if value.get("content")
            and (descriptor.get("name") == "Card Condition"
                 or value["content"].lower() in CARD_CONDITIONS)
        ),
        None,
    )
    language = next(
        (
            aspect["value"]
            for aspect in item.get("localizedAspects", [])
            if (aspect.get("name") or "").lower() in LANGUAGE_NAMES
            and aspect.get("value")
        ),
        None,
    )
    return ItemDetails(
        card_condition=card_condition,
        language=language,
        reserve_met=item.get("reservePriceMet"),
    )


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_item(summary: dict, auction: bool = False) -> EbayItem | None:
    """Convert a Browse API itemSummary, or None if it lacks a price.

    For an auction the price is the current bid, not any Buy It Now price.
    """
    price = summary.get("currentBidPrice") if auction else None
    price = price or summary.get("price")
    if not price or "value" not in price:
        return None

    return EbayItem(
        item_id=summary["itemId"],
        title=summary["title"],
        url=summary["itemWebUrl"],
        price_cents=to_cents(price["value"]),
        currency=price.get("currency", "USD"),
        shipping_cents=parse_shipping(summary),
        condition=summary.get("condition"),
        image_url=summary.get("image", {}).get("imageUrl"),
        created_at=summary.get("itemCreationDate"),
        auction=auction,
        ends_at=parse_time(summary.get("itemEndDate")) if auction else None,
        bid_count=summary.get("bidCount") if auction else None,
        best_offer=not auction and "BEST_OFFER" in summary.get("buyingOptions", []),
    )


class EbayClient:
    """Minimal eBay Browse API client using an application access token."""

    def __init__(
        self,
        config: EbayConfig,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self.host = API_HOSTS[config.environment]
        self.transport = transport
        self.clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def access_token(self) -> str:
        if self._token is not None and self.clock() < self._token_expires_at:
            return self._token

        credentials = f"{self.config.app_id}:{self.config.cert_id}".encode()
        request = urllib.request.Request(
            f"{self.host}/identity/v1/oauth2/token",
            data=urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "scope": BROWSE_SCOPE,
            }).encode(),
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        status, body = self.transport(request)
        if status != 200:
            raise EbayError(status, body)

        payload = json.loads(body)
        self._token = payload["access_token"]
        self._token_expires_at = (
            self.clock() + payload["expires_in"] - TOKEN_EXPIRY_MARGIN
        )
        return self._token

    def search(
        self,
        query: str,
        limit: int = PAGE_LIMIT,
        auctions_ending_before: datetime | None = None,
    ) -> list[EbayItem]:
        """Return the newest Buy It Now card listings matching a query, or
        with auctions_ending_before, auctions ending by then, soonest first."""
        if auctions_ending_before is None:
            buying_filter = "buyingOptions:{FIXED_PRICE}"
            sort = "newlyListed"
        else:
            buying_filter = (
                "buyingOptions:{AUCTION},"
                f"itemEndDate:[..{format_time(auctions_ending_before)}]"
            )
            sort = "endingSoonest"
        params = urllib.parse.urlencode({
            "q": query,
            "category_ids": CCG_INDIVIDUAL_CARDS_CATEGORY,
            "filter": (
                f"{buying_filter},"
                f"price:[..{MAX_PRICE_USD}],priceCurrency:USD"
            ),
            "sort": sort,
            "limit": str(limit),
        })
        url = f"{self.host}/buy/browse/v1/item_summary/search?{params}"

        auction = auctions_ending_before is not None
        summaries = self._get_json(url).get("itemSummaries", [])
        items = (parse_item(summary, auction) for summary in summaries)
        return [item for item in items if item is not None]

    def item_details(self, item_id: str) -> ItemDetails:
        """Return a listing's card condition, language and reserve."""
        quoted = urllib.parse.quote(item_id, safe="")
        return parse_details(
            self._get_json(f"{self.host}/buy/browse/v1/item/{quoted}")
        )

    def _get_json(self, url: str) -> dict:
        status, body = self._get(url)
        if status == 401:
            # The token may have been revoked early; retry once with a new one.
            self._token = None
            status, body = self._get(url)
        if status != 200:
            raise EbayError(status, body)
        return json.loads(body)

    def _get(self, url: str) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
            },
        )
        return self.transport(request)
