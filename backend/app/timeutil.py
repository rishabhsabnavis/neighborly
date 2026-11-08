from __future__ import annotations

from datetime import UTC, datetime, timedelta


def now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return to_iso(now())


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def plus_seconds(seconds: float) -> str:
    return to_iso(now() + timedelta(seconds=seconds))
