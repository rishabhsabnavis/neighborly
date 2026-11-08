"""Menu, emergency path, claim confirmation, and outbound texts."""

from __future__ import annotations

import asyncio
import re
import time

from app.fallbacks import (
    HeuristicBrain,
    classify,
    follow_up_text,
    life_safety,
    template_claim,
)
from app.integrations.base import CallContext, CallResult
from app.integrations.fake import FakeMessenger
from app.models import (
    Action,
    Call,
    CallReason,
    CheckinRunResponse,
    ClaimDraft,
    HumanRequest,
    MenuChoice,
    Message,
    Triage,
    TriageSource,
)
from app.steps import StepLog
from app.store import Store, StoredCase, mask_phone, touch
from app.timeutil import now_iso, plus_seconds

MENU_CHOICES = {"1", "2", "3", "4", "0"}
EMERGENCY_TEXT = "If you're in danger, call 911 now. We've marked you top priority and are calling you."
EMERGENCY_RETRY_TEXT = (
    "If you're in danger call 911. Reply here or call (701) 888-0282 to reach us."
)
HUMAN_TEXT = "A State Farm agent will contact you within 15 min."
MISSED_CALL_TEXT = "We couldn't reach you by phone. Reply here or call (701) 888-0282."
JOIN_TEXT = (
    "You're signed up for State Farm storm check-ins. "
    "We'll text you if a disaster hits your county."
)
WELFARE = "Welfare check recommended"


def menu_text(case: StoredCase) -> str:
    first = case.name.split()[0]
    return (
        f"{first}, this is State Farm. Hurricane Isaias hit {case.county} County. "
        "Reply 1 Safe, 2 Need help, 3 Emergency, 4 Call me, 0 Talk to a person."
    )


def parse_menu(text: str) -> MenuChoice:
    raw = text.strip()
    lowered = raw.lower()
    match = re.match(r"^([0-4])\b", lowered)
    if match and match.group(1) in MENU_CHOICES:
        return match.group(1)  # type: ignore[return-value]
    if lowered == "yes" or lowered.startswith(("yes ", "yes,", "yes.")):
        return "yes"
    if any(re.search(rf"\b{word}\b", lowered) for word in ("person", "human", "agent")):
        return "0"
    if re.search(r"\bcall\b", lowered) and "911" not in lowered:
        return "4"
    return "free"


def _summary(case: StoredCase) -> str:
    if case.summary and case.summary.strip() not in {"1", "2", "3", "4", "0"}:
        return case.summary
    for message in reversed(case.messages):
        text = message.text.strip()
        if message.from_ == "policyholder" and text not in {
            "1",
            "2",
            "3",
            "4",
            "0",
            "YES",
        }:
            return text[:240]
    return case.summary or "No details yet"


class Flow:
    def __init__(
        self,
        store: Store,
        steps: StepLog,
        messenger: object,
        caller: object,
        brain: object,
        fake: FakeMessenger,
    ) -> None:
        self.store = store
        self.steps = steps
        self.messenger = messenger
        self.caller = caller
        self.brain = brain
        self.fake = fake
        self.placed: set[str] = set()
        # The heuristic brain is instant and offline, so it runs inline (tests, no-key demo).
        # A live brain (Nemotron) gets timeouts, a heuristic fallback and background claim drafts.
        self.live_brain = not isinstance(brain, HeuristicBrain)
        self._drafting: set[str] = set()
        self._redraft: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    async def run_checkin(self, disaster_number: int) -> CheckinRunResponse:
        del disaster_number
        async with self.store.lock:
            self.store.run_count += 1
            run_id = f"run_{self.store.run_count:02d}"
            live = 0
            for case in self.store.cases.values():
                if case.status != "pending":
                    continue
                if case.live and case.call_only:
                    case.status = "texted"
                    case.channel = "voice"
                    case.texted_at = now_iso()
                    live += 1
                    self.steps.add(
                        "plan",
                        "Call-only line; calling if there is no reply",
                        policyholder_id=case.id,
                    )
                    continue
                if case.live and not case.opted_in:
                    continue
                text = menu_text(case)
                if case.live:
                    await self._say(case, text)
                    live += 1
                else:
                    self._remember(case, "agent", "imessage", text)
                case.status = "texted"
                case.phase = "menu"
                case.channel = "imessage"
                case.texted_at = case.last_contact_at or now_iso()
            return CheckinRunResponse(
                run_id=run_id, queued=len(self.store.cases), live=live
            )

    async def handle_id(self, policyholder_id: str, text: str) -> None:
        async with self.store.lock:
            case = self.store.cases.get(policyholder_id)
            if case is None:
                raise KeyError(policyholder_id)
            await self._ingest(case, text, "imessage")

    async def handle_phone(self, phone: str, text: str) -> None:
        async with self.store.lock:
            case = self.store.by_phone(phone)
            if case is None:
                self.steps.add("error", f"Unknown sender {mask_phone(phone)}")
                return
            await self._ingest(case, text, "imessage")

    async def place_manual(self, policyholder_id: str) -> str:
        async with self.store.lock:
            case = self.store.cases.get(policyholder_id)
            if case is None:
                raise KeyError(policyholder_id)
            call_id = await self._place(case, "requested")
            if call_id is None:
                raise RuntimeError("call failed")
            return call_id

    async def execute(self, action: Action) -> None:
        async with self.store.lock:
            case = self.store.cases.get(action.policyholder_id)
            if case is None:
                self.steps.add(
                    "error",
                    "unknown policyholder",
                    policyholder_id=action.policyholder_id,
                )
                return
            if action.tool == "place_call":
                if case.status == "calling" or case.active_call_id:
                    return
                await self._place(case, action.reason or "requested")
            elif action.tool == "send_imessage" and action.text:
                await self._say(case, action.text)
            elif action.tool == "request_human":
                await self._human(case, action.text or "Asked for a person")
            elif action.tool == "draft_claim":
                await self._draft(case, announce=True)
            elif action.tool == "record_triage" and action.urgency:
                triage = classify(action.summary or action.text or "", "imessage")
                if action.summary:
                    triage.summary = action.summary
                if action.action:
                    triage.action = action.action
                self._apply_triage(case, triage)

    async def resolve_call(self, case: StoredCase, result: CallResult) -> None:
        """Apply a finished call. Caller holds the store lock."""

        call = next(
            (item for item in case.calls if item.call_id == result.call_id), None
        )
        if call is None and case.active_call_id == result.call_id:
            call = Call(call_id=result.call_id, reason="requested", status="calling")
            case.calls.append(call)
        if call is None:
            return
        if result.status == "calling":
            return
        unanswered = (
            result.status == "failed" or result.voicemail or result.answered is False
        )
        call.status = "failed" if result.status == "failed" else "done"
        call.duration_s = result.duration_s
        call.transcript_summary = result.summary
        case.active_call_id = None
        if unanswered:
            await self._unanswered(case, call)
            return
        for turn in result.transcript:
            sender = "voice_agent" if turn.role == "agent" else "policyholder"
            self._remember(case, sender, "voice", turn.text)
        # Only the policyholder's words count: the agent's own questions
        # ("is anyone injured?") must not trigger the emergency path.
        spoken = "\n".join(
            turn.text for turn in result.transcript if turn.role != "agent"
        )
        case.status = "called"
        case.channel = "voice"
        if not spoken.strip():
            self.steps.add(
                "triage", "Call ended with no reply", policyholder_id=case.id
            )
            return
        triage = await self._triage(case, spoken, "call")
        self._apply_triage(case, triage)
        self.steps.add(
            "triage",
            triage.summary,
            policyholder_id=case.id,
            tool="record_triage",
        )
        if life_safety(spoken) and call.reason != "emergency":
            # They just answered, so flag and text 911 guidance instead of dialing again.
            await self._flag_emergency(case, triage)
        if any(parse_menu(line) == "0" for line in spoken.splitlines()):
            await self._human(case, "Asked for a person on the call")
        if call.reason != "emergency":
            await self._draft(case, announce=True)

    async def _ingest(self, case: StoredCase, text: str, source: TriageSource) -> None:
        body = text.strip()
        if not body:
            return
        if body.lower() == "join":
            case.opted_in = True
            self._remember(case, "policyholder", "imessage", body)
            await self._say(case, JOIN_TEXT)
            return
        self._remember(case, "policyholder", "imessage", body)
        choice = parse_menu(body)
        if choice == "3" or (choice == "free" and life_safety(body)):
            await self._emergency(case, source)
            return
        if choice == "yes" and case.claim_draft is not None:
            case.claim_draft.status = "confirmed"
            self.steps.add(
                "claim",
                f"Confirmed {case.claim_draft.claim_id}",
                policyholder_id=case.id,
                tool="draft_claim",
            )
            await self._say(case, f"Confirmed claim {case.claim_draft.claim_id}.")
            return
        if choice == "0":
            await self._human(case, "Asked for a person")
            return
        if choice == "4":
            case.status = "replied"
            if not case.summary or case.summary.strip() in {"1", "2", "3", "4", "0"}:
                case.summary = "Asked for a call"
            await self._place(case, "requested")
            return
        if choice == "1":
            await self._safe(case)
            return
        await self._help(case, body, source)

    async def _safe(self, case: StoredCase) -> None:
        triage = Triage(
            urgency=1,
            label="safe",
            needs=[],
            summary="Safe, no help needed",
            action="No help needed",
            source="imessage",
        )
        self._apply_triage(case, triage)
        case.status = "safe"
        case.phase = "closed"
        first = case.name.split()[0]
        await self._say(
            case,
            f"Glad you're safe, {first}. We'll close this check-in. Text us if anything changes.",
        )
        self.steps.add(
            "triage", triage.summary, policyholder_id=case.id, tool="record_triage"
        )

    async def _help(self, case: StoredCase, text: str, source: TriageSource) -> None:
        was_critical = case.urgency == 4
        triage = await self._triage(case, text, source)
        self._apply_triage(case, triage)
        if case.status in {"pending", "texted"}:
            case.status = "replied"
        self.steps.add(
            "triage", triage.summary, policyholder_id=case.id, tool="record_triage"
        )
        # Heuristic life-safety words, or the brain newly reaching 4 (its safety floor
        # catches e.g. "oxygen + power out"), take the emergency path.
        if triage.urgency == 4 and (life_safety(text) or not was_critical):
            await self._emergency(case, source, case.triage)
            return
        question = await self._follow_up(case, text)
        if question and case.followups_sent < 2:
            await self._say(case, question)
            case.followups_sent += 1
            case.phase = "followup"
            case.status = "replied"
            return
        case.status = "replied"
        await self._draft(case, announce=True)

    async def _flag_emergency(self, case: StoredCase, triage: Triage) -> None:
        if triage.urgency < 4:
            triage.urgency = 4
            triage.label = "critical"
            triage.action = "Emergency"
        self._apply_triage(case, triage)
        case.urgency = 4
        case.human_requested = True
        case.human_request = HumanRequest(
            requested=True, reason="Emergency", ts=now_iso()
        )
        self.steps.add(
            "triage", "EMERGENCY", policyholder_id=case.id, tool="record_triage"
        )
        await self._say(case, EMERGENCY_TEXT)

    async def _emergency(
        self, case: StoredCase, source: TriageSource, triage: Triage | None = None
    ) -> None:
        already = bool(case.active_call_id)
        if triage is None:
            triage = classify(_latest_policyholder_text(case), source)
        await self._flag_emergency(case, triage.model_copy())
        if already:
            self.steps.add(
                "plan",
                "Already on a call; emergency flagged for the voice agent",
                policyholder_id=case.id,
            )
            return
        await self._place(case, "emergency")

    async def _human(self, case: StoredCase, reason: str) -> None:
        case.human_requested = True
        case.human_request = HumanRequest(requested=True, reason=reason, ts=now_iso())
        if case.status != "calling":
            case.channel = "human"
        self.steps.add(
            "tool_call",
            f"request_human {reason}",
            policyholder_id=case.id,
            tool="request_human",
        )
        await self._say(case, HUMAN_TEXT)

    async def _triage(
        self, case: StoredCase, text: str, source: TriageSource
    ) -> Triage:
        """Brain triage (Nemotron) with the heuristic as the fallback. Caller holds the lock."""
        if not self.live_brain:
            return classify(text, source)
        started = time.perf_counter()
        try:
            raw = await asyncio.wait_for(self.brain.triage(case), 9)  # type: ignore[attr-defined]
            triage = Triage.model_validate(
                {**_plain(raw), "source": source if source != "seed" else "imessage"}
            )
        except Exception as exc:  # noqa: BLE001 - the heuristic keeps the demo moving
            self.steps.add(
                "error",
                f"Nemotron triage failed ({type(exc).__name__}); heuristic used",
                policyholder_id=case.id,
                tool="record_triage",
                ms=_ms(started),
            )
            return classify(text, source)
        floor = getattr(self.brain, "last_floor_reason", None)
        self.steps.add(
            "tool_result",
            f"Nemotron triage: urgency {triage.urgency}"
            + (f" (safety floor: {floor})" if floor else ""),
            policyholder_id=case.id,
            tool="record_triage",
            ms=_ms(started),
        )
        return triage

    async def _follow_up(self, case: StoredCase, text: str) -> str | None:
        """Next policy-aware question, or None when it's time to draft the claim."""
        bare = text.strip().isdigit()
        if case.followups_sent >= 2:
            return None
        if not self.live_brain:
            return follow_up_text(case) if bare else None
        started = time.perf_counter()
        try:
            question = await asyncio.wait_for(self.brain.follow_up(case), 7)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self.steps.add(
                "error",
                f"Nemotron follow-up failed ({type(exc).__name__}); template used",
                policyholder_id=case.id,
                tool="send_imessage",
                ms=_ms(started),
            )
            return follow_up_text(case) if bare else None
        if getattr(self.brain, "last_dropped", None):
            self.steps.add(
                "error",
                "Nemotron follow-up: dropped a sentence with an unverified dollar amount",
                policyholder_id=case.id,
                tool="send_imessage",
            )
        self.steps.add(
            "tool_result",
            "Nemotron follow-up: " + ("asked" if question else "no more questions"),
            policyholder_id=case.id,
            tool="send_imessage",
            ms=_ms(started),
        )
        return question

    async def _draft(self, case: StoredCase, announce: bool) -> None:
        """Draft (or silently refresh) the claim. A confirmed claim is final."""
        if case.claim_draft is not None and case.claim_draft.status == "confirmed":
            return
        announce = announce and case.claim_draft is None
        if not self.live_brain:
            try:
                draft = self._as_claim(case, await self.brain.draft_claim(case))  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - template claim is the demo fallback
                self.steps.add(
                    "error",
                    f"draft_claim failed: {type(exc).__name__}",
                    policyholder_id=case.id,
                    tool="draft_claim",
                )
                draft = template_claim(case)
            await self._apply_draft(case, draft, announce)
            return
        # Live brain: the reply text has already gone out; draft off the lock (up to 15s).
        if case.id in self._drafting:
            self._redraft.add(case.id)
            return
        self._drafting.add(case.id)
        task = asyncio.create_task(self._draft_in_background(case.id, announce))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _draft_in_background(self, policyholder_id: str, announce: bool) -> None:
        try:
            while True:
                case = self.store.cases.get(policyholder_id)
                if case is None:
                    return
                started = time.perf_counter()
                try:
                    raw = await asyncio.wait_for(self.brain.draft_claim(case), 15)  # type: ignore[attr-defined]
                    draft = self._as_claim(case, raw)
                except Exception as exc:  # noqa: BLE001 - template claim is the demo fallback
                    self.steps.add(
                        "error",
                        f"Nemotron draft_claim failed ({type(exc).__name__}); template used",
                        policyholder_id=policyholder_id,
                        tool="draft_claim",
                        ms=_ms(started),
                    )
                    draft = template_claim(case)
                async with self.store.lock:
                    current = self.store.cases.get(policyholder_id)
                    confirmed = (
                        current is not None
                        and current.claim_draft is not None
                        and current.claim_draft.status == "confirmed"
                    )
                    if current is case and not confirmed:  # skip after a demo reset
                        await self._apply_draft(
                            case,
                            draft,
                            announce and case.claim_draft is None,
                            _ms(started),
                        )
                if policyholder_id not in self._redraft:
                    return
                self._redraft.discard(policyholder_id)
                announce = False
        finally:
            self._drafting.discard(policyholder_id)

    def _as_claim(self, case: StoredCase, raw: object) -> ClaimDraft:
        if isinstance(raw, ClaimDraft):
            return raw
        data = _plain(raw)
        deductible = data.get("deductible")
        data["deductible"] = int(
            deductible if deductible is not None else case.policy.deductible
        )
        return ClaimDraft.model_validate(data)

    async def _apply_draft(
        self,
        case: StoredCase,
        draft: ClaimDraft,
        announce: bool,
        ms: int | None = None,
    ) -> None:
        case.claim_draft = draft
        case.claim_id = draft.claim_id
        case.phase = "claim_confirm"
        self.steps.add(
            "claim",
            f"Drafted {draft.claim_id}",
            policyholder_id=case.id,
            tool="draft_claim",
            ms=ms,
        )
        if announce:
            await self._say(
                case,
                f"We started claim {draft.claim_id} for you. Reply YES to confirm.",
            )

    async def _place(self, case: StoredCase, reason: CallReason) -> str | None:
        opening = None
        if reason == "emergency":
            opening = "If you're in danger, hang up and call 911 now."
        context = CallContext(
            name=case.name,
            summary=_summary(case),
            reason=reason,
            opening=opening,
        )
        started = time.perf_counter()
        self.steps.add(
            "tool_call",
            f"place_call reason={reason}",
            policyholder_id=case.id,
            tool="place_call",
        )
        try:
            call_id = await asyncio.wait_for(
                self.caller.place_call(case.phone, context),  # type: ignore[attr-defined]
                10,
            )
        except Exception as exc:  # noqa: BLE001 - the demo logs the failure and continues
            self.steps.add(
                "error",
                f"call failed: {exc}"[:240],
                policyholder_id=case.id,
                tool="place_call",
                ms=_ms(started),
            )
            return None
        case.calls.append(Call(call_id=call_id, reason=reason, status="calling"))
        case.active_call_id = call_id
        self.placed.add(call_id)
        case.status = "calling"
        case.channel = "voice"
        if reason == "emergency":
            case.emergency_attempts += 1
            case.emergency_retry_at = None
        self.steps.add(
            "tool_result",
            f"place_call {call_id} reason={reason}",
            policyholder_id=case.id,
            tool="place_call",
            ms=_ms(started),
        )
        return call_id

    async def _unanswered(self, case: StoredCase, call: Call) -> None:
        if call.reason == "emergency" and case.emergency_attempts < 2:
            case.status = "replied"
            case.emergency_retry_at = plus_seconds(60)
            await self._say(case, EMERGENCY_RETRY_TEXT)
            self.steps.add(
                "plan",
                "Emergency call unanswered; retry in 60s",
                policyholder_id=case.id,
                tool="place_call",
            )
            return
        case.status = "unreachable"
        case.emergency_retry_at = None
        if call.reason == "emergency":
            if case.triage is not None:
                case.triage.action = WELFARE
            case.human_requested = True
            if case.human_request is None:
                case.human_request = HumanRequest(
                    requested=True,
                    reason="Emergency",
                    ts=now_iso(),
                )
        else:
            await self._say(case, MISSED_CALL_TEXT)
        self.steps.add(
            "triage",
            WELFARE if call.reason == "emergency" else "Call unanswered",
            policyholder_id=case.id,
        )

    async def _say(self, case: StoredCase, text: str) -> None:
        from app.coverage import validate_amounts

        if case.call_only:
            # Phone B has no iMessage line: a text would fail (or reach the wrong person).
            self.steps.add(
                "plan",
                "Call-only line; text skipped",
                policyholder_id=case.id,
                tool="send_imessage",
            )
            return

        clean = validate_amounts(text, case.policy)
        if clean != text:
            self.steps.add(
                "error",
                "Dropped a sentence with an unverified dollar amount",
                policyholder_id=case.id,
                tool="send_imessage",
            )
        if not clean:
            return
        started = time.perf_counter()
        self.steps.add(
            "tool_call",
            "send_imessage",
            policyholder_id=case.id,
            tool="send_imessage",
        )
        message_id = await self._send(case, clean)
        self._remember(case, "agent", "imessage", clean, message_id)
        self.steps.add(
            "tool_result",
            clean[:160],
            policyholder_id=case.id,
            tool="send_imessage",
            ms=_ms(started),
        )

    async def _send(self, case: StoredCase, text: str) -> str:
        try:
            return await asyncio.wait_for(
                self.messenger.send(case.phone, text),  # type: ignore[attr-defined]
                10,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the in-memory messenger
            self.steps.add(
                "error",
                f"send failed: {type(exc).__name__}",
                policyholder_id=case.id,
                tool="send_imessage",
            )
            if self.messenger is not self.fake:
                try:
                    return await self.fake.send(case.phone, text)
                except Exception as fallback_exc:  # noqa: BLE001
                    self.steps.add(
                        "error",
                        f"fake send failed: {type(fallback_exc).__name__}",
                        policyholder_id=case.id,
                        tool="send_imessage",
                    )
            return f"m_local_{case.id}"

    def _remember(
        self,
        case: StoredCase,
        sender: str,
        channel: str,
        text: str,
        message_id: str | None = None,
    ) -> None:
        stamp = touch(case)
        case.messages.append(
            Message(
                id=message_id or f"m_{case.id}_{len(case.messages) + 1}",
                ts=stamp,
                from_=sender,  # type: ignore[arg-type]
                channel=channel,  # type: ignore[arg-type]
                text=text,
            )
        )

    def _apply_triage(self, case: StoredCase, triage: Triage) -> None:
        """Urgency 4 is sticky (only a person clears it); a bare menu digit keeps prior details."""
        prev = case.triage
        if prev is not None:
            bare_digit = triage.summary.strip() in {"0", "1", "2", "3", "4"}
            sticky = prev.urgency == 4 or case.urgency == 4
            updates: dict = {}
            if sticky or bare_digit:
                merged = list(prev.needs) + [
                    n for n in triage.needs if n not in prev.needs
                ]
                updates["needs"] = merged
            if bare_digit and prev.summary:
                updates["summary"] = prev.summary
            if sticky and triage.urgency < 4:
                updates.update(
                    urgency=4, label="critical", action=prev.action or "Emergency"
                )
            if updates:
                triage = triage.model_copy(update=updates)
        case.triage = triage
        case.urgency = triage.urgency
        case.summary = triage.summary


def _plain(obj: object) -> dict:
    """Pydantic model / dataclass / dict -> dict (brain modules use their own result models)."""
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    from dataclasses import asdict, is_dataclass

    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"unexpected brain result {type(obj).__name__}")


def _latest_policyholder_text(case: StoredCase) -> str:
    for message in reversed(case.messages):
        if message.from_ == "policyholder":
            return message.text
    return ""


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
