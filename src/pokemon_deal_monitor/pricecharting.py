"""PriceCharting API client for ungraded and graded card prices."""

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .ebay import Transport, urllib_transport


API_URL = "https://www.pricecharting.com/api"

# PriceCharting allows at most one API call per second.
MIN_SECONDS_BETWEEN_CALLS = 1.0

# Cloudflare in front of PriceCharting answers sustained bursts with HTTP
# 429 even within the documented limit, or sometimes by dropping the
# connection. Back off and retry either: 30s, 60s, ...
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF_SECONDS = 30.0

logger = logging.getLogger(__name__)

class PriceChartingError(Exception):

    def __init__(self, status: int, message: str):
        super().__init__(f"PriceCharting returned HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class PriceChartingPrice:
    product_id: str
    product_name: str
    # Prices in cents; None when PriceCharting has no value for that grade.
    ungraded_cents: int | None
    grade_5_cents: int | None
    grade_7_cents: int | None
    # Units sold over the last year, across all grades.
    sales_volume: int | None


def optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def parse_product(product: dict) -> PriceChartingPrice:
    # PriceCharting reuses video game field names for card grades:
    # "loose" is ungraded and "cib" is grade 7.
    return PriceChartingPrice(
        product_id=str(product["id"]),
        product_name=product.get("product-name", ""),
        ungraded_cents=optional_int(product.get("loose-price")),
        grade_5_cents=optional_int(product.get("condition-15-price")),
        grade_7_cents=optional_int(product.get("cib-price")),
        sales_volume=optional_int(product.get("sales-volume")),
    )


def load_product_ids(path: Path) -> dict[str, str]:
    """Load a game's map of catalog card identifiers to PriceCharting
    product IDs, written by scripts/map_pricecharting.py."""
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {
        identifier: entry["product_id"]
        for identifier, entry in entries.items()
        if entry.get("product_id")
    }


class PriceChartingClient:

    def __init__(
        self,
        token: str,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_seconds_between_calls: float = MIN_SECONDS_BETWEEN_CALLS,
    ):
        self.token = token
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.min_seconds_between_calls = min_seconds_between_calls
        self._last_call_at: float | None = None

    def product(self, product_id: str) -> PriceChartingPrice:
        return parse_product(self._get("product", id=product_id))

    def search(self, query: str) -> list[dict]:
        """Return up to 20 raw product records matching a search."""
        return self._get("products", q=query).get("products", [])

    def _get(self, endpoint: str, **params) -> dict:
        query = urllib.parse.urlencode({"t": self.token, **params})
        url = f"{API_URL}/{endpoint}?{query}"

        for attempt in range(RATE_LIMIT_RETRIES + 1):
            last_attempt = attempt == RATE_LIMIT_RETRIES
            try:
                status, body = self._send(url)
            except OSError:
                if last_attempt:
                    raise
            else:
                if status != 429 or last_attempt:
                    break
            wait = RATE_LIMIT_BACKOFF_SECONDS * 2 ** attempt
            logger.info("PriceCharting is throttling requests; retrying in %.0fs",
                        wait)
            self.sleep(wait)

        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {}

        if status != 200 or payload.get("status") != "success":
            message = payload.get("error-message")
            if message is None:
                # Cloudflare returns HTML pages rather than JSON errors.
                message = (
                    "rate limited" if status == 429
                    else body[:200].decode(errors="replace")
                )
            raise PriceChartingError(status, message)
        return payload

    def _send(self, url: str) -> tuple[int, bytes]:
        if self._last_call_at is not None:
            elapsed = self.clock() - self._last_call_at
            wait = self.min_seconds_between_calls - elapsed
            if wait > 0:
                self.sleep(wait)
        self._last_call_at = self.clock()
        return self.transport(urllib.request.Request(url))
