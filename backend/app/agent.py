"""Rule planner plus the background tick and poll loops.

The owner can drop in NemotronPlanner with the same plan() signature later.
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
        self.planner = _select_planner(steps)

    async def tick(self) -> None:
        moment = now()
        async with self.store.lock:
            actions = self.planner.plan(list(self.store.cases.values()), moment)
            if actions:
                summary = ", ".join(
                    f"{action.tool} {action.policyholder_id} {action.reason or ''}".strip()
                    for action in actions
                )
            else:
                summary = "No actions"
            self.steps.add("plan", summary)
        for action in actions:
            await self.flow.execute(action)

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


def _select_planner(steps: StepLog) -> RulePlanner:
    if env("PLANNER", "rules") == "nemotron":
        try:
            from app.integrations.nemotron import NemotronPlanner

            return NemotronPlanner()
        except Exception as exc:  # noqa: BLE001 - missing planner file falls back to rules
            steps.add("error", f"Nemotron planner unavailable: {type(exc).__name__}")
    return RulePlanner()
