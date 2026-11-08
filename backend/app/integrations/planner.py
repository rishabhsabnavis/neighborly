"""Nemotron planner: decides each agent tick what to do next across all open cases.

Implements the planner slot from docs/BACKEND_PROMPT.md ("Agent loop"):
    async plan(snapshot) -> list[Action]       (selected with PLANNER=nemotron)
plus `last` (a PlanResult) holding the reasoning, latency and fallback info for the step log.

How it works (hybrid, so the demo never depends on the model getting it right):
1. Rules compute what is DUE: a texted person silent past NO_REPLY_SECONDS -> place_call(no_reply);
   a failed/unanswered call -> follow-up text; an urgency-4 case with no human -> request_human; a
   triaged case with no claim yet -> draft_claim.
2. Nemotron (super, reasoning ON, tool calling) sees the open cases plus the due list. It chooses
   and orders the actions and writes any text. Its reasoning goes in the `plan` step log entry
   (the "beyond a chatbot" evidence for the Nvidia judges).
3. Guardrails: unknown ids, non-live phones for send/call, calling someone already on a call,
   early no-reply calls, duplicates, and more than MAX_ACTIONS per tick are dropped. Any due
   action the model skipped is added back (marked rule_fallback). If the model fails or times
   out, the rule actions are used alone.

The snapshot is a dict {"now": iso, "no_reply_seconds": int, "policyholders": [rows]} or just the
list of rows. Rows use SPEC's PolicyholderRow fields (id, name, status, channel, human_requested,
urgency, summary, claim_id, last_contact_at, live). Optional extras the core may add: "opted_in",
"call_status" ("calling"|"done"|"failed"), "call_answered" (bool), "followups_sent" (int), "call_reason" (requested|no_reply|emergency), "call_attempts" (int),
"policy" (only used to check $ amounts in texts).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from app.integrations.nemotron import (
    BASE_URL,
    DEFAULT_AGENT_MODEL,
    as_dict,
    validate_amounts,
)

ToolName = Literal["send_imessage", "place_call", "request_human", "draft_claim"]
MAX_ACTIONS = 5
MAX_ROWS_TO_MODEL = 25

PLANNER_SYSTEM = """You are SafeFarm's disaster-response planner for State Farm after Hurricane Isaias.
Every 15 seconds you get the live open policyholder cases and a list of actions our rules say are DUE.
Decide what to do THIS round, using the tools. Priorities, in order:
1. Life safety: urgency 4 first. Make sure every urgency-4 case has a human State Farm agent (request_human).
   Emergencies (call_reason emergency) that went unanswered: retry the call once, then text and get a human.
2. Silence is a warning sign: anyone texted who has not replied within no_reply_seconds gets a call
   (place_call reason=no_reply). If a call failed or went to voicemail, send one short iMessage instead.
3. Paperwork last: draft_claim for cases that have triage but no claim yet.
Do every DUE action unless there is a clear reason not to, and do not invent actions for people who
are fine. Never act on someone who is "calling" right now. Keep iMessage texts under 250 characters,
calm and plain, and say this is State Farm. If nothing is needed, call `wait`.
Before acting, think briefly about who is most at risk."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "place_call",
            "description": "Have the voice agent phone this policyholder now.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policyholder_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "enum": ["no_reply", "requested", "emergency"],
                    },
                    "why": {
                        "type": "string",
                        "description": "one short sentence for the log",
                    },
                },
                "required": ["policyholder_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_imessage",
            "description": "Text this policyholder over iMessage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policyholder_id": {"type": "string"},
                    "text": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["policyholder_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human",
            "description": "Put this case in the human State Farm agent queue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policyholder_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["policyholder_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_claim",
            "description": "Write the claim draft for this case from everything we know.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policyholder_id": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["policyholder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Nothing needs doing this round.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass
class Action:
    tool: ToolName
    policyholder_id: str
    args: dict[str, Any] = field(default_factory=dict)  # reason / text for the tool
    why: str = ""
    source: Literal["nemotron", "rule_fallback", "rules"] = "nemotron"


@dataclass
class PlanResult:
    actions: list[Action]
    reasoning: str  # Nemotron's reasoning_content (or why rules were used)
    ms: int
    model: str
    used_fallback: bool = False
    dropped: list[str] = field(default_factory=list)  # guardrail notes for the log
    error: str | None = None

    def log_text(self) -> str:
        """Short text for the `plan` step: each decision with the model's own reason.
        (The raw reasoning opens by restating the instructions, so it lives in
        `reasoning` for an expandable view instead.)"""
        if not self.actions:
            return "Nemotron plan: nothing needs doing this round."
        who = "Rules" if self.model == "rules" else "Nemotron"
        parts = []
        for a in self.actions:
            why = a.why or a.args.get("reason") or ""
            tag = " [rule]" if a.source == "rule_fallback" else ""
            parts.append(
                f"{a.tool}({a.policyholder_id}){tag}" + (f": {why}" if why else "")
            )
        return f"{who} plan ({self.ms} ms): " + "; ".join(parts)

    def reasoning_excerpt(self, limit: int = 600) -> str:
        """The end of the reasoning, where the model concludes (for an expandable log row)."""
        r = " ".join(self.reasoning.split())
        return r if len(r) <= limit else "..." + r[-(limit - 3) :]


# ---------- snapshot helpers ----------
def _rows(snapshot: Any) -> tuple[list[dict], datetime, int]:
    snap = snapshot if isinstance(snapshot, (dict, list)) else as_dict(snapshot)
    if isinstance(snap, list):
        rows, now, nrs = snap, None, None
    else:
        rows, now, nrs = (
            snap.get("policyholders") or [],
            snap.get("now"),
            snap.get("no_reply_seconds"),
        )
    rows = [r if isinstance(r, dict) else as_dict(r) for r in rows]
    now_dt = _parse_ts(now) or datetime.now(UTC)
    nrs = int(nrs or os.getenv("NO_REPLY_SECONDS") or 60)
    return rows, now_dt, nrs


def _parse_ts(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _age(row: dict, now: datetime) -> int | None:
    t = _parse_ts(row.get("last_contact_at"))
    return None if t is None else int((now - t).total_seconds())


def due_actions(rows: list[dict], now: datetime, no_reply_seconds: int) -> list[Action]:
    """What the rules say must happen this tick (also the fallback plan)."""
    out: list[Action] = []
    for r in rows:
        if not r.get("live"):
            continue  # seeded cases are pre-played scenery; the agent only works live ones
        pid, status, live = r.get("id"), r.get("status"), True
        age = _age(r, now)
        if status == "calling" or r.get("call_status") == "calling":
            continue
        if live and status == "texted" and age is not None and age >= no_reply_seconds:
            out.append(
                Action(
                    "place_call",
                    pid,
                    {"reason": "no_reply"},
                    f"no reply for {age}s",
                    "rules",
                )
            )
            continue
        unanswered = r.get("call_status") == "failed" or r.get("call_answered") is False
        if live and unanswered and status in ("unreachable", "called"):
            emergency = r.get("call_reason") == "emergency"
            attempts = int(r.get("call_attempts") or 1)
            if emergency and attempts < 2:
                # SPEC Emergency path step 5: retry the call once after 60s.
                if age is not None and age >= no_reply_seconds:
                    out.append(
                        Action(
                            "place_call",
                            pid,
                            {"reason": "emergency"},
                            "emergency call unanswered, retrying once",
                            "rules",
                        )
                    )
                continue
            if int(r.get("followups_sent") or 0) == 0:
                text = (
                    "If you're in danger call 911. Reply here or call (701) 888-0282 to reach us."
                    if emergency
                    else "This is State Farm. We tried to call you after Hurricane Isaias. "
                    "Please reply 1 if you're safe or 2 if you need help, or call (701) 888-0282. "
                    "If you are in danger, call 911."
                )
                out.append(
                    Action(
                        "send_imessage",
                        pid,
                        {"text": text},
                        "call not answered",
                        "rules",
                    )
                )
            if emergency and not r.get("human_requested"):
                out.append(
                    Action(
                        "request_human",
                        pid,
                        {"reason": "Welfare check recommended"},
                        "emergency, unreachable",
                        "rules",
                    )
                )
            continue
        if r.get("urgency") == 4 and not r.get("human_requested"):
            out.append(
                Action(
                    "request_human",
                    pid,
                    {"reason": "critical case"},
                    "urgency 4 without a human",
                    "rules",
                )
            )
        if (
            r.get("urgency")
            and not r.get("claim_id")
            and status in ("replied", "called")
            and not r.get("collecting_details")
        ):
            out.append(Action("draft_claim", pid, {}, "triaged, no claim yet", "rules"))
    return out


def _model_view(rows: list[dict], now: datetime) -> dict:
    """Live open cases (most urgent first) plus a one-line summary of the seeded ones."""
    live = [r for r in rows if r.get("live")]
    live.sort(key=lambda r: (-(r.get("urgency") or 0), -(_age(r, now) or 0)))
    keep = (
        "id",
        "name",
        "status",
        "channel",
        "urgency",
        "summary",
        "human_requested",
        "claim_id",
        "call_status",
        "call_answered",
    )
    seeded = [r for r in rows if not r.get("live")]
    return {
        "live_cases": [
            {
                **{k: r.get(k) for k in keep if r.get(k) is not None},
                "seconds_since_contact": _age(r, now),
            }
            for r in live[:MAX_ROWS_TO_MODEL]
        ],
        "other_cases_already_handled": {
            "count": len(seeded),
            "critical": sum(1 for r in seeded if r.get("urgency") == 4),
        },
    }


# ---------- planner ----------
class NemotronPlanner:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 12.0,
        thinking: bool = True,
    ) -> None:
        self.api_key = (api_key or os.getenv("NVIDIA_API_KEY") or "").strip()
        self.model = (
            model or os.getenv("NEMOTRON_AGENT_MODEL") or DEFAULT_AGENT_MODEL
        ).strip()
        self.timeout = timeout
        self.thinking = thinking
        self._http = httpx.AsyncClient(
            base_url=(os.getenv("NVIDIA_BASE_URL") or BASE_URL).strip().rstrip("/"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            transport=transport,
        )
        self.last: PlanResult | None = None

    async def plan(self, snapshot: Any) -> list[Action]:
        rows, now, nrs = _rows(snapshot)
        due = due_actions(rows, now, nrs)
        by_id = {r.get("id"): r for r in rows}
        t0 = time.monotonic()
        if not self.api_key:
            self.last = PlanResult(
                due,
                "NVIDIA_API_KEY not set; rules only.",
                0,
                "rules",
                True,
                error="no key",
            )
            return due
        if not due and not any(
            r.get("live")
            and r.get("status") in ("texted", "replied", "called", "unreachable")
            for r in rows
        ):
            self.last = PlanResult([], "Nothing open; waiting.", 0, "rules")
            return []
        try:
            reasoning, proposed = await self._ask(rows, now, nrs, due)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            ms = int((time.monotonic() - t0) * 1000)
            self.last = PlanResult(
                due,
                f"Planner unavailable ({type(e).__name__}); using rules.",
                ms,
                "rules",
                True,
                error=str(e)[:200],
            )
            return due
        actions, dropped = self._guard(proposed, due, by_id, now, nrs)
        ms = int((time.monotonic() - t0) * 1000)
        self.last = PlanResult(
            actions,
            reasoning,
            ms,
            self.model,
            any(a.source == "rule_fallback" for a in actions),
            dropped,
        )
        return actions

    async def _ask(
        self, rows: list[dict], now: datetime, nrs: int, due: list[Action]
    ) -> tuple[str, list[Action]]:
        payload = {
            "now": now.isoformat(timespec="seconds"),
            "no_reply_seconds": nrs,
            "due": [
                {
                    "tool": a.tool,
                    "policyholder_id": a.policyholder_id,
                    **a.args,
                    "why": a.why,
                }
                for a in due
            ],
            **_model_view(rows, now),
        }
        r = await self._http.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": PLANNER_SYSTEM},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.2,
                "max_tokens": 2500,
                "chat_template_kwargs": {"enable_thinking": self.thinking},
            },
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise ValueError(f"HTTP {r.status_code}: {r.text[:160]}")
        msg = r.json()["choices"][0]["message"]
        reasoning = (msg.get("reasoning_content") or msg.get("content") or "").strip()
        proposed: list[Action] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            if name == "wait" or not isinstance(args, dict):
                continue
            pid = str(args.pop("policyholder_id", "") or "")
            why = str(args.pop("why", "") or "")
            if (
                name in ("place_call", "send_imessage", "request_human", "draft_claim")
                and pid
            ):
                proposed.append(Action(name, pid, args, why, "nemotron"))
        return reasoning or "(no reasoning returned)", proposed

    def _guard(
        self,
        proposed: list[Action],
        due: list[Action],
        by_id: dict,
        now: datetime,
        nrs: int,
    ) -> tuple[list[Action], list[str]]:
        kept: list[Action] = []
        dropped: list[str] = []
        seen: set[tuple[str, str]] = set()
        busy: set[str] = set()  # one contact action (call/text) per person per tick
        for a in proposed:
            r = by_id.get(a.policyholder_id)
            key = (a.tool, a.policyholder_id)
            note = None
            if r is None:
                note = "unknown policyholder"
            elif key in seen:
                note = "duplicate"
            elif not r.get("live"):
                note = "not a live case"
            elif a.tool in ("place_call", "send_imessage") and (
                r.get("status") == "calling" or r.get("call_status") == "calling"
            ):
                note = "already on a call"
            elif (
                a.tool in ("place_call", "send_imessage") and a.policyholder_id in busy
            ):
                note = "already contacting this person this round"
            elif (
                a.tool == "place_call"
                and a.args.get("reason") == "no_reply"
                and (_age(r, now) or 0) < nrs
            ):
                note = f"too early for a no-reply call ({_age(r, now)}s < {nrs}s)"
            elif a.tool == "send_imessage":
                # SPEC coverage rule 3: no $ amount that isn't in the policy (no policy = none allowed).
                text, bad = validate_amounts(
                    str(a.args.get("text") or ""), r.get("policy") or {}
                )
                if not text:
                    note = "empty text"
                else:
                    a.args["text"] = text[:300]
                    if bad:
                        dropped.append(
                            f"send_imessage({a.policyholder_id}): removed unverified $ amount"
                        )
            elif a.tool == "request_human" and r.get("human_requested"):
                note = "human already requested"
            elif a.tool == "draft_claim" and r.get("claim_id"):
                note = "claim already drafted"
            if note:
                dropped.append(f"{a.tool}({a.policyholder_id}): {note}")
                continue
            seen.add(key)
            if a.tool in ("place_call", "send_imessage"):
                busy.add(a.policyholder_id)
            kept.append(a)
        for a in due:  # rules win when the model skipped something required
            key = (a.tool, a.policyholder_id)
            contact = a.tool in ("place_call", "send_imessage")
            if key in seen or (contact and a.policyholder_id in busy):
                continue
            a.source = "rule_fallback"
            kept.append(a)
            seen.add(key)
            if contact:
                busy.add(a.policyholder_id)
        order = {
            "request_human": 0,
            "place_call": 1,
            "send_imessage": 2,
            "draft_claim": 3,
        }
        kept.sort(
            key=lambda a: (
                order[a.tool],
                -((by_id.get(a.policyholder_id) or {}).get("urgency") or 0),
            )
        )
        if len(kept) > MAX_ACTIONS:
            dropped += [
                f"{a.tool}({a.policyholder_id}): over {MAX_ACTIONS} actions this round"
                for a in kept[MAX_ACTIONS:]
            ]
            kept = kept[:MAX_ACTIONS]
        return kept, dropped

    async def aclose(self) -> None:
        await self._http.aclose()
