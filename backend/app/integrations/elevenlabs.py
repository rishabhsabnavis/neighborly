"""Live Caller: outbound voice calls, ElevenLabs agent -> Photon SIP -> phone.

Implements the Caller interface from docs/BACKEND_PROMPT.md:
    async place_call(phone, context) -> call_id
    async get_call(call_id) -> CallResult

Facts this relies on (verified with spikes/voice_outbound.py, docs/CONTEXT.md):
- POST /v1/convai/sip-trunk/outbound-call BLOCKS until the call is set up (it took >30s
  once). The core wraps integration calls in a 10s timeout, so place_call returns a local
  id immediately and runs the POST in a background task. get_call resolves it.
- If that POST times out anyway, the call usually still happened: recover the conversation
  as the agent's newest outbound conversation started after we dialed.
- `call_successful` says "success" even for voicemail. A call counts as answered only if no
  voicemail_detection tool fired and the person said something real.
- The agent takes dynamic variables first_name, case_opening, call_reason, case_summary
  (set up by `just voice-outbound --setup`).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import httpx

BASE_URL = "https://api.elevenlabs.io"
CallReason = Literal["requested", "no_reply", "emergency"]

REASON_TEXT: dict[str, str] = {
    "requested": "the policyholder asked us to call them",
    "no_reply": "the policyholder has not replied to our check-in text",
    "emergency": "EMERGENCY: the policyholder reported a life-safety emergency. Ask ONLY safety questions (who is hurt, exact location, medical needs such as oxygen or power, can they get out). No claim or coverage talk. Keep it short",
}
# Voicemail greetings and menus that the speech-to-text transcribes as "user" turns
_MACHINE_PHRASES = (
    "leave a message",
    "leave your message",
    "message for",
    "not available",
    "at the tone",
    "after the tone",
    "voicemail",
    "voice mailbox",
    "press one",
    "press pound",
    "to replay your message",
    "recording has reached",
    "your message has been sent",
)


@dataclass
class CallContext:
    """Structurally matches the core's CallContext (name, case summary, reason)."""

    name: str
    summary: str = ""
    reason: CallReason = "requested"
    opening: str | None = (
        None  # optional first-sentence override, e.g. "You texted us that..."
    )


@dataclass
class CallTurn:
    role: Literal["agent", "user"]
    text: str
    t: float | None = None  # seconds into the call


@dataclass
class CallResult:
    call_id: str
    status: Literal["calling", "done", "failed"]
    conversation_id: str | None = None
    duration_s: int | None = None
    transcript: list[CallTurn] = field(default_factory=list)
    summary: str | None = None
    answered: bool | None = None  # None while calling
    voicemail: bool = False
    error: str | None = None


@dataclass
class _Pending:
    phone: str
    started: float
    task: asyncio.Task
    conversation_id: str | None = None
    error: str | None = None


class ElevenLabsError(RuntimeError):
    pass


def first_name(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "there"


def build_dynamic_variables(ctx: CallContext) -> dict[str, str]:
    summary = (ctx.summary or "").strip() or "nothing yet"
    if ctx.opening:
        opening = ctx.opening
    elif ctx.reason == "no_reply":
        opening = "We sent you a text after Hurricane Isaias and wanted to make sure you're okay."
    elif ctx.reason == "emergency":
        opening = "If you're in danger, hang up and call 911 now."  # SPEC Emergency path step 4
    else:
        opening = "You asked us to give you a call."
    name = first_name(ctx.name)
    if ctx.reason == "emergency":
        # SPEC Emergency path step 4: the 911 line comes first.
        first = f"If you're in danger, hang up and call 911 now. {name}, this is State Farm. Is anyone hurt or trapped?"
    else:
        hi = f"Hi {name}," if name != "there" else "Hi,"
        first = f"{hi} this is State Farm's storm check-in line. {opening} Are you and everyone with you safe right now?"
    return {
        "first_message": first,
        "first_name": name,
        "case_opening": opening,
        "call_reason": REASON_TEXT.get(ctx.reason, ctx.reason),
        "case_summary": summary,
    }


def _is_machine(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _MACHINE_PHRASES)


def parse_conversation(call_id: str, d: dict) -> CallResult:
    """Map an ElevenLabs conversation into a CallResult (pure, unit-tested)."""
    raw_status = d.get("status")
    status: Literal["calling", "done", "failed"]
    if raw_status == "done":
        status = "done"
    elif raw_status == "failed":
        status = "failed"
    else:  # initiated, in-progress, processing
        status = "calling"

    turns: list[CallTurn] = []
    voicemail = False
    for t in d.get("transcript") or []:
        for tc in t.get("tool_calls") or []:
            if "voicemail" in str(tc.get("tool_name") or tc.get("name") or ""):
                voicemail = True
        msg = (t.get("message") or "").strip()
        if not msg or msg == "...":
            continue
        role = "agent" if t.get("role") == "agent" else "user"
        turns.append(CallTurn(role=role, text=msg, t=t.get("time_in_call_secs")))

    meta = d.get("metadata") or {}
    analysis = d.get("analysis") or {}
    if not voicemail and "voicemail" in str(meta.get("termination_reason", "")).lower():
        voicemail = True
    if (
        not voicemail
        and "voicemail" in (analysis.get("transcript_summary") or "").lower()
    ):
        voicemail = True

    real_user = [x for x in turns if x.role == "user" and not _is_machine(x.text)]
    answered = None if status == "calling" else (not voicemail and len(real_user) > 0)
    return CallResult(
        call_id=call_id,
        status=status,
        conversation_id=d.get("conversation_id"),
        duration_s=meta.get("call_duration_secs"),
        transcript=turns,
        summary=analysis.get("transcript_summary"),
        answered=answered,
        voicemail=voicemail,
    )


class ElevenLabsCaller:
    def __init__(
        self,
        api_key: str | None = None,
        agent_id: str | None = None,
        phone_number_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        dial_timeout: float = 90.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("ELEVENLABS_API_KEY") or "").strip()
        self.agent_id = (agent_id or os.getenv("ELEVENLABS_AGENT_ID") or "").strip()
        self.phone_number_id = (
            phone_number_id or os.getenv("ELEVENLABS_PHONE_NUMBER_ID") or ""
        ).strip()
        if not (self.api_key and self.agent_id and self.phone_number_id):
            raise ElevenLabsError(
                "ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID not set"
            )
        self.dial_timeout = dial_timeout
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"xi-api-key": self.api_key},
            timeout=15.0,
            transport=transport,
        )
        self._pending: dict[str, _Pending] = {}

    # ---------- Caller interface ----------
    async def place_call(self, phone: str, context: CallContext) -> str:
        """Returns immediately with a local call id; dialing continues in the background."""
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        started = time.time()
        task = asyncio.create_task(self._dial(call_id, phone, context))
        self._pending[call_id] = _Pending(phone=phone, started=started, task=task)
        return call_id

    async def get_call(self, call_id: str) -> CallResult:
        p = self._pending.get(call_id)
        conv_id = (
            p.conversation_id if p else call_id
        )  # also accepts a raw conversation id
        if p and not conv_id:
            if p.error:
                return CallResult(
                    call_id=call_id, status="failed", answered=False, error=p.error
                )
            if not p.task.done():
                # Still dialing. After 15s, look for the conversation in case it already exists.
                if time.time() - p.started > 15:
                    p.conversation_id = await self._recover(p.started)
                if not p.conversation_id:
                    return CallResult(call_id=call_id, status="calling")
            conv_id = p.conversation_id
            if not conv_id:
                return CallResult(
                    call_id=call_id,
                    status="failed",
                    answered=False,
                    error=p.error or "no conversation",
                )
        r = await self._http.get(f"/v1/convai/conversations/{conv_id}")
        if r.status_code == 404:
            return CallResult(
                call_id=call_id, status="calling", conversation_id=conv_id
            )
        r.raise_for_status()
        return parse_conversation(call_id, r.json())

    # ---------- internals ----------
    async def _dial(self, call_id: str, phone: str, ctx: CallContext) -> None:
        p = self._pending[call_id]
        try:
            r = await self._http.post(
                "/v1/convai/sip-trunk/outbound-call",
                json={
                    "agent_id": self.agent_id,
                    "agent_phone_number_id": self.phone_number_id,
                    "to_number": phone,
                    "conversation_initiation_client_data": {
                        "dynamic_variables": build_dynamic_variables(ctx)
                    },
                },
                timeout=self.dial_timeout,
            )
            if r.status_code >= 400:
                p.error = f"HTTP {r.status_code}: {r.text[:200]}"
                return
            body = r.json()
            if body.get("success") is False and not body.get("conversation_id"):
                p.error = body.get("message") or "call not initiated"
                return
            p.conversation_id = p.conversation_id or body.get("conversation_id")
        except httpx.TimeoutException:
            p.conversation_id = p.conversation_id or await self._recover(p.started)
            if not p.conversation_id:
                p.error = "dial timed out and no conversation found"
        except Exception as e:  # noqa: BLE001 - a background dial task must never die silently
            p.error = f"{type(e).__name__}: {e}"

    async def _recover(self, started: float) -> str | None:
        try:
            r = await self._http.get(
                "/v1/convai/conversations",
                params={"agent_id": self.agent_id, "page_size": 5},
            )
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        for c in r.json().get("conversations", []):
            if (
                c.get("direction") == "outbound"
                and c.get("start_time_unix_secs", 0) >= started - 5
            ):
                return c.get("conversation_id")
        return None

    async def aclose(self) -> None:
        await self._http.aclose()
