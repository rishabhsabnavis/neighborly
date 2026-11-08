"""Live Brain: triage, policy-aware follow-ups and claim drafts with NVIDIA Nemotron.

Implements the Brain interface from docs/BACKEND_PROMPT.md:
    async triage(case) -> Triage
    async follow_up(case) -> str | None      (None = no more questions needed)
    async draft_claim(case) -> ClaimDraft

Facts this relies on (spikes/nemotron_claim.py, docs/CONTEXT.md):
- The API is OpenAI-compatible at https://integrate.api.nvidia.com/v1, and one key works for all models.
- Reasoning is ON by default and eats max_tokens, so content comes back empty. Every call
  here sends chat_template_kwargs.enable_thinking=False.
- Lightning (fast, ~0.5s) handles triage and follow-ups. Super handles claims (3-10s).
  NOTE for the core: draft_claim can take up to ~10s, so give it a 15s timeout, not 10s.
- Facts we already know (policy number, deductible, claim id) are filled in from the case,
  not trusted from the model.

`case` may be a Pydantic model or a dict shaped like SPEC's GET /cases/{id} response.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_AGENT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
DEFAULT_TRIAGE_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"

URGENCY_LABEL = {1: "safe", 2: "moderate", 3: "high", 4: "critical"}
COVERAGES = {"dwelling", "contents", "auto", "ale"}
NEEDS = {
    "medical",
    "shelter",
    "power",
    "water",
    "food",
    "medication",
    "transport",
    "rescue",
    "repairs",
    "none",
}


# ---------- result models (field names exactly as in SPEC "Data contracts") ----------
class Triage(BaseModel):
    urgency: int = Field(ge=1, le=4)
    label: str
    needs: list[str] = []
    summary: str
    action: str
    source: Literal["imessage", "call", "seed"] = "imessage"


class Damage(BaseModel):
    item: str
    description: str
    coverage: Literal["dwelling", "contents", "auto", "ale"]
    severity: Literal["minor", "moderate", "major"]


class ClaimDraft(BaseModel):
    claim_id: str
    status: Literal["draft", "confirmed"] = "draft"
    policy_number: str
    date_of_loss: str
    cause_of_loss: str
    loss_location: str
    damages: list[Damage] = []
    ale_requested: bool = False
    injuries_or_medical: list[str] = []
    deductible: float | int | None = None
    missing_info: list[str] = []
    evidence: list[str] = []


class NemotronError(RuntimeError):
    pass


# ---------- prompts ----------
TRIAGE_SYSTEM = """You triage State Farm policyholders after a hurricane. Read the case JSON (policy,
household notes, texts, call transcripts) and judge how urgently this person needs help NOW.
Urgency:
4 = life safety at risk: trapped, injured, water rising inside, someone on oxygen/medical equipment WITHOUT
    power, chose "3" (emergency). Over-triage rather than under-triage at this level.
3 = serious but not life-threatening: major home damage, home unlivable, needs shelter tonight.
2 = needs help but stable: moderate damage, needs repairs or supplies, or said "2" with no details yet.
1 = safe, no help needed.
Base urgency ONLY on problems the person actually reported. Household notes (elderly, medical needs) raise
urgency only when combined with a reported problem; never invent a problem from the notes.
Speech-to-text in call transcripts is noisy: ignore words that make no sense in context.
Output ONLY JSON: {"urgency": 1-4, "needs": [from: medical, shelter, power, water, food, medication,
transport, rescue, repairs, none], "summary": "<= 20 words, only reported facts, no name",
"action": "<= 12 words, what State Farm should do next"}"""

FOLLOWUP_SYSTEM = """You are State Farm's catastrophe check-in agent texting a policyholder over iMessage
after a hurricane. Write the next follow-up text. Go down this list and ask about the FIRST item the person
has NOT already answered anywhere in their texts or call transcripts:
1. Damage: what is damaged at their covered home (say the street address) or covered vehicle. If ale_limit is
   given, in the SAME text say their policy covers up to <ale_limit> for a hotel or temporary housing and ask
   if they need a place to stay tonight.
2. Safety: is anyone hurt or trapped; if household notes mention medical equipment (e.g. oxygen), ask about it
   specifically.
3. Shelter (only if still unanswered): do they need a place to stay tonight (mention ale_limit if given).
Something counts as answered if they said it at all ("need hotel" answers shelter; "roof caved in" answers damage).
If all three are answered, set done to true.
Rules: under 280 characters, plain warm words, no emoji, no greeting name repeated every time, max 2 questions.
Output ONLY JSON: {"done": true|false, "question": "<the text>"}"""

CLAIM_SYSTEM = """You are a State Farm catastrophe claims assistant. Write a FIRST NOTICE OF LOSS claim draft
from the case JSON. Use ONLY facts stated in the messages or call transcripts. Never invent damage, items,
injuries or amounts. Map each damage to one coverage: dwelling (the structure: roof, walls, floors, water
inside the home), contents (belongings: furniture, electronics, clothing), auto (a covered vehicle, only if
its damage was described), ale (only via ale_requested, never as a damage). List what an adjuster still
needs in missing_info (photos, estimates, dates, unknowns). evidence = the ids of messages/calls the facts
came from. Output ONLY JSON:
{"cause_of_loss": str, "damages": [{"item": str, "description": str, "coverage": "dwelling|contents|auto",
"severity": "minor|moderate|major"}], "ale_requested": bool, "injuries_or_medical": [str],
"missing_info": [str], "evidence": [str]}"""


# ---------- helpers ----------
def as_dict(case: Any) -> dict:
    if isinstance(case, dict):
        return case
    dump = getattr(case, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    raise TypeError(f"case must be a dict or Pydantic model, got {type(case).__name__}")


def compact_case(case: dict) -> dict:
    """Only the parts the model needs (keeps prompts small and fast)."""
    calls = []
    for c in case.get("calls") or []:
        entry = {
            k: c.get(k)
            for k in ("call_id", "reason", "status", "transcript_summary")
            if c.get(k)
        }
        if c.get("transcript"):
            entry["transcript"] = c["transcript"]
        calls.append(entry)
    return {
        "policyholder": case.get("policyholder"),
        "policy": case.get("policy"),
        "disaster": case.get("disaster")
        or {"number": 4955, "name": "Hurricane Isaias", "state": "FL"},
        "messages": [
            {
                k: m.get(k)
                for k in ("id", "from", "channel", "text")
                if m.get(k) is not None
            }
            for m in (case.get("messages") or [])
        ],
        "calls": calls,
    }


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise NemotronError(f"no JSON in model output: {text[:120]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise NemotronError(f"bad JSON from model: {e}") from e


def _latest_source(case: dict) -> Literal["imessage", "call"]:
    """Where the newest policyholder information came from: a call or a text."""
    calls_done = any(c.get("status") == "done" for c in case.get("calls") or [])
    for m in reversed(case.get("messages") or []):
        if (
            m.get("from") in ("policyholder", "voice_agent")
            or m.get("channel") == "voice"
        ):
            return "call" if m.get("channel") == "voice" else "imessage"
    return "call" if calls_done else "imessage"


def claim_id_for(case: dict) -> str:
    ph_id = (case.get("policyholder") or {}).get("id") or "ph_000"
    num = re.sub(r"\D", "", ph_id)[-4:].zfill(4)
    disaster = (case.get("disaster") or {}).get("number", 4955)
    return f"SF-{disaster}-{num}"


# ---------- safety floor (deterministic; the model may under-triage life safety) ----------
_NEGATIONS = re.compile(
    r"\b(no ?one|nobody|not|isn'?t|aren'?t|wasn'?t|no)\s+(is\s+|are\s+|was\s+|got\s+)?"
    r"(hurt|injured|trapped|stuck|bleeding)\b",
    re.IGNORECASE,
)
_LIFE_SAFETY = [
    (
        re.compile(
            r"\b(trapped|stuck|can'?t get out|cannot get out|on the roof|in the attic)\b",
            re.IGNORECASE,
        ),
        "rescue",
    ),
    (
        re.compile(
            r"\bwater\b.{0,25}\b(rising|coming in|up to|inside)\b|\bflood(ing|ed)? (inside|the house)",
            re.IGNORECASE,
        ),
        "rescue",
    ),
    (
        re.compile(
            r"\b(injur\w*|bleeding|hurt|unconscious|not breathing|can'?t breathe|chest pain|broken (leg|arm|bone))\b",
            re.IGNORECASE,
        ),
        "medical",
    ),
]
_DEVICE = re.compile(
    r"\b(oxygen|ventilator|dialysis|cpap|insulin|wheelchair|medical equipment)\b",
    re.IGNORECASE,
)
_NO_POWER = re.compile(
    r"\b(no power|power('?s| is)? (out|off|gone)|lost power|no electricity|without power)\b",
    re.IGNORECASE,
)


def safety_floor(case: dict) -> tuple[int, list[str], str | None]:
    """Minimum urgency from what the policyholder said: (min_urgency, extra_needs, reason)."""
    said = " ".join(
        str(m.get("text") or "")
        for m in case.get("messages") or []
        if m.get("from") == "policyholder"
    )
    menu = [
        str(m.get("text") or "").strip()
        for m in case.get("messages") or []
        if m.get("from") == "policyholder"
        and m.get("channel", "imessage") == "imessage"
    ]
    notes = " ".join(
        str(n)
        for n in ((case.get("policy") or {}).get("household") or {}).get("notes") or []
    )
    clean = _NEGATIONS.sub(" ", said)
    for pat, need in _LIFE_SAFETY:
        if pat.search(clean):
            return 4, [need], f"reported: {pat.search(clean).group(0)!r}"
    if _NO_POWER.search(said) and (_DEVICE.search(said) or _DEVICE.search(notes)):
        return 4, ["medical", "power"], "medical equipment without power"
    if "3" in menu:
        return 4, [], "chose 3 (emergency)"
    return 1, [], None


def ale_limit_text(case: dict) -> str | None:
    ale = ((case.get("policy") or {}).get("coverages") or {}).get("ale")
    try:
        return f"${int(ale):,}" if ale else None
    except (TypeError, ValueError):
        return None


# ---------- the Brain ----------
class NemotronBrain:
    def __init__(
        self,
        api_key: str | None = None,
        agent_model: str | None = None,
        triage_model: str | None = None,
        followup_model: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("NVIDIA_API_KEY") or "").strip()
        if not self.api_key:
            raise NemotronError("NVIDIA_API_KEY not set")
        self.agent_model = (
            agent_model or os.getenv("NEMOTRON_AGENT_MODEL") or DEFAULT_AGENT_MODEL
        ).strip()
        self.triage_model = (
            triage_model or os.getenv("NEMOTRON_TRIAGE_MODEL") or DEFAULT_TRIAGE_MODEL
        ).strip()
        # Follow-ups use the big model: in live tests lightning kept asking things the person had
        # already answered; super followed the question order every time at ~0.6-1.7s.
        self.followup_model = (
            followup_model or os.getenv("NEMOTRON_FOLLOWUP_MODEL") or self.agent_model
        ).strip()
        self._http = httpx.AsyncClient(
            base_url=(base_url or os.getenv("NVIDIA_BASE_URL") or BASE_URL)
            .strip()
            .rstrip("/"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            transport=transport,
        )
        self.last_ms: int | None = None  # latency of the last call, for the step log
        self.last_floor_reason: str | None = (
            None  # set when the safety floor raised urgency
        )

    async def _chat(
        self, model: str, system: str, user: str, max_tokens: int, timeout: float
    ) -> dict:
        t0 = time.monotonic()
        r = await self._http.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=timeout,
        )
        self.last_ms = int((time.monotonic() - t0) * 1000)
        if r.status_code >= 400:
            raise NemotronError(f"HTTP {r.status_code}: {r.text[:200]}")
        content = (r.json().get("choices") or [{}])[0].get("message", {}).get(
            "content"
        ) or ""
        return extract_json(content)

    async def triage(self, case: Any) -> Triage:
        c = as_dict(case)
        d = await self._chat(
            self.triage_model, TRIAGE_SYSTEM, json.dumps(compact_case(c)), 400, 8.0
        )
        try:
            urgency = max(1, min(4, int(d.get("urgency"))))
        except (TypeError, ValueError) as e:
            raise NemotronError(f"bad urgency: {d.get('urgency')!r}") from e
        needs = [
            n
            for n in (str(x).lower().strip() for x in d.get("needs") or [])
            if n in NEEDS and n != "none"
        ]
        # A bare menu reply ("2") with no details yet is "needs help, stable" until we learn more.
        said = [
            str(m.get("text") or "").strip()
            for m in c.get("messages") or []
            if m.get("from") == "policyholder"
        ]
        if said and all(t in {"0", "2", "4"} for t in said):
            urgency = 2
        floor, extra, self.last_floor_reason = safety_floor(c)
        if floor > urgency:
            urgency = floor
            needs = needs + [n for n in extra if n not in needs]
        else:
            self.last_floor_reason = None
        # A 4 never goes down automatically (docs/CONTEXT.md "Danger (urgency) levels"):
        # only a person in the console clears it, so keep it and any needs already recorded.
        prev = c.get("triage") or {}
        if prev.get("urgency") == 4 and urgency < 4:
            urgency = 4
            needs = needs + [n for n in prev.get("needs") or [] if n not in needs]
            self.last_floor_reason = "stays critical: urgency 4 only clears by a person"
        return Triage(
            urgency=urgency,
            label=URGENCY_LABEL[urgency],
            needs=needs,
            summary=str(d.get("summary") or "").strip()[:200] or "No details yet",
            action=str(d.get("action") or "").strip()[:120] or "Follow up",
            source=_latest_source(c),
        )

    async def follow_up(self, case: Any) -> str | None:
        c = as_dict(case)
        payload = {**compact_case(c), "ale_limit": ale_limit_text(c)}
        d = await self._chat(
            self.followup_model, FOLLOWUP_SYSTEM, json.dumps(payload), 300, 6.0
        )
        q = str(d.get("question") or "").strip()
        if d.get("done") is True or not q:
            return None
        # Guard against the model repeating itself (seen once in the spike).
        half = len(q) // 2
        if len(q) > 40 and q[:half].strip() == q[half:].strip():
            q = q[:half].strip()
        return q[:300]

    async def draft_claim(self, case: Any) -> ClaimDraft:
        c = as_dict(case)
        d = await self._chat(
            self.agent_model, CLAIM_SYSTEM, json.dumps(compact_case(c)), 1500, 15.0
        )
        policy = c.get("policy") or {}
        ph = c.get("policyholder") or {}
        disaster = c.get("disaster") or {}
        known_ids = {m.get("id") for m in c.get("messages") or []} | {
            k.get("call_id") for k in c.get("calls") or []
        }
        damages = []
        for x in d.get("damages") or []:
            cov = str(x.get("coverage", "")).lower()
            if cov not in COVERAGES or cov == "ale":
                continue
            sev = str(x.get("severity", "moderate")).lower()
            try:
                damages.append(
                    Damage(
                        item=str(x.get("item", "")).strip()[:60] or "Unspecified",
                        description=str(x.get("description", "")).strip()[:160],
                        coverage=cov,
                        severity=sev
                        if sev in {"minor", "moderate", "major"}
                        else "moderate",
                    )
                )
            except ValidationError:
                continue
        existing = c.get("claim_draft") or {}
        try:
            return ClaimDraft(
                claim_id=existing.get("claim_id") or claim_id_for(c),
                status=existing.get("status") or "draft",
                policy_number=policy.get("number") or "",
                date_of_loss=disaster.get("declared")
                or disaster.get("date_of_loss")
                or "2026-10-27",
                cause_of_loss=str(d.get("cause_of_loss") or "").strip()
                or f"{disaster.get('name', 'Hurricane Isaias')} (FEMA-{disaster.get('number', 4955)})",
                loss_location=ph.get("address") or "",
                damages=damages,
                ale_requested=bool(d.get("ale_requested")),
                injuries_or_medical=[
                    str(x) for x in d.get("injuries_or_medical") or []
                ][:6],
                deductible=policy.get("deductible"),
                missing_info=[str(x) for x in d.get("missing_info") or []][:8],
                evidence=[str(e) for e in d.get("evidence") or [] if e in known_ids],
            )
        except ValidationError as e:
            raise NemotronError(
                f"claim draft failed validation: {e.errors()[:2]}"
            ) from e

    async def aclose(self) -> None:
        await self._http.aclose()
