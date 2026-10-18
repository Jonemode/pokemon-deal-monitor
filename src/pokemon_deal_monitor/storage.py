import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .catalog import PROJECT_ROOT


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "monitor.db"
DB_PATH_ENV_VAR = "POKEMON_MONITOR_DB"

# A listing that was already alerted on is alerted again only when its
# total price drops at least this far below the last alerted total.
REALERT_PRICE_DROP = 0.10

# Each entry upgrades the schema by one version. Never edit an entry once it
# has shipped; append a new one instead.
MIGRATIONS = [
    """
    CREATE TABLE listings (
        item_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        shipping_cents INTEGER NOT NULL,
        currency TEXT NOT NULL,
        card_identifier TEXT,
        match_confidence REAL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        ended_at TEXT
    );

    CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL REFERENCES listings (item_id),
        total_cents INTEGER NOT NULL,
        sent_at TEXT NOT NULL
    );

    CREATE INDEX alerts_item_id ON alerts (item_id);
    """,
]


@dataclass(frozen=True)
class Listing:
    item_id: str
    title: str
    url: str
    price_cents: int
    shipping_cents: int
    currency: str = "USD"
    card_identifier: str | None = None
    match_confidence: float | None = None

    @property
    def total_cents(self) -> int:
        return self.price_cents + self.shipping_cents


@dataclass(frozen=True)
class StoredListing(Listing):
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    ended_at: datetime | None = None


class UpsertResult(str, Enum):
    NEW = "new"
    PRICE_CHANGED = "price_changed"
    UNCHANGED = "unchanged"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> Path:
    override = os.environ.get(DB_PATH_ENV_VAR)
    return Path(override) if override else DEFAULT_DB_PATH


def format_time(value: datetime) -> str:
    # Stored as fixed-width UTC text so timestamps sort and compare correctly.
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class Storage:
    """SQLite store for discovered listings and the alerts sent for them."""

    def __init__(self, path: Path | str | None = None):
        db_path = path if path is not None else default_db_path()
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self) -> None:
        self.connection.close()

    @property
    def schema_version(self) -> int:
        return self.connection.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        for version in range(self.schema_version, len(MIGRATIONS)):
            self.connection.executescript(
                f"BEGIN; {MIGRATIONS[version]} "
                f"PRAGMA user_version = {version + 1}; COMMIT;"
            )

    def get_listing(self, item_id: str) -> StoredListing | None:
        row = self.connection.execute(
            "SELECT * FROM listings WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None

        fields = dict(row)
        for name in ("first_seen_at", "last_seen_at", "ended_at"):
            fields[name] = parse_time(fields[name])
        return StoredListing(**fields)

    def upsert_listing(
        self, listing: Listing, now: datetime | None = None
    ) -> UpsertResult:
        """Record a sighting of a listing and report what changed.

        A listing seen again after being marked ended is treated as live.
        """
        seen_at = format_time(now or utc_now())
        existing = self.get_listing(listing.item_id)

        with self.connection:
            if existing is None:
                self.connection.execute(
                    """
                    INSERT INTO listings (
                        item_id, title, url, price_cents, shipping_cents,
                        currency, card_identifier, match_confidence,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.item_id, listing.title, listing.url,
                        listing.price_cents, listing.shipping_cents,
                        listing.currency, listing.card_identifier,
                        listing.match_confidence, seen_at, seen_at,
                    ),
                )
                return UpsertResult.NEW

            self.connection.execute(
                """
                UPDATE listings SET
                    title = ?, url = ?, price_cents = ?, shipping_cents = ?,
                    currency = ?, card_identifier = ?, match_confidence = ?,
                    last_seen_at = ?, ended_at = NULL
                WHERE item_id = ?
                """,
                (
                    listing.title, listing.url, listing.price_cents,
                    listing.shipping_cents, listing.currency,
                    listing.card_identifier, listing.match_confidence,
                    seen_at, listing.item_id,
                ),
            )

        if existing.total_cents != listing.total_cents:
            return UpsertResult.PRICE_CHANGED
        return UpsertResult.UNCHANGED

    def should_alert(self, item_id: str) -> bool:
        """Return whether a live listing deserves an alert now.

        True for a listing never alerted on, or one whose total price has
        dropped by REALERT_PRICE_DROP since the last alert.
        """
        listing = self.get_listing(item_id)
        if listing is None or listing.ended_at is not None:
            return False

        row = self.connection.execute(
            """
            SELECT total_cents FROM alerts
            WHERE item_id = ? ORDER BY id DESC LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return True

        threshold = row["total_cents"] * (1 - REALERT_PRICE_DROP)
        return listing.total_cents <= threshold

    def record_alert(self, item_id: str, now: datetime | None = None) -> None:
        listing = self.get_listing(item_id)
        if listing is None:
            raise KeyError(f"Unknown listing: {item_id}")

        with self.connection:
            self.connection.execute(
                "INSERT INTO alerts (item_id, total_cents, sent_at) "
                "VALUES (?, ?, ?)",
                (item_id, listing.total_cents, format_time(now or utc_now())),
            )

    def mark_ended(
        self, not_seen_since: datetime, now: datetime | None = None
    ) -> int:
        """Mark live listings not seen since a cutoff as ended.

        Returns the number of listings marked.
        """
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE listings SET ended_at = ?
                WHERE ended_at IS NULL AND last_seen_at < ?
                """,
                (format_time(now or utc_now()), format_time(not_seen_since)),
            )
        return cursor.rowcount
