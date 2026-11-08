from __future__ import annotations

import time
import uuid

from app.integrations.base import (
    CallContext,
    CallResult,
    CallTurn,
    InboundMessage,
)
from app.timeutil import now_iso


class FakeMessenger:
    def __init__(self) -> None:
        self.outbound: list[tuple[str, str, str]] = []
        self._inbound: list[InboundMessage] = []

    async def send(self, phone: str, text: str) -> str:
        message_id = f"m_{len(self.outbound) + 1}"
        self.outbound.append((phone, text, message_id))
        return message_id

    async def poll_inbound(self) -> list[InboundMessage]:
        found = self._inbound
        self._inbound = []
        return found

    def push(self, phone: str, text: str) -> None:
        self._inbound.append(
            InboundMessage(
                id=f"in_{uuid.uuid4().hex[:8]}",
                phone=phone,
                text=text,
                ts=now_iso(),
            )
        )

    def reset(self) -> None:
        self.outbound.clear()
        self._inbound.clear()


class _Record:
    def __init__(
        self, call_id: str, phone: str, context: CallContext, started: float
    ) -> None:
        self.call_id = call_id
        self.phone = phone
        self.context = context
        self.started = started


class FakeCaller:
    """Finishes a call after delay_s with a transcript that fits the case."""

    def __init__(self) -> None:
        self._calls: dict[str, _Record] = {}
        self.delay_s = 10.0
        self.mode = "answered"
        self.fail_next = False

    async def place_call(self, phone: str, context: CallContext) -> str:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("network down")
        call_id = f"conv_{uuid.uuid4().hex[:10]}"
        self._calls[call_id] = _Record(call_id, phone, context, time.time())
        return call_id

    async def get_call(self, call_id: str) -> CallResult:
        record = self._calls.get(call_id)
        if record is None or time.time() - record.started < self.delay_s:
            return CallResult(call_id=call_id, status="calling", answered=None)
        if self.mode == "fail":
            return CallResult(
                call_id=call_id,
                status="failed",
                answered=False,
                error="network down",
            )
        if self.mode == "voicemail":
            return CallResult(
                call_id=call_id,
                status="done",
                answered=False,
                voicemail=True,
                duration_s=25,
                summary="Voicemail left.",
                transcript=[
                    CallTurn(
                        role="agent",
                        text="Hi, please call us back or text this number.",
                    ),
                ],
            )
        first = (record.context.name or "there").split()[0]
        summary = record.context.summary or "Spoke with the policyholder."
        return CallResult(
            call_id=call_id,
            status="done",
            answered=True,
            duration_s=74,
            summary=summary,
            transcript=[
                CallTurn(role="agent", text=f"Hi {first}, this is Neighborly."),
                CallTurn(
                    role="user",
                    text="The water's coming in and we're stuck upstairs.",
                ),
            ],
        )

    def reset(self) -> None:
        self._calls.clear()
        self.delay_s = 10.0
        self.mode = "answered"
        self.fail_next = False
