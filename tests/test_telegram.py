import json
import unittest

from pokemon_deal_monitor.telegram import TelegramClient, TelegramError


class FakeTransport:

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode()


class TestTelegramClient(unittest.TestCase):

    def test_send_message(self):
        transport = FakeTransport((200, {"ok": True, "result": {}}))
        TelegramClient("123:abc", transport=transport).send_message("42", "<b>hi</b>")

        (request,) = transport.requests
        self.assertEqual(request.full_url,
                         "https://api.telegram.org/bot123:abc/sendMessage")
        body = json.loads(request.data)
        self.assertEqual(body["chat_id"], "42")
        self.assertEqual(body["text"], "<b>hi</b>")
        self.assertEqual(body["parse_mode"], "HTML")

    def test_error_does_not_reveal_token(self):
        transport = FakeTransport(
            (400, {"ok": False, "description": "Bad Request: chat not found"})
        )
        with self.assertRaises(TelegramError) as context:
            TelegramClient("123:secret", transport=transport).send_message("1", "x")

        self.assertEqual(context.exception.status, 400)
        self.assertIn("chat not found", str(context.exception))
        self.assertNotIn("secret", str(context.exception))

    def test_chats_from_updates(self):
        transport = FakeTransport((200, {"ok": True, "result": [
            {"message": {"chat": {"id": 42, "username": "jonemode"}}},
            {"message": {"chat": {"id": 42, "username": "jonemode"}}},
            {"message": {"chat": {"id": -100, "title": "Deals group"}}},
            {"edited_message": {}},
        ]}))
        chats = TelegramClient("t", transport=transport).chats()

        self.assertEqual(chats, [
            {"id": 42, "name": "jonemode"},
            {"id": -100, "name": "Deals group"},
        ])


if __name__ == "__main__":
    unittest.main()
