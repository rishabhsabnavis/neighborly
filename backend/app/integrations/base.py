"""Seams the live Photon, ElevenLabs, and Nemotron modules plug into.

CallContext field names match ElevenLabsCaller: name, summary, reason, opening.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.models import CallReason, ClaimDraft, Triage


@dataclass
class InboundMessage:
    id: str
    phone: str
    text: str
    ts: str


@dataclass
class CallContext:
    name: str
    summary: str = ""
    reason: CallReason = "requested"
    opening: str | None = None


@dataclass
class CallTurn:
    role: Literal["agent", "user"]
    text: str
    t: float | None = None


@dataclass
class CallResult:
    call_id: str
    status: Literal["calling", "done", "failed"]
    conversation_id: str | None = None
    duration_s: int | None = None
    transcript: list[CallTurn] = field(default_factory=list)
    summary: str | None = None
    answered: bool | None = None
    voicemail: bool = False
    error: str | None = None


class Messenger(Protocol):
    async def send(self, phone: str, text: str) -> str: ...

    async def poll_inbound(self) -> list[InboundMessage]: ...


class Caller(Protocol):
    async def place_call(self, phone: str, context: CallContext) -> str: ...

    async def get_call(self, call_id: str) -> CallResult: ...


class Brain(Protocol):
    async def triage(self, case: object) -> Triage: ...

    async def follow_up(self, case: object) -> str | None: ...

    async def draft_claim(self, case: object) -> ClaimDraft: ...
