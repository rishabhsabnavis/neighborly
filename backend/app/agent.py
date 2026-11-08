"""Rule planner plus the background tick and poll loops.

PLANNER=nemotron adds NemotronPlanner on top of the rules (see Agent._nemotron_plan).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.flow import Flow
from app.integrations.base import CallResult
from app.models import Action
from app.settings import agent_tick_seconds, env, no_reply_seconds
from app.steps import StepLog
from app.store import Store, StoredCase
from app.timeutil import now, parse_ts


class RulePlanner:
    def plan(self, cases: list[StoredCase], moment: datetime) -> list[Action]:
        actions: list[Action] = []
        limit = no_reply_seconds()
        for case in cases:
            if not case.live or case.status == "calling" or case.active_call_id:
                continue
            if (
                case.emergency_retry_at
                and case.emergency_attempts < 2
                and parse_ts(case.emergency_retry_at) <= moment
            ):
                actions.append(
                    Action(
                        tool="place_call",
                        policyholder_id=case.id,
                        reason="emergency",
                    )
                )
                continue
            if case.status == "texted" and case.texted_at:
                elapsed = (moment - parse_ts(case.texted_at)).total_seconds()
                due = limit <= 0 or elapsed >= limit
                if due:
                    actions.append(
                        Action(
                            tool="place_call",
                            policyholder_id=case.id,
                            reason="no_reply",
                        )
                    )
        return actions


class Agent:
    def __init__(self, store: Store, steps: StepLog, flow: Flow) -> None:
        self.store = store
        self.steps = steps
        self.flow = flow
        self.rules = RulePlanner()
        self.nemotron = _select_planner(steps)
        self._planning = False

    async def tick(self) -> None:
        if self._planning:  # never two plans at once (slow Nemotron tick + next tick)
            return
        self._planning = True
        try:
            moment = now()
            async with self.store.lock:
                cases = list(self.store.cases.values())
                rule_actions = self.rules.plan(cases, moment)
                snapshot = (
                    planner_snapshot(cases, moment)
                    if self.nemotron is not None
                    else None
                )
            actions = rule_actions
            if self.nemotron is not None and snapshot is not None:
                actions = await self._nemotron_plan(snapshot, rule_actions)
            elif actions:
                self.steps.add("plan", _summary(actions))
        finally:
            self._planning = False
        for action in actions:
            await self.flow.execute(action)

    async def _nemotron_plan(
        self, snapshot: dict, rule_actions: list[Action]
    ) -> list[Action]:
        """Nemotron picks and orders actions (outside the store lock). The core's own timing
        rules (no-reply call, emergency retry) are always kept, so the demo can't stall."""
        from app.integrations.planner import due_actions

        rows = snapshot["policyholders"]
        due = due_actions(rows, now(), int(no_reply_seconds()))
        if not due and not rule_actions:
            return []  # nothing due: no model call, no noise in the step log
        assert self.nemotron is not None
        try:
            proposed = await asyncio.wait_for(self.nemotron.plan(snapshot), 20)
            last = getattr(self.nemotron, "last", None)
            if last is not None:
                self.steps.add("plan", last.log_text()[:600], ms=last.ms)
        except Exception as exc:  # noqa: BLE001 - rules alone keep the demo moving
            self.steps.add(
                "error", f"Nemotron planner failed ({type(exc).__name__}); rules used"
            )
            proposed = []
        live_ids = {row["id"] for row in rows if row.get("live")}
        actions = [
            a
            for a in (to_core_action(p) for p in proposed)
            if a and a.policyholder_id in live_ids
        ]
        have = {(a.tool, a.policyholder_id) for a in actions}
        missing = [a for a in rule_actions if (a.tool, a.policyholder_id) not in have]
        if missing:
            self.steps.add("plan", "Rules: " + _summary(missing))
        return actions + missing

    async def tick_loop(self) -> None:
        while True:
            await asyncio.sleep(agent_tick_seconds())
            await self.tick()

    async def poll_message_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            await self.poll_messages()

    async def poll_call_loop(self) -> None:
        while True:
            await asyncio.sleep(3)
            await self.poll_calls()

    async def poll_messages(self) -> None:
        try:
            messages = await asyncio.wait_for(self.flow.messenger.poll_inbound(), 10)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - one bad poll must not kill the loop
            self.steps.add("error", f"inbound poll failed: {type(exc).__name__}")
            return
        for message in messages:
            await self.flow.handle_phone(message.phone, message.text)

    async def poll_calls(self) -> None:
        async with self.store.lock:
            pending = [
                (case.id, case.active_call_id)
                for case in self.store.cases.values()
                if case.active_call_id and case.active_call_id in self.flow.placed
            ]
        for policyholder_id, call_id in pending:
            if not call_id:
                continue
            try:
                result: CallResult = await asyncio.wait_for(
                    self.flow.caller.get_call(call_id),  # type: ignore[attr-defined]
                    10,
                )
            except Exception as exc:  # noqa: BLE001 - a failed lookup must not kill the loop
                self.steps.add(
                    "error",
                    f"get_call failed: {type(exc).__name__}",
                    policyholder_id=policyholder_id,
                    tool="place_call",
                )
                continue
            if result.status == "calling":
                continue
            async with self.store.lock:
                case = self.store.cases.get(policyholder_id)
                if case is None or case.active_call_id != call_id:
                    continue
                await self.flow.resolve_call(case, result)


def _summary(actions: list[Action]) -> str:
    return ", ".join(
        f"{a.tool} {a.policyholder_id} {a.reason or ''}".strip() for a in actions
    )


def planner_snapshot(cases: list[StoredCase], moment: datetime) -> dict:
    """SPEC PolicyholderRow fields plus the extras NemotronPlanner reads."""
    rows = []
    for case in cases:
        row = case.to_row().model_dump(mode="json")
        last = case.calls[-1] if case.calls else None
        unanswered = case.status == "unreachable" or (
            last is not None and last.status == "failed"
        )
        row.update(
            opted_in=case.opted_in,
            # The core already texts after an unanswered call, so count that text.
            followups_sent=max(case.followups_sent, 1 if unanswered else 0),
            call_status=last.status if last else None,
            call_answered=False if unanswered else None,
            call_reason=last.reason if last else None,
            call_attempts=max(case.emergency_attempts, 1 if last else 0),
            policy=case.policy.model_dump(mode="json"),
        )
        if case.status == "texted" and case.texted_at:
            row["last_contact_at"] = case.texted_at
        rows.append(row)
    return {
        "now": moment.isoformat(timespec="seconds"),
        "no_reply_seconds": int(no_reply_seconds()),
        "policyholders": rows,
    }


def to_core_action(p: object) -> Action | None:
    """planner.Action (tool, policyholder_id, args, why) -> models.Action."""
    tool = getattr(p, "tool", None)
    pid = getattr(p, "policyholder_id", None)
    args = getattr(p, "args", {}) or {}
    if (
        tool not in {"send_imessage", "place_call", "request_human", "draft_claim"}
        or not pid
    ):
        return None
    reason = args.get("reason")
    if tool == "place_call":
        if reason not in {"requested", "no_reply", "emergency"}:
            reason = "no_reply"
        return Action(tool="place_call", policyholder_id=pid, reason=reason)
    if tool == "send_imessage":
        text = str(args.get("text") or "").strip()
        return Action(tool=tool, policyholder_id=pid, text=text) if text else None
    if tool == "request_human":
        return Action(
            tool=tool,
            policyholder_id=pid,
            text=str(reason or getattr(p, "why", "") or "Critical case")[:120],
        )
    return Action(tool="draft_claim", policyholder_id=pid)


def _select_planner(steps: StepLog) -> object | None:
    """NemotronPlanner when PLANNER=nemotron, else None (rules only)."""
    if env("PLANNER", "rules") != "nemotron":
        return None
    try:
        from app.integrations.planner import NemotronPlanner

        return NemotronPlanner()
    except Exception as exc:  # noqa: BLE001 - a broken planner must not stop startup
        steps.add(
            "error",
            f"Nemotron planner unavailable: {type(exc).__name__}: {exc}"[:240],
        )
    return None
