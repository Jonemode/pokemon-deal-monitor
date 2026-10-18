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
    """
    ALTER TABLE listings ADD COLUMN condition TEXT;
    ALTER TABLE listings ADD COLUMN shipping_known INTEGER NOT NULL DEFAULT 1;
    """,
    """
    CREATE TABLE prices (
        card_identifier TEXT NOT NULL,
        source TEXT NOT NULL,
        raw_cents INTEGER,
        grade_5_cents INTEGER,
        grade_7_cents INTEGER,
        sales_volume INTEGER,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (card_identifier, source)
    );
    """,
    """
    ALTER TABLE listings ADD COLUMN card_condition TEXT;
    ALTER TABLE listings ADD COLUMN language TEXT;
    ALTER TABLE listings ADD COLUMN details_fetched_at TEXT;
    """,
    # Details from other eBay sites were stored blank before their localized
    # names were recognised, so fetch those again.
    """
    UPDATE listings SET details_fetched_at = NULL
    WHERE card_condition IS NULL AND language IS NULL;
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
    # eBay's condition label, e.g. "Ungraded" or "Graded".
    condition: str | None = None
    # False when eBay gave no shipping cost, so shipping_cents is a guess.
    shipping_known: bool = True

    @property
    def total_cents(self) -> int:
        return self.price_cents + self.shipping_cents


@dataclass(frozen=True)
class StoredListing(Listing):
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    ended_at: datetime | None = None
    # From the full listing; see save_details. Both are None until
    # details_fetched_at is set, and either may be None afterwards when the
    # seller left it blank.
    card_condition: str | None = None
    language: str | None = None
    details_fetched_at: datetime | None = None


@dataclass(frozen=True)
class PriceRecord:
    """One source's price for a catalog card. All prices are optional because
    a source may know a card without having a value for every grade."""
    card_identifier: str
    source: str
    fetched_at: datetime
    raw_cents: int | None = None
    grade_5_cents: int | None = None
    grade_7_cents: int | None = None
    sales_volume: int | None = None


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
        for name in ("first_seen_at", "last_seen_at", "ended_at",
                     "details_fetched_at"):
            fields[name] = parse_time(fields[name])
        fields["shipping_known"] = bool(fields["shipping_known"])
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
                        condition, shipping_known, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing.item_id, listing.title, listing.url,
                        listing.price_cents, listing.shipping_cents,
                        listing.currency, listing.card_identifier,
                        listing.match_confidence, listing.condition,
                        listing.shipping_known, seen_at, seen_at,
                    ),
                )
                return UpsertResult.NEW

            self.connection.execute(
                """
                UPDATE listings SET
                    title = ?, url = ?, price_cents = ?, shipping_cents = ?,
                    currency = ?, card_identifier = ?, match_confidence = ?,
                    condition = ?, shipping_known = ?, last_seen_at = ?,
                    ended_at = NULL
                WHERE item_id = ?
                """,
                (
                    listing.title, listing.url, listing.price_cents,
                    listing.shipping_cents, listing.currency,
                    listing.card_identifier, listing.match_confidence,
                    listing.condition, listing.shipping_known, seen_at,
                    listing.item_id,
                ),
            )

        if existing.total_cents != listing.total_cents:
            return UpsertResult.PRICE_CHANGED
        return UpsertResult.UNCHANGED

    def save_details(
        self,
        item_id: str,
        card_condition: str | None,
        language: str | None,
        now: datetime | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE listings SET
                    card_condition = ?, language = ?, details_fetched_at = ?
                WHERE item_id = ?
                """,
                (card_condition, language, format_time(now or utc_now()), item_id),
            )

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

    def count_alerts_since(self, since: datetime) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM alerts WHERE sent_at >= ?", (format_time(since),)
        ).fetchone()
        return row[0]

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

    def save_price(self, record: PriceRecord) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO prices (
                    card_identifier, source, raw_cents, grade_5_cents,
                    grade_7_cents, sales_volume, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.card_identifier, record.source, record.raw_cents,
                    record.grade_5_cents, record.grade_7_cents,
                    record.sales_volume, format_time(record.fetched_at),
                ),
            )

    def get_prices(self, card_identifier: str) -> dict[str, PriceRecord]:
        """Return the cached price from each source for a card."""
        rows = self.connection.execute(
            "SELECT * FROM prices WHERE card_identifier = ?", (card_identifier,)
        ).fetchall()
        records = {}
        for row in rows:
            fields = dict(row)
            fields["fetched_at"] = parse_time(fields["fetched_at"])
            records[row["source"]] = PriceRecord(**fields)
        return records

    def latest_price_fetch(self, source: str) -> datetime | None:
        row = self.connection.execute(
            "SELECT MAX(fetched_at) FROM prices WHERE source = ?", (source,)
        ).fetchone()
        return parse_time(row[0])
