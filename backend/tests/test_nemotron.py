"""Offline tests for NemotronBrain (no network: httpx.MockTransport fakes the NVIDIA API)."""

import asyncio
import json

import httpx
import pytest

from app.integrations.nemotron import (
    ClaimDraft,
    NemotronBrain,
    NemotronError,
    Triage,
    extract_json,
)

MARIA = {
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
        },
        {
            "id": "m_2",
            "ts": "2026-11-07T23:41:00Z",
            "from": "policyholder",
            "channel": "imessage",
            "text": "2",
        },
        {
            "id": "m_4",
            "ts": "2026-11-07T23:42:00Z",
            "from": "policyholder",
            "channel": "imessage",
            "text": "roof caved in, water in the living room, couch and tv ruined. yes need hotel",
        },
    ],
    "calls": [],
    "triage": None,
    "human_request": None,
    "claim_draft": None,
}


def brain_with(reply: dict | str, seen: list | None = None) -> NemotronBrain:
    content = reply if isinstance(reply, str) else json.dumps(reply)

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if seen is not None:
            seen.append(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return NemotronBrain(api_key="k", transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_every_call_disables_thinking_and_picks_the_right_model():
    seen: list = []
    b = brain_with(
        {"urgency": 4, "needs": ["medical"], "summary": "s", "action": "a"}, seen
    )
    run(b.triage(MARIA))
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "lightning" in seen[0]["model"]
    seen.clear()
    b2 = brain_with({"damages": []}, seen)
    run(b2.draft_claim(MARIA))
    assert (
        "super" in seen[0]["model"]
        and seen[0]["chat_template_kwargs"]["enable_thinking"] is False
    )


def test_triage_clamps_and_cleans():
    t = run(
        brain_with(
            {
                "urgency": 9,
                "needs": ["Medical", "shelter", "lasers", "none"],
                "summary": "Roof gone",
                "action": "Welfare check",
            }
        ).triage(MARIA)
    )
    assert isinstance(t, Triage)
    assert t.urgency == 4 and t.label == "critical"
    assert t.needs == ["medical", "shelter"]
    assert t.source == "imessage"


def test_triage_source_is_call_after_voice_turns():
    case = {
        **MARIA,
        "messages": MARIA["messages"]
        + [
            {
                "id": "c1",
                "from": "policyholder",
                "channel": "voice",
                "text": "mom is on oxygen",
            }
        ],
        "calls": [{"call_id": "conv_1", "status": "done"}],
    }
    t = run(
        brain_with({"urgency": 4, "needs": [], "summary": "s", "action": "a"}).triage(
            case
        )
    )
    assert t.source == "call"


def test_triage_bad_urgency_raises():
    with pytest.raises(NemotronError):
        run(brain_with({"urgency": "high", "summary": "s"}).triage(MARIA))


def test_follow_up_question_done_and_dedupe():
    q = run(
        brain_with(
            {
                "done": False,
                "question": "Is your home at 412 Harbor Dr damaged? Your policy covers up to $18,000 for a hotel.",
            }
        ).follow_up(MARIA)
    )
    assert "$18,000" in q
    assert (
        run(brain_with({"done": True, "question": "anything else?"}).follow_up(MARIA))
        is None
    )
    doubled = "Do you need a hotel tonight at all? " * 2
    assert (
        run(
            brain_with({"done": False, "question": doubled.strip()}).follow_up(MARIA)
        ).count("hotel")
        == 1
    )


def test_claim_uses_case_facts_and_drops_bad_rows():
    reply = {
        "cause_of_loss": "Hurricane Isaias wind and water",
        "policy_number": "WRONG-123",  # must be ignored
        "damages": [
            {
                "item": "Roof",
                "description": "Caved in",
                "coverage": "dwelling",
                "severity": "major",
            },
            {
                "item": "Couch and TV",
                "description": "Water damage",
                "coverage": "contents",
                "severity": "huge",
            },
            {
                "item": "Hotel",
                "description": "Needs a room",
                "coverage": "ale",
                "severity": "major",
            },
            {
                "item": "Boat",
                "description": "?",
                "coverage": "marine",
                "severity": "major",
            },
        ],
        "ale_requested": True,
        "injuries_or_medical": ["Mother on home oxygen"],
        "missing_info": ["Photos of damage"],
        "evidence": ["m_4", "made_up_id"],
    }
    c = run(brain_with(reply).draft_claim(MARIA))
    assert isinstance(c, ClaimDraft)
    assert c.claim_id == "SF-4955-0017" and c.status == "draft"
    assert c.policy_number == "SF-HO-88213" and c.deductible == 2500
    assert c.loss_location.startswith("412 Harbor Dr")
    assert [(d.item, d.coverage, d.severity) for d in c.damages] == [
        ("Roof", "dwelling", "major"),
        ("Couch and TV", "contents", "moderate"),
    ]
    assert c.ale_requested is True and c.evidence == ["m_4"]


def test_claim_keeps_existing_id_and_confirmed_status():
    case = {**MARIA, "claim_draft": {"claim_id": "SF-4955-0017", "status": "confirmed"}}
    c = run(brain_with({"damages": []}).draft_claim(case))
    assert c.status == "confirmed"


def test_extract_json_handles_fences_and_think():
    assert extract_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(NemotronError):
        extract_json("no json here")


def test_http_error_raises():
    b = NemotronBrain(
        api_key="k",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, text="rate limited")
        ),
    )
    with pytest.raises(NemotronError, match="429"):
        run(b.triage(MARIA))


def test_accepts_pydantic_case():
    from pydantic import BaseModel

    class Case(BaseModel):
        policyholder: dict
        policy: dict
        messages: list
        calls: list = []

    t = run(
        brain_with(
            {"urgency": 2, "needs": ["repairs"], "summary": "s", "action": "a"}
        ).triage(Case(**{k: MARIA[k] for k in ("policyholder", "policy", "messages")}))
    )
    assert t.urgency == 2


def test_follow_up_uses_big_model_and_gets_ale_limit():
    seen: list = []
    b = brain_with({"done": False, "question": "What is damaged?"}, seen)
    run(b.follow_up(MARIA))
    assert "super" in seen[0]["model"]
    assert json.loads(seen[0]["messages"][1]["content"])["ale_limit"] == "$18,000"


def test_safety_floor_raises_urgency():
    oxygen = {
        **MARIA,
        "messages": MARIA["messages"]
        + [
            {
                "id": "v1",
                "from": "policyholder",
                "channel": "voice",
                "text": "My mom is on oxygen and the power is out.",
            }
        ],
    }
    b = brain_with({"urgency": 3, "needs": ["shelter"], "summary": "s", "action": "a"})
    t = run(b.triage(oxygen))
    assert t.urgency == 4 and "medical" in t.needs and b.last_floor_reason


def test_safety_floor_ignores_negations_and_bare_menu_is_2():
    from app.integrations.nemotron import safety_floor

    ok = {
        "policy": {},
        "messages": [{"from": "policyholder", "text": "fence down, nobody is hurt"}],
    }
    assert safety_floor(ok)[0] == 1
    trapped = {
        "policy": {},
        "messages": [{"from": "policyholder", "text": "we are trapped upstairs"}],
    }
    assert safety_floor(trapped)[0] == 4
    bare = {**MARIA, "messages": [MARIA["messages"][0], MARIA["messages"][1]]}
    t = run(
        brain_with({"urgency": 3, "needs": [], "summary": "s", "action": "a"}).triage(
            bare
        )
    )
    assert t.urgency == 2


def test_critical_never_downgrades_automatically():
    case = {
        **MARIA,
        "triage": {
            "urgency": 4,
            "needs": ["medical", "power"],
            "summary": "s",
            "action": "a",
        },
        "messages": MARIA["messages"]
        + [
            {
                "id": "m_9",
                "from": "policyholder",
                "channel": "imessage",
                "text": "power is back, we are ok now",
            }
        ],
    }
    b = brain_with(
        {
            "urgency": 2,
            "needs": ["repairs"],
            "summary": "Power restored",
            "action": "Check in later",
        }
    )
    t = run(b.triage(case))
    assert t.urgency == 4 and t.label == "critical"
    assert {"medical", "power", "repairs"} <= set(t.needs)
    assert "stays critical" in b.last_floor_reason
    # a 3 can still go down
    t3 = run(
        brain_with({"urgency": 2, "needs": [], "summary": "s", "action": "a"}).triage(
            {**case, "triage": {"urgency": 3}}
        )
    )
    assert t3.urgency == 2


# ---------- SPEC "Policy coverage" ----------
def test_check_coverage_maria_roof_and_renters_roof():
    from app.integrations.nemotron import check_coverage

    r = check_coverage(MARIA, "roof")
    assert (r["coverage"], r["covered"], r["limit"], r["deductible"]) == (
        "dwelling",
        True,
        320000,
        2500,
    )
    renters = {
        **MARIA,
        "policy": {
            **MARIA["policy"],
            "type": "renters",
            "coverages": {"contents": 30000, "ale": 6000},
        },
    }
    r2 = check_coverage(renters, "roof")
    assert r2["covered"] is False and "landlord" in r2["reason"]
    assert check_coverage(MARIA, "couch")["coverage"] == "contents"
    assert check_coverage(MARIA, "need a hotel")["limit"] == 18000


def test_validate_amounts_strips_wrong_dollar_sentence():
    from app.integrations.nemotron import validate_amounts

    text, dropped = validate_amounts(
        "Your policy covers up to $25,000 for a hotel. Do you need a place tonight?",
        MARIA["policy"],
    )
    assert text == "Do you need a place tonight?" and len(dropped) == 1
    ok, none = validate_amounts(
        "Your policy covers up to $18,000 for a hotel.", MARIA["policy"]
    )
    assert none == [] and "$18,000" in ok


def test_follow_up_strips_hallucinated_amount_and_sends_answered_hints():
    seen: list = []
    b = brain_with(
        {
            "done": False,
            "question": "Your policy covers $50,000 for a hotel. Is anyone hurt?",
        },
        seen,
    )
    q = run(b.follow_up(MARIA))
    assert q == "Is anyone hurt?" and b.last_dropped
    sent = json.loads(seen[0]["messages"][1]["content"])
    assert (
        "shelter" in sent["already_answered"] and "damage" in sent["already_answered"]
    )


def test_claim_coverage_comes_from_code_and_uncovered_goes_to_review():
    renters = {
        **MARIA,
        "policy": {
            **MARIA["policy"],
            "type": "renters",
            "covered_property": [],
            "coverages": {"contents": 30000},
        },
    }
    reply = {
        "damages": [
            {
                "item": "Roof",
                "description": "Caved in",
                "coverage": "contents",
                "severity": "major",
            },  # wrong label
            {
                "item": "TV",
                "description": "Water damage",
                "coverage": "dwelling",
                "severity": "moderate",
            },  # wrong label
        ],
        "ale_requested": True,
        "missing_info": ["Photos"],
    }
    c = run(brain_with(reply).draft_claim(renters))
    assert [(d.item, d.coverage) for d in c.damages] == [("TV", "contents")]
    assert (
        "Coverage review: Roof" in c.missing_info
        and "Coverage review: temporary housing" in c.missing_info
    )
    assert c.ale_requested is False
    assert not any("denied" in m.lower() for m in c.missing_info)


def test_follow_up_done_leaves_no_dropped():
    b = brain_with({"done": True, "question": ""})
    assert run(b.follow_up(MARIA)) is None and b.last_dropped == []


def test_actions_are_recommendations_never_dispatch():
    from app.integrations.nemotron import recommend_only

    assert (
        recommend_only("Dispatch emergency medical assistance immediately")
        == "Recommend emergency medical assistance immediately"
    )
    assert recommend_only("Send an ambulance") == "Welfare check recommended"
    assert recommend_only("Welfare check recommended") == "Welfare check recommended"
    t = run(
        brain_with(
            {
                "urgency": 4,
                "needs": ["medical"],
                "summary": "s",
                "action": "Dispatch rescue team",
            }
        ).triage(MARIA)
    )
    assert "dispatch" not in t.action.lower()


def test_floor_collects_all_needs_and_replaces_closing_action():
    from app.integrations.nemotron import safety_floor

    case = {
        "policy": {},
        "messages": [
            {
                "from": "policyholder",
                "text": "my husband fell and he's bleeding, we're stuck upstairs",
            }
        ],
    }
    u, needs, why = safety_floor(case)
    assert (
        u == 4
        and set(needs) == {"rescue", "medical"}
        and "stuck" in why
        and "bleeding" in why
    )
    t = run(
        brain_with(
            {
                "urgency": 1,
                "needs": [],
                "summary": "says fine",
                "action": "Confirm safety and close case",
            }
        ).triage({**MARIA, **case, "policy": MARIA["policy"]})
    )
    assert t.urgency == 4 and t.action == "Welfare check recommended"
