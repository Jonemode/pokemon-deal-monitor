"""Answers /status in Telegram, so the monitor can be checked from a phone."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .monitor import PollResult
from .storage import utc_now
from .telegram import TelegramClient


logger = logging.getLogger(__name__)

STATUS_COMMAND = "/status"


@dataclass
class MonitorStatus:
    started_at: datetime
    last_poll_at: datetime | None = None
    last_poll_errors: int = 0
    last_poll_failed: bool = False
    last_auction_poll_at: datetime | None = None

    def record(self, poll: PollResult, auctions: bool, now: datetime) -> None:
        if auctions:
            self.last_auction_poll_at = now
            return
        self.last_poll_at = now
        self.last_poll_errors = len(poll.errors)
        self.last_poll_failed = False

    def record_failure(self, now: datetime) -> None:
        self.last_poll_at = now
        self.last_poll_failed = True


def format_duration(duration: timedelta) -> str:
    minutes = int(duration.total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m" if minutes else "under 1m"


def format_status(status: MonitorStatus, alerts_last_day: int, now: datetime) -> str:
    """Return a two-line status: uptime and the last poll, then the last
    auction search and recent alerts."""
    uptime = format_duration(now - status.started_at)
    if status.last_poll_at is None:
        first = f"✅ Running {uptime} · first poll in progress"
    else:
        ago = format_duration(now - status.last_poll_at)
        if status.last_poll_failed:
            first = f"⚠️ Running {uptime} · last poll failed {ago} ago"
        else:
            errors = status.last_poll_errors
            first = (f"✅ Running {uptime} · last poll {ago} ago, "
                     f"{errors} error{'' if errors == 1 else 's'}")

    alerts = f"{alerts_last_day} alert{'' if alerts_last_day == 1 else 's'} in 24h"
    if status.last_auction_poll_at is None:
        second = alerts
    else:
        ago = format_duration(now - status.last_auction_poll_at)
        second = f"Auctions {ago} ago · {alerts}"
    return f"{first}\n{second}"


class CommandListener:
    """Replies to /status from the alert chat. Messages from other chats,
    and ones sent before the monitor started, are ignored."""

    def __init__(
        self,
        client: TelegramClient,
        chat_id: str,
        status_text: Callable[[], str],
        started_at: datetime | None = None,
    ):
        self.client = client
        self.chat_id = str(chat_id)
        self.status_text = status_text
        self.started_at = started_at or utc_now()
        self.offset: int | None = None

    def check(self, timeout: int = 0) -> None:
        """Answer new commands, waiting up to timeout seconds for one."""
        for update in self.client.updates(self.offset, timeout):
            self.offset = update["update_id"] + 1
            message = update.get("message") or {}
            if str(message.get("chat", {}).get("id")) != self.chat_id:
                continue
            if message.get("date", 0) < self.started_at.timestamp():
                continue
            words = (message.get("text") or "").split()
            # In a group the command can be addressed as /status@botname.
            if words and words[0].split("@")[0].lower() == STATUS_COMMAND:
                logger.info("Answering %s", STATUS_COMMAND)
                self.client.send_message(self.chat_id, self.status_text())
