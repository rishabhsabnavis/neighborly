from __future__ import annotations

import json

from app import runtime
from app.coverage import check_coverage, validate_amounts
from app.fallbacks import classify, follow_up_text, template_claim
from app.flow import parse_menu
from app.models import ClaimDraft, Message
from app.store import SEED_PATH
from tests.helpers import maria_case, renters_case


def run_async(client, fn):
    """Run on the app loop. The store's asyncio.Lock was created there."""

    return client.portal.call(fn)


def test_menu_parser() -> None:
    assert parse_menu("1") == "1"
    assert parse_menu("2") == "2"
    assert parse_menu("3") == "3"
    assert parse_menu("4") == "4"
    assert parse_menu("0") == "0"
    assert parse_menu("YES") == "yes"
    assert parse_menu("please call me") == "4"
    assert parse_menu("I want a person") == "0"
    assert parse_menu("roof caved in, water in the living room") == "free"


def test_check_coverage_maria_roof() -> None:
    result = check_coverage(maria_case(), "roof")
    assert result.model_dump() == {
        "item": "roof",
        "coverage": "dwelling",
        "covered": True,
        "limit": 320000,
        "deductible": 2500,
        "reason": "Dwelling: 412 Harbor Dr",
    }


def test_check_coverage_renters_roof_is_not_covered() -> None:
    result = check_coverage(renters_case(), "roof")
    assert result.covered is False
    assert result.coverage == "dwelling"
    assert "landlord" in result.reason


def test_validate_amounts_strips_unknown_dollars() -> None:
    text = "Your limit is $18,000. A manager approved $9,999 yesterday."
    clean = validate_amounts(text, maria_case().policy)
    assert "$18,000" in clean
    assert "9,999" not in clean


def test_heuristic_triage_oxygen() -> None:
    triage = classify("roof caved in, mom needs oxygen")
    assert triage.urgency == 4
    assert "medical" in triage.needs


def test_follow_up_mentions_ale_limit() -> None:
    text = follow_up_text(maria_case())
    assert text is not None
    assert "$18,000" in text


def test_template_claim_validates() -> None:
    case = maria_case()
    case.messages = [
        Message(
            id="m_1",
            ts="2026-11-07T23:40:00Z",
            from_="policyholder",
            channel="imessage",
            text="roof caved in, water in the living room, yes need hotel",
        )
    ]
    draft = template_claim(case)
    ClaimDraft.model_validate(draft.model_dump())
    assert draft.missing_info
    assert draft.claim_id == "SF-4955-0017"
    assert any(damage.coverage == "dwelling" for damage in draft.damages)


def test_seed_shape() -> None:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    people = raw["policyholders"]
    assert len(people) == 42
    assert raw["disaster"]["counties"] == [
        "Bay",
        "Calhoun",
        "Escambia",
        "Franklin",
        "Gadsden",
        "Gulf",
        "Holmes",
        "Jackson",
        "Jefferson",
        "Liberty",
        "Okaloosa",
        "Santa Rosa",
        "Wakulla",
        "Walton",
        "Washington",
    ]
    counties = {person["county"] for person in people}
    assert counties == set(raw["disaster"]["counties"])
    maria = next(person for person in people if person["id"] == "ph_017")
    assert maria["name"] == "Maria Lopez"
    assert maria["live"] is True
    assert maria["status"] == "pending"
    assert maria["policy"]["number"] == "SF-HO-88213"
    assert maria["policy"]["coverages"]["ale"] == 18000
    assert maria["policy"]["deductible"] == 2500
    assert maria["messages"] == []
    renters = [person for person in people if person["policy"]["type"] == "renters"]
    assert renters and "dwelling" not in renters[0]["policy"]["coverages"]
    assert any(person["policy"]["type"] == "auto" for person in people)
    lost = next(person for person in people if person["status"] == "unreachable")
    assert lost["human_requested"] is True
    assert lost["triage"]["action"] == "Welfare check recommended"
    assert "+1555" not in json.dumps(maria["phone_masked"])


def test_dashboard_sort_and_unknown_case(client) -> None:
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    rows = body["policyholders"]
    assert body["counts"]["total"] == len(rows) == 42
    assert "+1555" not in dashboard.text
    seen_other = False
    for row in rows:
        if row["human_requested"]:
            assert seen_other is False
        else:
            seen_other = True
    others = [row for row in rows if not row["human_requested"]]

    def rank(urgency: int | None) -> int:
        return -1 if urgency is None else urgency

    previous = 99
    for row in others:
        value = rank(row["urgency"])
        assert value <= previous
        previous = value
    missing = client.get("/cases/nope")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown policyholder"


def test_live_human_request_tops_queue(client) -> None:
    client.post("/checkins/run", json={"disaster_number": 4955})
    reply = client.post(
        "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "0"}
    )
    assert reply.status_code == 200
    rows = client.get("/dashboard").json()["policyholders"]
    assert rows[0]["id"] == "ph_017"
    assert rows[0]["human_requested"] is True
    assert sum(1 for row in rows if row["human_requested"]) == 6


def test_full_fake_run(client, monkeypatch) -> None:
    monkeypatch.setenv("NO_REPLY_SECONDS", "60")
    started = client.post("/checkins/run", json={"disaster_number": 4955})
    assert started.status_code == 200
    assert started.json() == {"run_id": "run_01", "queued": 42, "live": 2}
    opened = client.get("/cases/ph_017").json()
    assert any("Reply 1 Safe" in message["text"] for message in opened["messages"])

    reply = client.post(
        "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "2"}
    )
    assert reply.status_code == 200
    followed = client.get("/cases/ph_017").json()
    assert any("$18,000" in message["text"] for message in followed["messages"])
    assert followed["claim_draft"] is None

    detail = "roof caved in, water in the living room, yes need hotel"
    assert (
        client.post(
            "/dev/simulate-reply",
            json={"policyholder_id": "ph_017", "text": detail},
        ).status_code
        == 200
    )
    drafted = client.get("/cases/ph_017").json()
    assert drafted["claim_draft"]["claim_id"] == "SF-4955-0017"
    assert drafted["claim_draft"]["status"] == "draft"
    assert drafted["claim_draft"]["missing_info"]

    assert (
        client.post(
            "/dev/simulate-reply",
            json={"policyholder_id": "ph_017", "text": "YES"},
        ).status_code
        == 200
    )
    confirmed = client.get("/cases/ph_017").json()
    assert confirmed["claim_draft"]["status"] == "confirmed"


def test_silence_places_no_reply_call(client, monkeypatch) -> None:
    monkeypatch.setenv("NO_REPLY_SECONDS", "0")
    assert (
        client.post("/checkins/run", json={"disaster_number": 4955}).status_code == 200
    )

    async def tick():
        assert runtime.agent is not None
        await runtime.agent.tick()

    run_async(client, tick)
    steps = client.get("/steps").json()["steps"]
    assert any(
        step["tool"] == "place_call"
        and "no_reply" in step["text"]
        and step["policyholder_id"] == "ph_017"
        for step in steps
    )


def test_human_request_counts_as_a_reply(client, monkeypatch) -> None:
    monkeypatch.setenv("NO_REPLY_SECONDS", "0")
    client.post("/checkins/run", json={"disaster_number": 4955})
    client.post("/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "0"})
    rows = client.get("/dashboard").json()["policyholders"]
    maria = next(row for row in rows if row["id"] == "ph_017")
    assert maria["status"] == "replied"

    async def tick():
        assert runtime.agent is not None
        await runtime.agent.tick()

    run_async(client, tick)
    steps = client.get("/steps").json()["steps"]
    assert not any(
        step["tool"] == "place_call"
        and "no_reply" in step["text"]
        and step["policyholder_id"] == "ph_017"
        for step in steps
    )


def test_emergency_digit_and_free_text(client) -> None:
    first = client.post(
        "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "3"}
    )
    assert first.status_code == 200
    body = client.get("/cases/ph_017").json()
    assert body["triage"]["urgency"] == 4
    assert body["human_request"]["requested"] is True
    assert any("call 911" in message["text"] for message in body["messages"])
    steps = client.get("/steps").json()["steps"]
    assert any(step["text"] == "EMERGENCY" for step in steps)
    assert any(
        step["tool"] == "place_call" and "emergency" in step["text"] for step in steps
    )

    client.post("/demo/reset")
    trapped = client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "ph_017", "text": "I'm trapped, water rising"},
    )
    assert trapped.status_code == 200
    again = client.get("/cases/ph_017").json()
    assert again["triage"]["urgency"] == 4
    assert again["human_request"]["requested"] is True
    assert again["human_request"]["reason"] == "Emergency"


def test_voicemail_retries_once_then_unreachable(client) -> None:
    from app.timeutil import plus_seconds

    flow = runtime.flow
    assert flow is not None
    flow.caller.mode = "voicemail"  # type: ignore[attr-defined]
    flow.caller.delay_s = 0  # type: ignore[attr-defined]
    assert (
        client.post(
            "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "3"}
        ).status_code
        == 200
    )

    async def finish():
        assert runtime.agent is not None
        await runtime.agent.poll_calls()

    run_async(client, finish)
    mid = client.get("/cases/ph_017").json()
    row = next(
        item
        for item in client.get("/dashboard").json()["policyholders"]
        if item["id"] == "ph_017"
    )
    assert row["status"] != "unreachable"
    assert any("888-0282" in message["text"] for message in mid["messages"])

    assert flow is not None and flow.store is not None
    flow.store.cases["ph_017"].emergency_retry_at = plus_seconds(-5)

    async def tick():
        assert runtime.agent is not None
        await runtime.agent.tick()

    run_async(client, tick)
    run_async(client, finish)
    done = client.get("/cases/ph_017").json()
    row = next(
        item
        for item in client.get("/dashboard").json()["policyholders"]
        if item["id"] == "ph_017"
    )
    assert row["status"] == "unreachable"
    assert done["triage"]["action"] == "Welfare check recommended"
    assert done["human_request"]["requested"] is True
    emergency_steps = [
        step
        for step in client.get("/steps").json()["steps"]
        if step["tool"] == "place_call" and "reason=emergency" in step["text"]
    ]
    assert len(emergency_steps) >= 2


def test_manual_call_unknown_and_failure(client) -> None:
    missing = client.post("/policyholders/nope/call")
    assert missing.status_code == 404
    flow = runtime.flow
    assert flow is not None
    flow.caller.fail_next = True  # type: ignore[attr-defined]
    failed = client.post("/policyholders/ph_017/call")
    assert failed.status_code == 502
    assert failed.json()["detail"].startswith("call failed:")


def test_simulate_unknown(client) -> None:
    response = client.post(
        "/dev/simulate-reply",
        json={"policyholder_id": "nope", "text": "2"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown policyholder"
