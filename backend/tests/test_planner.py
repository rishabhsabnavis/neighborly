"""Offline tests for the hybrid Nemotron planner (httpx.MockTransport fakes the NVIDIA API)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.planner import NemotronPlanner, due_actions

NOW = datetime(2026, 11, 8, 6, 0, 0, tzinfo=UTC)


def ago(s: int) -> str:
    return (NOW - timedelta(seconds=s)).isoformat()


def snap(rows):
    return {"now": NOW.isoformat(), "no_reply_seconds": 60, "policyholders": rows}


MARIA = {
    "id": "ph_017",
    "name": "Maria Lopez",
    "status": "replied",
    "live": True,
    "urgency": 4,
    "human_requested": False,
    "claim_id": None,
    "last_contact_at": ago(10),
}
SILENT = {
    "id": "ph_041",
    "name": "James Reed",
    "status": "texted",
    "live": True,
    "urgency": None,
    "human_requested": False,
    "claim_id": None,
    "last_contact_at": ago(95),
}
SEEDED = {
    "id": "ph_003",
    "name": "Seed Person",
    "status": "replied",
    "live": False,
    "urgency": 4,
    "human_requested": False,
    "claim_id": None,
    "last_contact_at": ago(900),
}


def planner_replying(
    tool_calls, reasoning="Maria is critical; James is silent.", seen=None, status=200
):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(req.content))
        if status != 200:
            return httpx.Response(status, text="boom")
        calls = [
            {
                "id": f"c{i}",
                "type": "function",
                "function": {"name": n, "arguments": json.dumps(a)},
            }
            for i, (n, a) in enumerate(tool_calls)
        ]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": reasoning,
                            "tool_calls": calls,
                        }
                    }
                ]
            },
        )

    return NemotronPlanner(api_key="k", transport=httpx.MockTransport(handler))


def run(c):
    return asyncio.run(c)


def test_rules_due_only_for_live_cases():
    due = due_actions([MARIA, SILENT, SEEDED], NOW, 60)
    got = {(a.tool, a.policyholder_id) for a in due}
    assert ("place_call", "ph_041") in got
    assert ("request_human", "ph_017") in got and ("draft_claim", "ph_017") in got
    assert not any(pid == "ph_003" for _, pid in got)


def test_no_reply_call_waits_for_threshold():
    young = {**SILENT, "last_contact_at": ago(30)}
    assert not any(a.tool == "place_call" for a in due_actions([young], NOW, 60))


def test_model_actions_kept_reasoning_recorded_and_thinking_on():
    seen: list = []
    p = planner_replying(
        [
            (
                "request_human",
                {"policyholder_id": "ph_017", "reason": "oxygen, no power"},
            ),
            (
                "place_call",
                {
                    "policyholder_id": "ph_041",
                    "reason": "no_reply",
                    "why": "silent 95s",
                },
            ),
            ("draft_claim", {"policyholder_id": "ph_017"}),
        ],
        seen=seen,
    )
    acts = run(p.plan(snap([MARIA, SILENT, SEEDED])))
    assert [(a.tool, a.policyholder_id, a.source) for a in acts] == [
        ("request_human", "ph_017", "nemotron"),
        ("place_call", "ph_041", "nemotron"),
        ("draft_claim", "ph_017", "nemotron"),
    ]
    assert p.last.reasoning.startswith("Maria is critical") and not p.last.used_fallback
    assert (
        p.last.log_text().startswith("Nemotron plan")
        and "silent 95s" in p.last.log_text()
    )
    body = seen[0]
    assert body["chat_template_kwargs"]["enable_thinking"] is True and body["tools"]
    sent = json.loads(body["messages"][1]["content"])
    assert [c["id"] for c in sent["live_cases"]] == [
        "ph_017",
        "ph_041",
    ]  # seeded not sent
    assert sent["other_cases_already_handled"]["count"] == 1


def test_guardrails_drop_bad_actions_and_rules_fill_gaps():
    calling = {**MARIA, "id": "ph_050", "status": "calling", "urgency": 3}
    p = planner_replying(
        [
            (
                "place_call",
                {"policyholder_id": "ph_003", "reason": "no_reply"},
            ),  # seeded
            (
                "place_call",
                {"policyholder_id": "ph_050", "reason": "requested"},
            ),  # on a call
            (
                "place_call",
                {"policyholder_id": "ph_999", "reason": "requested"},
            ),  # unknown
            ("send_imessage", {"policyholder_id": "ph_017", "text": "  "}),  # empty
        ]
    )
    acts = run(p.plan(snap([MARIA, SILENT, SEEDED, calling])))
    got = [(a.tool, a.policyholder_id, a.source) for a in acts]
    # model skipped the required call to James and Maria's human request: rules add them back
    assert ("place_call", "ph_041", "rule_fallback") in got
    assert ("request_human", "ph_017", "rule_fallback") in got
    assert not any(pid in ("ph_003", "ph_050", "ph_999") for _, pid, _ in got)
    assert len(p.last.dropped) == 4 and p.last.used_fallback


def test_early_no_reply_call_is_dropped():
    young = {**SILENT, "last_contact_at": ago(20)}
    p = planner_replying(
        [("place_call", {"policyholder_id": "ph_041", "reason": "no_reply"})]
    )
    assert run(p.plan(snap([young]))) == []
    assert "too early" in p.last.dropped[0]


def test_model_failure_falls_back_to_rules():
    p = planner_replying([], status=500)
    acts = run(p.plan(snap([SILENT])))
    assert [(a.tool, a.source) for a in acts] == [("place_call", "rules")]
    assert p.last.used_fallback and p.last.error


def test_nothing_open_skips_the_model():
    seen: list = []
    p = planner_replying([], seen=seen)
    assert run(p.plan(snap([SEEDED, {**SILENT, "status": "safe"}]))) == []
    assert seen == []


def test_unanswered_call_gets_one_followup_text():
    vm = {
        **SILENT,
        "status": "unreachable",
        "call_status": "done",
        "call_answered": False,
    }
    due = due_actions([vm], NOW, 60)
    assert [a.tool for a in due] == ["send_imessage"] and "911" in due[0].args["text"]
    assert due_actions([{**vm, "followups_sent": 1}], NOW, 60) == []


def test_emergency_call_unanswered_retries_once_then_texts_and_gets_human():
    em = {
        **SILENT,
        "status": "unreachable",
        "call_status": "done",
        "call_answered": False,
        "call_reason": "emergency",
        "last_contact_at": ago(70),
    }
    first = due_actions([em], NOW, 60)
    assert [(a.tool, a.args.get("reason")) for a in first] == [
        ("place_call", "emergency")
    ]
    after = due_actions([{**em, "call_attempts": 2}], NOW, 60)
    tools = {a.tool: a for a in after}
    assert "911" in tools["send_imessage"].args["text"]
    assert tools["request_human"].args["reason"] == "Welfare check recommended"


def test_planner_text_with_unverified_amount_is_cleaned():
    p = planner_replying(
        [
            (
                "send_imessage",
                {
                    "policyholder_id": "ph_017",
                    "text": "We approved $5,000 for you. Reply 2 if you need help.",
                },
            )
        ]
    )
    acts = run(
        p.plan(
            snap(
                [
                    {
                        **MARIA,
                        "urgency": 2,
                        "human_requested": True,
                        "claim_id": "SF-4955-0017",
                    }
                ]
            )
        )
    )
    msg = next(a for a in acts if a.tool == "send_imessage")
    assert "$" not in msg.args["text"] and "Reply 2" in msg.args["text"]
    assert any("unverified $" in d for d in p.last.dropped)
