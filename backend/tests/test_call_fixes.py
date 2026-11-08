from __future__ import annotations

from app import runtime
from app.integrations.base import CallResult, CallTurn
from tests.test_behavior import run_async


def _resolve(client, policyholder_id: str, transcript: list[CallTurn]) -> dict:
    flow = runtime.flow
    store = runtime.store
    assert flow is not None and store is not None
    assert client.post(f"/policyholders/{policyholder_id}/call").status_code == 200
    call_id = store.cases[policyholder_id].active_call_id
    assert call_id

    async def finish():
        async with store.lock:
            await flow.resolve_call(
                store.cases[policyholder_id],
                CallResult(
                    call_id=call_id,
                    status="done",
                    answered=True,
                    duration_s=60,
                    summary="Spoke with the policyholder.",
                    transcript=transcript,
                ),
            )

    run_async(client, finish)
    return client.get(f"/cases/{policyholder_id}").json()


def _place_calls(client) -> int:
    steps = client.get("/steps").json()["steps"]
    return sum(
        1
        for step in steps
        if step["kind"] == "tool_call" and step["tool"] == "place_call"
    )


def test_agent_words_do_not_trigger_emergency_or_human(client) -> None:
    case = _resolve(
        client,
        "ph_017",
        [
            CallTurn(
                role="agent",
                text="Is anyone injured or trapped? A State Farm agent can help.",
            ),
            CallTurn(role="user", text="The roof is leaking and we need a hotel."),
        ],
    )
    assert case["triage"]["urgency"] < 4
    assert case["human_request"] is None
    assert case["claim_draft"] is not None
    assert _place_calls(client) == 1


def test_life_safety_on_answered_call_flags_without_redialing(client) -> None:
    case = _resolve(
        client,
        "ph_017",
        [
            CallTurn(role="agent", text="Hi Maria, this is State Farm."),
            CallTurn(role="user", text="My mom's on oxygen and the power is out."),
        ],
    )
    assert case["triage"]["urgency"] == 4
    assert case["human_request"]["requested"] is True
    assert case["claim_draft"] is not None
    assert any("call 911" in message["text"] for message in case["messages"])
    assert _place_calls(client) == 1


def test_text_during_call_still_resolves_call(client) -> None:
    flow = runtime.flow
    assert flow is not None
    flow.caller.delay_s = 0  # type: ignore[attr-defined]
    assert (
        client.post(
            "/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": "4"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/dev/simulate-reply",
            json={"policyholder_id": "ph_017", "text": "roof is leaking"},
        ).status_code
        == 200
    )

    async def poll():
        assert runtime.agent is not None
        await runtime.agent.poll_calls()

    run_async(client, poll)
    case = client.get("/cases/ph_017").json()
    assert case["calls"][0]["status"] == "done"


def test_phone_b_gets_no_reply_call_without_opt_in(client, monkeypatch) -> None:
    monkeypatch.delenv("DEMO_ASSUME_OPTED_IN", raising=False)
    monkeypatch.setenv("NO_REPLY_SECONDS", "0")
    runtime.reset()
    store = runtime.store
    assert store is not None
    assert store.cases["ph_041"].opted_in is False
    run = client.post("/checkins/run", json={"disaster_number": 4955}).json()
    assert run["live"] == 1

    async def tick():
        assert runtime.agent is not None
        await runtime.agent.tick()

    run_async(client, tick)
    steps = client.get("/steps").json()["steps"]
    assert any(
        step["tool"] == "place_call"
        and "no_reply" in step["text"]
        and step["policyholder_id"] == "ph_041"
        for step in steps
    )
