import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from pokemon_deal_monitor.account_deletion import (
    DeletionConfig,
    build_handler,
    challenge_response,
    load_deletion_config,
)


CONFIG = DeletionConfig(
    verification_token="t" * 40,
    endpoint_url="https://167-71-16-111.sslip.io/ebay/account-deletion",
)
NOTIFICATION = {
    "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
    "notification": {
        "notificationId": "49feeaeb-4982-42d9-a377-9645b8479411_33f7e043",
        "data": {"username": "someone", "userId": "ma8vp1jySJC",
                 "eiasToken": "nY+sHZ2PrBmdj6wVnY+sEZ2PrA2dj6wJnY+gAZGEpwmdj6x9nY+seQ=="},
    },
}


class TestChallengeResponse(unittest.TestCase):

    def test_hashes_code_token_and_endpoint_in_order(self):
        expected = hashlib.sha256(
            ("abc" + CONFIG.verification_token + CONFIG.endpoint_url).encode()
        ).hexdigest()
        self.assertEqual(challenge_response("abc", CONFIG), expected)

    def test_config_from_settings(self):
        config = load_deletion_config(env_path=Path("missing.env"), environ={
            "EBAY_DELETION_TOKEN": CONFIG.verification_token,
            "EBAY_DELETION_ENDPOINT": CONFIG.endpoint_url,
        })
        self.assertEqual(config, CONFIG)
        with self.assertRaisesRegex(ValueError, "EBAY_DELETION_TOKEN"):
            load_deletion_config(env_path=Path("missing.env"),
                                 environ={"EBAY_DELETION_ENDPOINT": "x"})


class TestServer(unittest.TestCase):

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(CONFIG))
        threading.Thread(target=self.server.serve_forever, args=(0.05,),
                         daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path, body=None):
        request = urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_answers_the_challenge(self):
        status, body = self.request("/ebay/account-deletion?challenge_code=abc123")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body),
                         {"challengeResponse": challenge_response("abc123", CONFIG)})

    def test_acknowledges_notifications(self):
        with self.assertLogs("pokemon_deal_monitor.account_deletion") as logs:
            status, body = self.request("/ebay/account-deletion",
                                        json.dumps(NOTIFICATION).encode())
        self.assertEqual((status, body), (204, b""))
        log = "\n".join(logs.output)
        self.assertIn("49feeaeb-4982-42d9-a377-9645b8479411_33f7e043", log)
        # The user's details are never logged.
        self.assertNotIn("someone", log)
        self.assertNotIn("ma8vp1jySJC", log)

    def test_other_requests_are_not_found(self):
        self.assertEqual(self.request("/ebay/account-deletion")[0], 404)
        self.assertEqual(self.request("/?challenge_code=abc")[0], 404)
        self.assertEqual(self.request("/other", b"{}")[0], 404)
