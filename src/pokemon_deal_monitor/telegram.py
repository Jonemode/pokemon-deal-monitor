"""Telegram Bot API client for sending deal alerts."""

import json
import urllib.request

from .ebay import Transport, urllib_transport


API_URL = "https://api.telegram.org"


class TelegramError(Exception):

    def __init__(self, status: int, description: str):
        super().__init__(f"Telegram API returned HTTP {status}: {description}")
        self.status = status


class TelegramClient:

    def __init__(self, bot_token: str, transport: Transport = urllib_transport):
        self.bot_token = bot_token
        self.transport = transport

    def send_message(self, chat_id: str, text: str, silent: bool = False) -> None:
        """Send an HTML-formatted message, without sound if silent."""
        self._call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": silent,
        })

    def chats(self) -> list[dict]:
        """Return the chats that have recently messaged the bot.

        Each chat is {"id", "name"}. Telegram keeps updates for 24 hours.
        """
        chats = {}
        for update in self._call("getUpdates", {}):
            message = update.get("message") or update.get("my_chat_member") or {}
            chat = message.get("chat")
            if chat:
                name = chat.get("username") or chat.get("title") or chat.get("first_name")
                chats[chat["id"]] = {"id": chat["id"], "name": name}
        return list(chats.values())

    def _call(self, method: str, params: dict):
        # The token is part of the URL, so errors must never include it.
        request = urllib.request.Request(
            f"{API_URL}/bot{self.bot_token}/{method}",
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status, body = self.transport(request)

        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {}

        if status != 200 or not payload.get("ok"):
            raise TelegramError(
                status, payload.get("description", "unexpected response")
            )
        return payload["result"]
