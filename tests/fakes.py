import json
import urllib.parse

from pokemon_deal_monitor.config import EbayConfig


CONFIG = EbayConfig(app_id="test-app", cert_id="test-cert")


def token_response(expires_in=7200):
    return 200, json.dumps({
        "access_token": "token-1",
        "expires_in": expires_in,
        "token_type": "Application Access Token",
    }).encode()


def item_summary(item_id, title, price="100.00", shipping="5.00",
                 condition="Ungraded"):
    summary = {
        "itemId": item_id,
        "title": title,
        "itemWebUrl": f"https://www.ebay.com/itm/{item_id}",
        "price": {"value": price, "currency": "USD"},
        "condition": condition,
        "image": {"imageUrl": f"https://i.ebayimg.com/{item_id}.jpg"},
        "itemCreationDate": "2026-10-17T12:00:00.000Z",
    }
    if shipping is not None:
        summary["shippingOptions"] = [{
            "shippingCostType": "FIXED",
            "shippingCost": {"value": shipping, "currency": "USD"},
        }]
    return summary


def item_response(card_condition="Near mint or better", language="English"):
    item = {"conditionDescriptors": [], "localizedAspects": []}
    if card_condition is not None:
        item["conditionDescriptors"].append({
            "name": "Card Condition",
            "values": [{"content": card_condition}],
        })
    if language is not None:
        item["localizedAspects"].append(
            {"type": "STRING", "name": "Language", "value": language}
        )
    return 200, json.dumps(item).encode()


def search_response(*summaries):
    return 200, json.dumps({"itemSummaries": list(summaries)}).encode()


class FakeTransport:
    """Serves the token endpoint, canned search results by query, and
    listing details by item ID (NM and English unless given)."""

    def __init__(self, searches=None, token=None, items=None):
        self.searches = searches or {}
        self.token = token or token_response()
        self.items = items or {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if request.full_url.endswith("/oauth2/token"):
            return self.token
        if "/buy/browse/v1/item/" in request.full_url:
            item_id = urllib.parse.unquote(request.full_url.rsplit("/", 1)[1])
            return self.items.get(item_id, item_response())

        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(request.full_url).query
        )["q"][0]
        response = self.searches.get(query, search_response())
        if isinstance(response, list):
            return response.pop(0)
        return response

    @property
    def token_requests(self):
        return [r for r in self.requests if r.full_url.endswith("/oauth2/token")]

    @property
    def item_requests(self):
        return [r for r in self.requests if "/buy/browse/v1/item/" in r.full_url]

    @property
    def search_requests(self):
        return [r for r in self.requests if "/item_summary/search" in r.full_url]
