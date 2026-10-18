import tempfile
import unittest
from pathlib import Path

from pokemon_deal_monitor.config import (
    load_ebay_config,
    load_telegram_config,
    read_env_file,
)


class TestConfig(unittest.TestCase):

    def write_env(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_read_env_file(self):
        path = self.write_env(
            "# eBay keyset\n"
            "\n"
            "EBAY_APP_ID = app-123\n"
            "EBAY_CERT_ID='cert=456'\n"
        )
        self.assertEqual(
            read_env_file(path),
            {"EBAY_APP_ID": "app-123", "EBAY_CERT_ID": "cert=456"},
        )

    def test_missing_env_file(self):
        self.assertEqual(read_env_file(Path("/nonexistent/.env")), {})

    def test_malformed_env_file(self):
        path = self.write_env("EBAY_APP_ID\n")
        with self.assertRaises(ValueError):
            read_env_file(path)

    def test_load_from_env_file(self):
        path = self.write_env("EBAY_APP_ID=app\nEBAY_CERT_ID=cert\n")
        config = load_ebay_config(env_path=path, environ={})

        self.assertEqual(config.app_id, "app")
        self.assertEqual(config.cert_id, "cert")
        self.assertEqual(config.environment, "production")

    def test_environment_overrides_env_file(self):
        path = self.write_env("EBAY_APP_ID=file-app\nEBAY_CERT_ID=cert\n")
        config = load_ebay_config(
            env_path=path, environ={"EBAY_APP_ID": "env-app"}
        )
        self.assertEqual(config.app_id, "env-app")

    def test_missing_credentials(self):
        path = self.write_env("EBAY_APP_ID=app\n")
        with self.assertRaises(ValueError) as context:
            load_ebay_config(env_path=path, environ={})
        self.assertIn("EBAY_CERT_ID", str(context.exception))

    def test_invalid_environment(self):
        path = self.write_env(
            "EBAY_APP_ID=app\nEBAY_CERT_ID=cert\nEBAY_ENVIRONMENT=staging\n"
        )
        with self.assertRaises(ValueError):
            load_ebay_config(env_path=path, environ={})


    def test_telegram_config(self):
        path = self.write_env("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=42\n")
        config = load_telegram_config(env_path=path, environ={})
        self.assertEqual((config.bot_token, config.chat_id), ("tok", "42"))

    def test_telegram_without_chat_id(self):
        path = self.write_env("TELEGRAM_BOT_TOKEN=tok\n")
        self.assertIsNone(load_telegram_config(env_path=path, environ={}).chat_id)

    def test_telegram_not_configured(self):
        path = self.write_env("TELEGRAM_BOT_TOKEN=\n")
        self.assertIsNone(load_telegram_config(env_path=path, environ={}))


if __name__ == "__main__":
    unittest.main()
