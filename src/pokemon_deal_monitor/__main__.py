import argparse
import logging
import time

from .config import load_ebay_config
from .ebay import EbayClient
from .monitor import DEFAULT_POLL_INTERVAL_SECONDS, PollResult, poll_once
from .storage import Storage


logger = logging.getLogger("pokemon_deal_monitor")


def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def report(poll: PollResult) -> None:
    logger.info(
        "Saw %d listings, %d candidates, %d errors",
        poll.items_seen, len(poll.candidates), len(poll.errors),
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
    with Storage() as storage:
        if args.command == "poll":
            report(poll_once(client, storage))
            return

        while True:
            started = time.monotonic()
            try:
                report(poll_once(client, storage))
            except Exception:
                # Keep the monitor alive through transient network failures.
                logger.exception("Poll failed")
            time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
