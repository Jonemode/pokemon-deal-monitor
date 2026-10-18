import unittest
from datetime import datetime, timedelta, timezone

from pokemon_deal_monitor.monitor import PollResult
from pokemon_deal_monitor.status import CommandListener, MonitorStatus, format_status


START = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def message(update_id, text, chat_id=42, sent_at=START + timedelta(minutes=1)):
    return {"update_id": update_id, "message": {
        "chat": {"id": chat_id},
        "date": int(sent_at.timestamp()),
        "text": text,
    }}


class FakeTelegram:

    def __init__(self, *batches):
        self.batches = list(batches)
        self.offsets = []
        self.sent = []

    def updates(self, offset=None, timeout=0):
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []

    def send_message(self, chat_id, text, silent=False):
        self.sent.append((chat_id, text))


class TestFormatStatus(unittest.TestCase):

    def test_after_polls(self):
        status = MonitorStatus(started_at=START)
        status.record(PollResult(items_seen=345, errors=["x"]), auctions=False,
                      now=START + timedelta(days=3, hours=4, minutes=58))
        status.record(PollResult(), auctions=True,
                      now=START + timedelta(days=3, hours=4, minutes=53))
        self.assertEqual(
            format_status(status, 2, START + timedelta(days=3, hours=5)),
            "✅ <b>Monitor running</b> for 3d 5h\n"
            "Last poll 2m ago: 345 listings, 1 error\n"
            "Last auction search 7m ago\n"
            "Alerts in the last 24h: 2",
        )

    def test_before_first_poll(self):
        text = format_status(MonitorStatus(started_at=START), 0, START)
        self.assertIn("running</b> for under 1m\nFirst poll in progress", text)

    def test_failed_poll(self):
        status = MonitorStatus(started_at=START)
        status.record_failure(START + timedelta(minutes=1))
        text = format_status(status, 0, START + timedelta(hours=1, minutes=1))
        self.assertIn("⚠️ Last poll failed 1h 0m ago", text)


class TestCommandListener(unittest.TestCase):

    def listener(self, telegram):
        return CommandListener(telegram, "42", lambda: "status text",
                               started_at=START)

    def test_answers_status(self):
        telegram = FakeTelegram([message(7, "/status")])
        self.listener(telegram).check()
        self.assertEqual(telegram.sent, [("42", "status text")])

    def test_addressed_command(self):
        telegram = FakeTelegram([message(7, "/status@jonemode_bot")])
        self.listener(telegram).check()
        self.assertEqual(len(telegram.sent), 1)

    def test_ignores_other_chats_text_and_old_messages(self):
        telegram = FakeTelegram([
            message(7, "/status", chat_id=99),
            message(8, "hello"),
            message(9, "/status", sent_at=START - timedelta(minutes=1)),
            {"update_id": 10, "edited_message": {}},
        ])
        self.listener(telegram).check()
        self.assertEqual(telegram.sent, [])

    def test_confirms_handled_updates(self):
        telegram = FakeTelegram([message(7, "hi"), message(8, "hi")], [])
        listener = self.listener(telegram)
        listener.check()
        listener.check()
        self.assertEqual(telegram.offsets, [None, 9])


if __name__ == "__main__":
    unittest.main()
