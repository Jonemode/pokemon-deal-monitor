import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import timedelta

from .alerts import (
    format_dollars,
    format_time_left,
    sample_alert,
    send_alerts,
    send_watch_alerts,
)
from .config import (
    TelegramConfig,
    load_ebay_config,
    load_pricecharting_token,
    load_telegram_config,
)
from .ebay import EbayClient
from .game import Game
from .games import GAMES
from .monitor import (
    AUCTION_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_SECONDS,
    PollResult,
    poll_once,
)
from .pricecharting import PriceChartingClient, load_product_ids
from .status import CommandListener, MonitorStatus, format_status
from .storage import Storage, utc_now
from .telegram import TelegramClient, TelegramError
from .valuation import Pricer
from .watch import poll_watches


logger = logging.getLogger("pokemon_deal_monitor")

# Between polls, Telegram is long-polled for commands this long at a time,
# within the transport's 30 second timeout.
COMMAND_WAIT_SECONDS = 20


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
    if deal.max_bid_cents is not None:
        summary += f", max bid {format_dollars(deal.max_bid_cents)}"
    if deal.offer_cents is not None:
        summary += f", offer {format_dollars(deal.offer_cents)}"
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
        if item.auction:
            logger.info("    auction, %s, %s bids",
                        format_time_left(item.ends_at, utc_now()), item.bid_count)
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


def build_listener(
    storage: Storage, status: MonitorStatus
) -> CommandListener | None:
    config = telegram_config()
    if config is None or config.chat_id is None:
        return None

    def status_text() -> str:
        now = utc_now()
        alerts = storage.count_alerts_since(now - timedelta(days=1))
        return format_status(status, alerts, now)

    return CommandListener(TelegramClient(config.bot_token), config.chat_id,
                           status_text, started_at=status.started_at)


def wait_until(deadline: float, listener: CommandListener | None) -> None:
    """Sleep until a time.monotonic() deadline, answering Telegram commands
    meanwhile."""
    while (remaining := deadline - time.monotonic()) > 0:
        if listener is None or remaining < 1:
            time.sleep(remaining)
            continue
        try:
            listener.check(timeout=min(int(remaining), COMMAND_WAIT_SECONDS))
        except Exception as error:
            # Commands are a convenience; never let them stop polling.
            logger.warning("Checking Telegram commands failed: %s", error)
            time.sleep(min(remaining, COMMAND_WAIT_SECONDS))


def build_pricer(storage: Storage, game: Game, token: str | None) -> Pricer:
    product_ids = (
        load_product_ids(game.pricecharting_ids_path)
        if game.pricecharting_ids_path else {}
    )
    if token is not None and game.pricecharting_ids_path and not product_ids:
        logger.warning("No PriceCharting product IDs for %s; "
                       "run make pricecharting-ids", game.name)
    return Pricer(
        storage, game,
        PriceChartingClient(token) if token else None,
        product_ids,
    )


def poll_and_alert(client, storage, pricer, notify, auctions=False,
                   quiet_hours=None, queries=None) -> PollResult:
    poll = poll_once(client, storage, pricer.game, queries=queries,
                     pricer=pricer, auctions=auctions, quiet_hours=quiet_hours)
    report(poll)
    if notify is not None:
        timezone = quiet_hours.timezone if quiet_hours else None
        sent = send_alerts(poll, storage, notify, timezone=timezone)
        if sent:
            logger.info("Sent %d alerts", sent)
    return poll


def watch_and_alert(client, storage, notify) -> None:
    result = poll_watches(client, storage)
    for hit in result.hits:
        logger.info("[watch] %s | %s | %s", hit.watch.name,
                    format_dollars(hit.item.price_cents), hit.item.url)
        logger.info("    %s", hit.item.title)
    if notify is not None:
        sent = send_watch_alerts(result.hits, storage, notify)
        if sent:
            logger.info("Sent %d watch alerts", sent)


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

    notify = build_notifier()
    telegram = telegram_config()
    # Auctions ending during quiet hours are searched for in the evening.
    quiet_hours = telegram.quiet_hours if telegram else None

    with Storage() as storage:
        pricers = [build_pricer(storage, game, token) for game in GAMES]
        if args.command == "poll":
            for pricer in pricers:
                poll_and_alert(client, storage, pricer, notify)
                poll_and_alert(client, storage, pricer, notify, auctions=True,
                               quiet_hours=quiet_hours)
            watch_and_alert(client, storage, notify)
            return

        # Auctions are searched on every sixth poll at the default interval,
        # with a second's leeway in case a sleep wakes slightly early.
        status = MonitorStatus(started_at=utc_now())
        listener = build_listener(storage, status)
        last_auction_poll = None
        # When each game's Buy It Now searches last ran, by game and search.
        last_searched = {pricer.game.key: {} for pricer in pricers}
        while True:
            started = time.monotonic()
            auctions_due = (
                last_auction_poll is None
                or started - last_auction_poll
                >= AUCTION_POLL_INTERVAL.total_seconds() - 1
            )
            try:
                for pricer in pricers:
                    searched = last_searched[pricer.game.key]
                    due = pricer.game.searches_due(searched, started,
                                                   args.interval)
                    if not due:
                        continue
                    poll = poll_and_alert(client, storage, pricer, notify,
                                          queries=due)
                    status.record(poll, auctions=False, now=utc_now())
                    searched.update(dict.fromkeys(due, started))
                if auctions_due:
                    last_auction_poll = started
                    for pricer in pricers:
                        poll = poll_and_alert(client, storage, pricer, notify,
                                              auctions=True,
                                              quiet_hours=quiet_hours)
                        status.record(poll, auctions=True, now=utc_now())
                    # Watched cards share the auctions' schedule, keeping
                    # eBay calls under the daily limit.
                    watch_and_alert(client, storage, notify)
            except Exception:
                # Keep the monitor alive through transient network failures.
                logger.exception("Poll failed")
                status.record_failure(utc_now())
            wait_until(started + args.interval, listener)


if __name__ == "__main__":
    main()
