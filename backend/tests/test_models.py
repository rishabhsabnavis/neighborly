from __future__ import annotations

from app.models import (
    CallStartResponse,
    CaseResponse,
    CheckinRunResponse,
    ClaimDraft,
    Coverages,
    DashboardResponse,
    HealthResponse,
    StepsResponse,
)


def test_spec_payloads_validate() -> None:
    """Concrete values for the enums the SPEC page writes as `a|b|c`."""

    health = HealthResponse.model_validate({"status": "ok"})
    assert health.status == "ok"

    run = CheckinRunResponse.model_validate(
        {"run_id": "run_01", "queued": 42, "live": 2}
    )
    assert run.queued == 42 and run.live == 2

    dashboard = DashboardResponse.model_validate(
        {
            "disaster": {
                "number": 4955,
                "name": "Hurricane Isaias",
                "state": "FL",
                "counties": ["Bay", "Gulf"],
            },
            "counts": {
                "total": 42,
                "safe": 20,
                "needs_help": 9,
                "critical": 3,
                "no_response": 8,
                "calling": 1,
                "human_requested": 2,
                "claims_drafted": 11,
            },
            "policyholders": [
                {
                    "id": "ph_017",
                    "name": "Maria Lopez",
                    "phone_masked": "***-***-4410",
                    "county": "Bay",
                    "lat": 30.16,
                    "lng": -85.66,
                    "live": True,
                    "status": "replied",
                    "channel": "imessage",
                    "human_requested": False,
                    "urgency": 4,
                    "summary": "Roof caved in, water inside, mother on oxygen, no power",
                    "claim_id": "SF-4955-0017",
                    "last_contact_at": "2026-11-07T23:41:02Z",
                }
            ],
        }
    )
    row = dashboard.policyholders[0]
    assert row.id == "ph_017"
    assert row.urgency == 4

    case = CaseResponse.model_validate(
        {
            "policyholder": {
                "id": "ph_017",
                "name": "Maria Lopez",
                "address": "412 Harbor Dr, Panama City, FL",
                "county": "Bay",
            },
            "policy": {
                "number": "SF-HO-88213",
                "type": "homeowners",
                "covered_property": ["Dwelling: 412 Harbor Dr", "2019 Toyota Camry"],
                "coverages": {"dwelling": 320000, "contents": 160000, "ale": 18000},
                "deductible": 2500,
                "household": {"size": 3, "notes": ["Mother, 74, home oxygen"]},
            },
            "messages": [
                {
                    "id": "m_1",
                    "ts": "2026-11-07T23:40:00Z",
                    "from": "agent",
                    "channel": "imessage",
                    "text": "Reply 1 Safe, 2 Need help...",
                }
            ],
            "calls": [
                {
                    "call_id": "conv_abc",
                    "reason": "requested",
                    "status": "done",
                    "duration_s": 74,
                    "transcript_summary": "Roof collapse.",
                }
            ],
            "triage": {
                "urgency": 4,
                "label": "critical",
                "needs": ["medical", "shelter", "power"],
                "summary": "Roof caved in, mother on oxygen",
                "action": "Welfare check; book ALE hotel",
                "source": "imessage",
            },
            "human_request": {
                "requested": True,
                "reason": "Asked for a person on the call",
                "ts": "2026-11-07T23:45:10Z",
            },
            "claim_draft": {
                "claim_id": "SF-4955-0017",
                "status": "draft",
                "policy_number": "SF-HO-88213",
                "date_of_loss": "2026-10-27",
                "cause_of_loss": "Hurricane Isaias (FEMA-4955): wind + water",
                "loss_location": "412 Harbor Dr, Panama City, FL",
                "damages": [
                    {
                        "item": "Roof",
                        "description": "Caved in",
                        "coverage": "dwelling",
                        "severity": "major",
                    },
                    {
                        "item": "Living room contents",
                        "description": "Water intrusion",
                        "coverage": "contents",
                        "severity": "moderate",
                    },
                ],
                "ale_requested": True,
                "injuries_or_medical": ["Mother on home oxygen, power out"],
                "deductible": 2500,
                "missing_info": ["Photos of damage", "Estimated repair cost"],
                "evidence": ["m_4", "conv_abc"],
            },
        }
    )
    dumped = case.model_dump(by_alias=True)
    assert dumped["messages"][0]["from"] == "agent"
    assert dumped["policy"]["coverages"] == {
        "dwelling": 320000,
        "contents": 160000,
        "ale": 18000,
    }
    ClaimDraft.model_validate(dumped["claim_draft"])
    started = CallStartResponse.model_validate(
        {"call_id": "conv_abc", "status": "calling"}
    )
    assert started.status == "calling"
    steps = StepsResponse.model_validate(
        {
            "steps": [
                {
                    "id": 57,
                    "ts": "2026-11-07T23:42:10Z",
                    "kind": "tool_call",
                    "policyholder_id": "ph_017",
                    "tool": "place_call",
                    "text": "Replied 4 -> calling with case context",
                    "ms": 812,
                }
            ]
        }
    )
    assert steps.steps[0].tool == "place_call"


def test_coverages_omit_missing_keys() -> None:
    dumped = Coverages(contents=40000, ale=8000).model_dump()
    assert "dwelling" not in dumped
    assert dumped["contents"] == 40000
