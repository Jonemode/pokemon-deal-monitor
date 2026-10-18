import argparse
import logging
import sys
import time
from collections.abc import Callable

from .alerts import format_dollars, sample_alert, send_alerts
from .config import (
    TelegramConfig,
    load_ebay_config,
    load_pricecharting_token,
    load_telegram_config,
)
from .ebay import EbayClient
from .monitor import DEFAULT_POLL_INTERVAL_SECONDS, PollResult, poll_once
from .pricecharting import PriceChartingClient, load_product_ids
from .storage import Storage, utc_now
from .telegram import TelegramClient, TelegramError
from .valuation import Pricer


logger = logging.getLogger("pokemon_deal_monitor")


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


def telegram_config() -> TelegramConfig | None:
    try:
        return load_telegram_config()
    except ValueError as error:
        sys.exit(f"{error}.")


def is_quiet(config: TelegramConfig) -> bool:
    return config.quiet_hours is not None and config.quiet_hours.contains(utc_now())


def telegram_client() -> tuple[TelegramClient, TelegramConfig]:
    config = telegram_config()
    if config is None:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env first.")
    return TelegramClient(config.bot_token), config


def show_chat_ids() -> None:
    client, _ = telegram_client()
    chats = client.chats()
    if not chats:
        sys.exit("No messages found. Send your bot a message in Telegram, "
                 "then run this again.")
    for chat in chats:
        print(f"TELEGRAM_CHAT_ID={chat['id']}  ({chat['name']})")
    print("Add the line for your chat to .env.")


def send_test_alert() -> None:
    client, config = telegram_client()
    if config.chat_id is None:
        sys.exit("Set TELEGRAM_CHAT_ID in .env first; run make telegram-chat-id.")
    silent = is_quiet(config)
    try:
        client.send_message(config.chat_id, sample_alert(), silent=silent)
    except TelegramError as error:
        sys.exit(str(error))
    print("Test alert sent silently (quiet hours)." if silent else "Test alert sent.")


def build_notifier() -> Callable[[str], None] | None:
    config = telegram_config()
    if config is None or config.chat_id is None:
        logger.warning("Telegram not configured; deals are only logged")
        return None
    client = TelegramClient(config.bot_token)
    return lambda text: client.send_message(
        config.chat_id, text, silent=is_quiet(config)
    )


def poll_and_alert(client, storage, pricer, notify) -> None:
    poll = poll_once(client, storage, pricer=pricer)
    report(poll)
    if notify is not None:
        sent = send_alerts(poll, storage, notify)
        if sent:
            logger.info("Sent %d alerts", sent)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pokemon_deal_monitor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("poll", help="Search eBay once and report candidates")
    subcommands.add_parser("telegram-chat-id",
                           help="List chats that have messaged the bot")
    subcommands.add_parser("test-alert", help="Send a sample Telegram alert")
    run = subcommands.add_parser("run", help="Poll eBay continuously")
    run.add_argument(
        "--interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Seconds between polls (default: %(default)s)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if args.command == "telegram-chat-id":
        return show_chat_ids()
    if args.command == "test-alert":
        return send_test_alert()

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

    notify = build_notifier()

    with Storage() as storage:
        pricer = Pricer(
            storage,
            PriceChartingClient(token) if token else None,
            product_ids,
        )
        if args.command == "poll":
            poll_and_alert(client, storage, pricer, notify)
            return

        while True:
            started = time.monotonic()
            try:
                poll_and_alert(client, storage, pricer, notify)
            except Exception:
                # Keep the monitor alive through transient network failures.
                logger.exception("Poll failed")
            time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
