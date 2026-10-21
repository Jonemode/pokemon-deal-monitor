import os
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .catalog import PROJECT_ROOT


DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class EbayConfig:
    app_id: str
    cert_id: str
    environment: str = "production"


@dataclass(frozen=True)
class QuietHours:
    """A daily window, which may span midnight, for silent alerts."""
    start: time
    end: time
    timezone: ZoneInfo

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.timezone).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def next_window(self, moment: datetime) -> tuple[datetime, datetime]:
        """Return the start and end of the next window starting after
        moment."""
        local = moment.astimezone(self.timezone)
        start = datetime.combine(local.date(), self.start, self.timezone)
        if start <= local:
            start += timedelta(days=1)
        end = datetime.combine(start.date(), self.end, self.timezone)
        if end <= start:
            end += timedelta(days=1)
        return start, end


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    # None until the chat ID has been looked up; see make telegram-chat-id.
    chat_id: str | None = None
    # Alerts in this window are delivered without a sound or vibration.
    quiet_hours: QuietHours | None = None


QUIET_HOURS_PATTERN = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def parse_quiet_hours(value: str, timezone: str | None) -> QuietHours:
    """Parse "22:00-07:00" in an IANA timezone such as America/Los_Angeles."""
    match = QUIET_HOURS_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("TELEGRAM_QUIET_HOURS must look like 22:00-07:00")
    if not timezone:
        raise ValueError("Set TIMEZONE, e.g. America/Los_Angeles, to use quiet hours")
    try:
        zone = ZoneInfo(timezone)
        start = time(int(match[1]), int(match[2]))
        end = time(int(match[3]), int(match[4]))
    except ZoneInfoNotFoundError:
        raise ValueError(f"Unknown TIMEZONE {timezone!r}") from None
    except ValueError:
        raise ValueError("TELEGRAM_QUIET_HOURS has an invalid time") from None
    return QuietHours(start=start, end=end, timezone=zone)


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, skipping blanks and # comments."""
    if not path.exists():
        return {}

    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")

        values[key.strip()] = value.strip().strip("'\"")

    return values


def load_settings(
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge .env values with the environment, which takes precedence."""
    values = read_env_file(env_path if env_path is not None else DEFAULT_ENV_PATH)
    values.update(os.environ if environ is None else environ)
    return values


def load_pricecharting_token(
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> str | None:
    """Return the PriceCharting API token, or None if it isn't configured."""
    return load_settings(env_path, environ).get("PRICECHARTING_TOKEN") or None


def load_telegram_config(
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> TelegramConfig | None:
    """Return Telegram settings, or None if no bot token is configured."""
    values = load_settings(env_path, environ)
    if not values.get("TELEGRAM_BOT_TOKEN"):
        return None
    quiet_hours = values.get("TELEGRAM_QUIET_HOURS")
    return TelegramConfig(
        bot_token=values["TELEGRAM_BOT_TOKEN"],
        chat_id=values.get("TELEGRAM_CHAT_ID") or None,
        quiet_hours=(
            parse_quiet_hours(quiet_hours, values.get("TIMEZONE"))
            if quiet_hours else None
        ),
    )


def load_ebay_config(
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> EbayConfig:
    """Load eBay credentials from the environment, falling back to .env.

    Real environment variables take precedence, so the VPS can set them
    directly without a .env file.
    """
    values = load_settings(env_path, environ)

    missing = [key for key in ("EBAY_APP_ID", "EBAY_CERT_ID") if not values.get(key)]
    if missing:
        raise ValueError(f"Missing eBay settings: {', '.join(missing)}")

    environment = values.get("EBAY_ENVIRONMENT", "production")
    if environment not in ("production", "sandbox"):
        raise ValueError("EBAY_ENVIRONMENT must be production or sandbox")

    return EbayConfig(
        app_id=values["EBAY_APP_ID"],
        cert_id=values["EBAY_CERT_ID"],
        environment=environment,
    )
