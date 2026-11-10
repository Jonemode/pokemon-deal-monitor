"""Answers eBay's Marketplace Account Deletion notifications.

eBay requires every app to subscribe to them. The monitor stores no eBay
user data, only listings (titles, prices, links), so there is never
anything to delete: a notification is only acknowledged.

eBay first checks the endpoint with a GET carrying a challenge code, which
must be answered with SHA-256(challenge code + verification token +
endpoint URL). Notifications then arrive as POSTs. Runs behind Caddy,
which terminates HTTPS; see deploy/README.md.
"""

import hashlib
import json
import logging
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_settings


logger = logging.getLogger(__name__)

PATH = "/ebay/account-deletion"
# Notifications are a few hundred bytes; anything far larger isn't one.
MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class DeletionConfig:
    # Made up when subscribing: 32 to 80 letters, digits, _ or -.
    verification_token: str
    # The public URL entered on eBay's developer portal, exactly.
    endpoint_url: str


def load_deletion_config(
    env_path: Path | None = None, environ: dict[str, str] | None = None
) -> DeletionConfig:
    values = load_settings(env_path, environ)
    missing = [key for key in ("EBAY_DELETION_TOKEN", "EBAY_DELETION_ENDPOINT")
               if not values.get(key)]
    if missing:
        raise ValueError(f"Missing {', '.join(missing)}")
    return DeletionConfig(values["EBAY_DELETION_TOKEN"],
                          values["EBAY_DELETION_ENDPOINT"])


def challenge_response(challenge_code: str, config: DeletionConfig) -> str:
    return hashlib.sha256(
        (challenge_code + config.verification_token + config.endpoint_url).encode()
    ).hexdigest()


def notification_id(body: bytes) -> str | None:
    """The notification's ID, for the log. Its user details aren't logged."""
    try:
        return json.loads(body)["notification"]["notificationId"]
    except (ValueError, KeyError, TypeError):
        return None


def build_handler(config: DeletionConfig) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            codes = urllib.parse.parse_qs(url.query).get("challenge_code")
            if url.path != PATH or not codes:
                self.send_error(404)
                return
            body = json.dumps(
                {"challengeResponse": challenge_response(codes[0], config)}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            logger.info("Answered eBay's endpoint challenge")

        def do_POST(self) -> None:
            if urllib.parse.urlsplit(self.path).path != PATH:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY_BYTES:
                self.send_error(413)
                return
            body = self.rfile.read(length)
            # Nothing to delete: no eBay user data is stored.
            logger.info("Account deletion notification %s acknowledged",
                        notification_id(body))
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args) -> None:
            # The default logs every request to stderr; requests are logged
            # above instead.
            pass

    return Handler


def serve(config: DeletionConfig, host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), build_handler(config))
    logger.info("Listening for eBay account deletion notifications on %s:%d",
                host, port)
    server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    serve(load_deletion_config())


if __name__ == "__main__":
    main()
