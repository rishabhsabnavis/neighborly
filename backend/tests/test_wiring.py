"""Regression tests for wiring the AI modules into the core (integration/mvp)."""

from __future__ import annotations

from app.fallbacks import classify
from app.flow import Flow
from app.integrations.nemotron import as_dict, safety_floor
from app.models import Message, Triage
from tests.helpers import maria_case


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
