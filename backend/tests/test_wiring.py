"""Regression tests for wiring the AI modules into the core (integration/mvp)."""

from __future__ import annotations

import asyncio

from app import runtime
from app.agent import planner_snapshot, to_core_action
from app.fallbacks import classify
from app.flow import Flow
from app.integrations import nemotron as nem
from app.integrations import planner as pl
from app.integrations.base import CallResult, CallTurn
from app.integrations.nemotron import as_dict, safety_floor
from app.models import Message, Triage
from tests.helpers import maria_case
from tests.test_behavior import run_async


def _flow() -> Flow:
    return object.__new__(Flow)  # _apply_triage needs no collaborators


def test_as_dict_on_stored_case_matches_spec_case_shape() -> None:
    case = maria_case()
    case.messages.append(
        Message(
            id="m1",
            ts="2026-10-27T12:00:00Z",
            from_="policyholder",
            channel="imessage",
            text="hi",
        )
    )
    d = as_dict(case)
    assert d["messages"][0]["from"] == "policyholder"
    assert "from_" not in d["messages"][0]
    assert d["policyholder"]["id"] == "ph_017"
    assert d["policyholder"]["address"].startswith("412 Harbor Dr")
    assert d["policy"]["deductible"] == 2500


def test_safety_floor_sees_policyholder_text_on_stored_case() -> None:
    case = maria_case()
    case.messages.append(
        Message(
            id="m1",
            ts="2026-10-27T12:00:00Z",
            from_="policyholder",
            channel="imessage",
            text="my mom is on oxygen and the power is out",
        )
    )
    level, _needs, reason = safety_floor(as_dict(case))
    assert level == 4 and reason


def test_urgency_four_is_sticky_and_keeps_needs() -> None:
    case, flow = maria_case(), _flow()
    flow._apply_triage(case, classify("water rising inside, mom on oxygen, power out"))
    assert case.urgency == 4
    before = list(case.triage.needs)
    flow._apply_triage(case, classify("we're okay now, just the roof", "call"))
    assert case.urgency == 4
    assert case.triage.label == "critical"
    assert case.triage.action == "Emergency"
    assert all(n in case.triage.needs for n in before)


def test_bare_digit_keeps_previous_summary_and_needs() -> None:
    case, flow = maria_case(), _flow()
    flow._apply_triage(case, classify("roof caved in, need a hotel"))
    summary, needs = case.summary, list(case.triage.needs)
    bare = Triage(
        urgency=4,
        label="critical",
        needs=[],
        summary="3",
        action="Emergency",
        source="imessage",
    )
    flow._apply_triage(case, bare)
    assert case.urgency == 4
    assert case.summary == summary != "3"
    assert case.triage.needs == needs


def test_urgency_can_still_rise_and_change_below_four() -> None:
    case, flow = maria_case(), _flow()
    flow._apply_triage(case, classify("all good, lost some branches"))
    flow._apply_triage(case, classify("roof caved in, need a hotel"))
    assert case.urgency == 3


# ---------- live-brain path (a stub shaped like NemotronBrain) ----------


class StubBrain:
    """Returns nemotron.py's own result models, like the real NemotronBrain."""

    def __init__(
        self, urgency: int = 3, question: str | None = None, fail: bool = False
    ):
        self.urgency, self.question, self.fail = urgency, question, fail
        self.last_floor_reason = None
        self.last_dropped: list[str] = []
        self.claims = 0

    async def triage(self, case):
        if self.fail:
            raise TimeoutError
        return nem.Triage(
            urgency=self.urgency,
            label=nem.URGENCY_LABEL[self.urgency],
            needs=["shelter"],
            summary="Roof damage, needs a hotel",
            action="Help arrange a hotel",
        )

    async def follow_up(self, case):
        if self.fail:
            raise TimeoutError
        return self.question

    async def draft_claim(self, case):
        self.claims += 1
        await asyncio.sleep(0.05)  # slow model: must not block the reply text
        return nem.ClaimDraft(
            claim_id="SF-4955-0017",
            policy_number="SF-HO-88213",
            date_of_loss="2026-10-27",
            cause_of_loss="Hurricane Isaias",
            loss_location="412 Harbor Dr",
            damages=[
                nem.Damage(
                    item="Roof",
                    description="leaking",
                    coverage="dwelling",
                    severity="moderate",
                )
            ],
            deductible=2500.0,
        )


def _use(monkeypatch, brain) -> None:
    assert runtime.flow is not None
    monkeypatch.setattr(runtime.flow, "brain", brain)
    monkeypatch.setattr(runtime.flow, "live_brain", True)


def _wait_claim(client, pid="ph_017", tries=50) -> dict:
    for _ in range(tries):
        run_async(client, lambda: asyncio.sleep(0.02))
        case = client.get(f"/cases/{pid}").json()
        if case["claim_draft"]:
            return case
    return client.get(f"/cases/{pid}").json()


def test_live_brain_triage_follow_up_and_background_claim(client, monkeypatch) -> None:
    _use(
        monkeypatch,
        StubBrain(
            urgency=3,
            question="Is anyone hurt? Your policy covers up to $18,000 for a hotel.",
        ),
    )
    client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "ph_017", "text": "2 roof is leaking"},
    )
    case = client.get("/cases/ph_017").json()
    assert (
        case["triage"]["urgency"] == 3
        and case["triage"]["summary"] == "Roof damage, needs a hotel"
    )
    assert any(
        "$18,000" in m["text"] for m in case["messages"]
    )  # follow-up even with details
    runtime.flow.brain.question = None  # model says: no more questions
    client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "ph_017", "text": "nobody hurt, need hotel"},
    )
    case = _wait_claim(client)
    assert case["claim_draft"]["deductible"] == 2500
    assert sum("Reply YES" in m["text"] for m in case["messages"]) == 1
    steps = client.get("/steps").json()["steps"]
    assert any("Nemotron triage" in s["text"] for s in steps)


def test_live_brain_failure_falls_back_to_heuristic(client, monkeypatch) -> None:
    _use(monkeypatch, StubBrain(fail=True))
    client.post("/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "2"})
    case = client.get("/cases/ph_017").json()
    assert case["triage"]["urgency"] == 2
    assert any("$18,000" in m["text"] for m in case["messages"])  # template follow-up
    steps = client.get("/steps").json()["steps"]
    assert any("heuristic used" in s["text"] for s in steps)


def test_live_brain_new_four_takes_emergency_path(client, monkeypatch) -> None:
    _use(monkeypatch, StubBrain(urgency=4))
    client.post(
        "/dev/simulate-reply",
        json={
            "policyholder_id": "ph_017",
            "text": "mom's oxygen machine stopped, the power is gone",
        },
    )
    case = client.get("/cases/ph_017").json()
    assert case["triage"]["urgency"] == 4
    assert case["human_request"]["reason"] == "Emergency"
    assert any(c["reason"] == "emergency" for c in case["calls"])


def test_confirmed_claim_is_not_redrafted(client) -> None:
    client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "ph_017", "text": "roof caved in, need hotel"},
    )
    client.post(
        "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "YES"}
    )
    store, flow = runtime.store, runtime.flow
    assert client.post("/policyholders/ph_017/call").status_code == 200
    call_id = store.cases["ph_017"].active_call_id

    async def finish():
        async with store.lock:
            await flow.resolve_call(
                store.cases["ph_017"],
                CallResult(
                    call_id=call_id,
                    status="done",
                    answered=True,
                    transcript=[CallTurn(role="user", text="also the fence is down")],
                ),
            )

    run_async(client, finish)
    case = client.get("/cases/ph_017").json()
    assert case["claim_draft"]["status"] == "confirmed"
    assert sum("Reply YES" in m["text"] for m in case["messages"]) == 1


def test_call_only_case_gets_no_imessages(client, monkeypatch) -> None:
    store = runtime.store
    monkeypatch.setattr(store.cases["ph_041"], "call_only", True)
    client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "ph_041", "text": "roof caved in, need hotel"},
    )
    case = client.get("/cases/ph_041").json()
    assert not any(
        m["from"] == "agent" and m["channel"] == "imessage"
        for m in case["messages"][-5:]
    )
    steps = client.get("/steps").json()["steps"]
    assert any(s["text"] == "Call-only line; text skipped" for s in steps)


def test_heuristic_catches_stuck_and_water_coming_in() -> None:
    assert classify("The water's coming in and we're stuck upstairs.").urgency == 4
    assert classify("car is stuck in the driveway mud").urgency < 4


# ---------- planner adapter ----------
def test_planner_snapshot_and_action_mapping(client) -> None:
    from app.timeutil import now

    snap = planner_snapshot(list(runtime.store.cases.values()), now())
    row = next(r for r in snap["policyholders"] if r["id"] == "ph_017")
    for key in (
        "followups_sent",
        "call_status",
        "call_answered",
        "call_reason",
        "call_attempts",
        "policy",
    ):
        assert key in row
    call = to_core_action(
        pl.Action("place_call", "ph_017", {"reason": "no_reply"}, "silent")
    )
    assert call.tool == "place_call" and call.reason == "no_reply"
    text = to_core_action(pl.Action("send_imessage", "ph_017", {"text": "hi"}))
    assert text.text == "hi"
    human = to_core_action(
        pl.Action("request_human", "ph_017", {"reason": "critical case"})
    )
    assert human.text == "critical case"
    assert to_core_action(pl.Action("send_imessage", "ph_017", {})) is None


class StubPlanner:
    def __init__(self, actions=None, fail=False):
        self.actions, self.fail, self.calls = actions or [], fail, 0
        self.last = None

    async def plan(self, snapshot):
        self.calls += 1
        if self.fail:
            raise TimeoutError
        self.last = pl.PlanResult(self.actions, "r", 5, "nemotron")
        return self.actions


def _tick(client, monkeypatch, planner) -> list[dict]:
    monkeypatch.setattr(runtime.agent, "nemotron", planner)
    run_async(client, runtime.agent.tick)
    return client.get("/steps").json()["steps"]


def test_nemotron_planner_drives_tick_and_rules_backfill(client, monkeypatch) -> None:
    monkeypatch.setenv("NO_REPLY_SECONDS", "0")
    client.post("/checkins/run", json={"disaster_number": 4955})
    planner = StubPlanner(
        [pl.Action("place_call", "ph_017", {"reason": "no_reply"}, "silent")]
    )
    steps = _tick(client, monkeypatch, planner)
    assert planner.calls == 1
    assert any(
        s["kind"] == "plan" and s["text"].startswith("Nemotron plan") for s in steps
    )
    calls = [s for s in steps if s["kind"] == "tool_call" and s["tool"] == "place_call"]
    assert {s["policyholder_id"] for s in calls} >= {
        "ph_017",
        "ph_041",
    }  # ph_041 from rules


def test_nemotron_planner_failure_uses_rules(client, monkeypatch) -> None:
    monkeypatch.setenv("NO_REPLY_SECONDS", "0")
    client.post("/checkins/run", json={"disaster_number": 4955})
    steps = _tick(client, monkeypatch, StubPlanner(fail=True))
    assert any("rules used" in s["text"] for s in steps)
    assert any(
        s["tool"] == "place_call" and s["policyholder_id"] == "ph_017" for s in steps
    )


def test_nemotron_planner_not_called_when_nothing_due(client, monkeypatch) -> None:
    planner = StubPlanner()
    _tick(client, monkeypatch, planner)
    assert planner.calls == 0
