import argparse
import logging
import time

from .config import load_ebay_config, load_pricecharting_token
from .ebay import EbayClient
from .monitor import DEFAULT_POLL_INTERVAL_SECONDS, PollResult, poll_once
from .pricecharting import PriceChartingClient, load_product_ids
from .storage import Storage
from .valuation import Pricer


logger = logging.getLogger("pokemon_deal_monitor")


def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def describe_deal(candidate) -> str:
    deal = candidate.deal
    if deal is None:
        return "no value"
    valuation = deal.valuation
    summary = (
        f"value {format_dollars(valuation.value_cents)} "
        f"({', '.join(f'{k} {format_dollars(v)}' for k, v in valuation.estimates.items())})"
        f", discount {deal.discount:.0%}"
    )
    if valuation.warnings:
        summary += f" [warning: {', '.join(valuation.warnings)}]"
    if deal.qualifies:
        return "DEAL " + summary
    return f"{summary}; not a deal: {', '.join(deal.reasons)}"


def report(poll: PollResult) -> None:
    deals = sum(1 for c in poll.candidates if c.deal and c.deal.qualifies)
    logger.info(
        "Saw %d listings, %d candidates, %d deals, %d errors",
        poll.items_seen, len(poll.candidates), deals, len(poll.errors),
    )
    for candidate in poll.candidates:
        item = candidate.item
        shipping = (
            format_dollars(item.shipping_cents)
            if item.shipping_cents is not None else "unknown"
        )
        logger.info(
            "[%s %.2f] %s | %s + %s shipping | %s",
            candidate.result.value,
            candidate.match.confidence,
            candidate.match.card.identifier,
            format_dollars(item.price_cents),
            shipping,
            item.url,
        )
        logger.info("    %s", item.title)
        logger.info("    %s", describe_deal(candidate))


def main() -> None:
    parser = argparse.ArgumentParser(prog="pokemon_deal_monitor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("poll", help="Search eBay once and report candidates")
    run = subcommands.add_parser("run", help="Poll eBay continuously")
    run.add_argument(
        "--interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Seconds between polls (default: %(default)s)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    try:
        config = load_ebay_config()
    except ValueError as error:
        parser.error(f"{error}. Copy .env.example to .env and fill it in.")

    client = EbayClient(config)
    token = load_pricecharting_token()
    if token is None:
        logger.warning("PRICECHARTING_TOKEN not set; values use TCGplayer only")
    product_ids = load_product_ids()
    if token is not None and not product_ids:
        logger.warning("No PriceCharting product IDs; run make pricecharting-ids")

    with Storage() as storage:
        pricer = Pricer(
            storage,
            PriceChartingClient(token) if token else None,
            product_ids,
        )
        if args.command == "poll":
            report(poll_once(client, storage, pricer=pricer))
            return

        while True:
            started = time.monotonic()
            try:
                report(poll_once(client, storage, pricer=pricer))
            except Exception:
                # Keep the monitor alive through transient network failures.
                logger.exception("Poll failed")
            time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
