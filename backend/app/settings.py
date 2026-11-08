from __future__ import annotations

import os


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def assume_opted_in() -> bool:
    return env("DEMO_ASSUME_OPTED_IN") == "1"


def no_reply_seconds() -> float:
    raw = env("NO_REPLY_SECONDS", "60") or "60"
    try:
        return float(raw)
    except ValueError:
        return 60.0


def agent_tick_seconds() -> float:
    raw = env("AGENT_TICK_SECONDS", "15") or "15"
    try:
        return float(raw)
    except ValueError:
        return 15.0


def demo_phone(which: str) -> str:
    return env(which)
