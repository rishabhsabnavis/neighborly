"""Offline tests for the live integrations (Photon iMessage, ElevenLabs voice).

Fixtures are trimmed from real conversations recorded during the spikes (docs/CONTEXT.md).
No network calls are made.
"""

import asyncio
import json
from types import SimpleNamespace as NS

import httpx
from photon_api.generated.models import TextContent

from app.integrations.elevenlabs import (
    CallContext,
    ElevenLabsCaller,
    build_dynamic_variables,
    parse_conversation,
)
from app.integrations.photon import PhotonError, PhotonMessenger

# ---------- ElevenLabs: conversation parsing ----------

ANSWERED = {  # conv_6701m6wjc13xfhpty77105bddcqr (trimmed)
    "conversation_id": "conv_answered",
    "status": "done",
    "transcript": [
        {
            "role": "agent",
            "message": "Hi Maria, this is Neighborly's storm check-in line. You texted us that your roof caved in.",
        },
        {"role": "user", "message": "No."},
        {
            "role": "agent",
            "message": "I'm sorry to hear that. Is anyone injured or trapped?",
        },
        {"role": "user", "message": "My mom is on oxygen and the power is out."},
        {
            "role": "agent",
            "message": "Please hang up and call nine-one-one for immediate assistance.",
        },
    ],
    "metadata": {"call_duration_secs": 46, "termination_reason": "Client disconnected"},
    "analysis": {
        "call_successful": "success",
        "transcript_summary": "Roof collapse; mother on oxygen; power out.",
    },
}

VOICEMAIL_DETECTED = {  # conv_1401m6wjmpzyejhvksy68yg5xp9t (trimmed)
    "conversation_id": "conv_vm",
    "status": "done",
    "transcript": [
        {
            "role": "agent",
            "message": "Hi Maria, this is Neighborly's storm check-in line.",
        },
        {"role": "user", "message": "Message for 5555550100."},
        {
            "role": "agent",
            "message": "Hi Maria, this is Neighborly checking on you after Hurricane Isaias.",
        },
        {
            "role": "agent",
            "message": "",
            "tool_calls": [{"tool_name": "voicemail_detection", "type": "system"}],
        },
        {
            "role": "agent",
            "message": "",
            "tool_results": [{"tool_name": "voicemail_detection", "type": "system"}],
        },
    ],
    "metadata": {
        "call_duration_secs": 25,
        "termination_reason": "voicemail_detection tool was called.",
    },
    "analysis": {
        "call_successful": "success",
        "transcript_summary": "Message was left.",
    },
}

VOICEMAIL_UNDETECTED = {  # conv_5701m6wj7pjwe55s0n4b564gn0bd, before the fix (trimmed)
    "conversation_id": "conv_vm_old",
    "status": "done",
    "transcript": [
        {
            "role": "agent",
            "message": "Hi Maria, this is Neighborly's storm check-in line.",
        },
        {"role": "user", "message": "Message for 5555550100."},
        {"role": "user", "message": "..."},
        {
            "role": "user",
            "message": "Your recording has reached the maximum length. To replay your message, press one.",
        },
        {
            "role": "user",
            "message": "Your message has been sent. Thank you for calling. Goodbye.",
        },
    ],
    "metadata": {
        "call_duration_secs": 263,
        "termination_reason": "Client disconnected: 1000",
    },
    "analysis": {
        "call_successful": "success",
        "transcript_summary": "The user only sent '...' messages.",
    },
}


def test_answered_call_is_answered_with_clean_transcript():
    r = parse_conversation("call_1", ANSWERED)
    assert r.status == "done" and r.answered is True and r.voicemail is False
    assert r.duration_s == 46
    assert [t.role for t in r.transcript][:2] == ["agent", "user"]
    assert "oxygen" in r.transcript[3].text


def test_voicemail_tool_call_means_unanswered():
    r = parse_conversation("call_2", VOICEMAIL_DETECTED)
    assert r.status == "done" and r.voicemail is True and r.answered is False
    assert all(t.text for t in r.transcript)  # empty tool turns dropped


def test_voicemail_menu_without_tool_still_unanswered():
    r = parse_conversation("call_3", VOICEMAIL_UNDETECTED)
    assert r.answered is False  # even though ElevenLabs said call_successful=success
    assert all(t.text != "..." for t in r.transcript)


def test_in_progress_maps_to_calling():
    for s in ("initiated", "in-progress", "processing"):
        r = parse_conversation("c", {"status": s, "transcript": []})
        assert r.status == "calling" and r.answered is None


def test_dynamic_variables_per_reason():
    v = build_dynamic_variables(
        CallContext(name="Maria Lopez", summary="Roof caved in", reason="no_reply")
    )
    assert v["first_name"] == "Maria"
    assert "text" in v["case_opening"] and v["case_summary"] == "Roof caved in"
    assert set(v) == {
        "first_message",
        "first_name",
        "case_opening",
        "call_reason",
        "case_summary",
    }
    assert v["first_message"].startswith("Hi Maria, this is Neighborly")
    assert (
        build_dynamic_variables(CallContext(name="", reason="requested"))[
            "case_summary"
        ]
        == "nothing yet"
    )


# ---------- ElevenLabs: place_call returns fast, get_call resolves ----------


def _caller(handler) -> ElevenLabsCaller:
    return ElevenLabsCaller(
        api_key="k",
        agent_id="agent_x",
        phone_number_id="phnum_x",
        transport=httpx.MockTransport(handler),
    )


def test_place_call_returns_immediately_then_resolves():
    async def run():
        dial_gate = asyncio.Event()

        async def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/v1/convai/sip-trunk/outbound-call":
                body = json.loads(req.content)
                assert body["to_number"] == "+15555550100"
                assert (
                    body["conversation_initiation_client_data"]["dynamic_variables"][
                        "first_name"
                    ]
                    == "Maria"
                )
                await dial_gate.wait()  # simulate the blocking dial
                return httpx.Response(
                    200, json={"success": True, "conversation_id": "conv_answered"}
                )
            if req.url.path == "/v1/convai/conversations/conv_answered":
                return httpx.Response(200, json=ANSWERED)
            return httpx.Response(404)

        c = _caller(handler)
        call_id = await asyncio.wait_for(
            c.place_call("+15555550100", CallContext(name="Maria Lopez")), 0.5
        )
        assert (await c.get_call(call_id)).status == "calling"
        dial_gate.set()
        await asyncio.sleep(0.05)
        r = await c.get_call(call_id)
        assert (
            r.status == "done"
            and r.answered is True
            and r.conversation_id == "conv_answered"
        )
        await c.aclose()

    asyncio.run(run())


def test_dial_timeout_recovers_conversation():
    async def run():
        async def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/v1/convai/sip-trunk/outbound-call":
                raise httpx.ReadTimeout("slow", request=req)
            if req.url.path == "/v1/convai/conversations":
                return httpx.Response(
                    200,
                    json={
                        "conversations": [
                            {
                                "conversation_id": "conv_vm",
                                "direction": "outbound",
                                "start_time_unix_secs": 9e12,
                            }
                        ]
                    },
                )
            if req.url.path == "/v1/convai/conversations/conv_vm":
                return httpx.Response(200, json=VOICEMAIL_DETECTED)
            return httpx.Response(404)

        c = _caller(handler)
        call_id = await c.place_call("+15555550100", CallContext(name="Maria"))
        await asyncio.sleep(0.05)
        r = await c.get_call(call_id)
        assert (
            r.conversation_id == "conv_vm"
            and r.answered is False
            and r.voicemail is True
        )
        await c.aclose()

    asyncio.run(run())


def test_dial_http_error_is_failed_call():
    async def run():
        c = _caller(lambda req: httpx.Response(422, json={"detail": "bad number"}))
        call_id = await c.place_call("+1", CallContext(name="X"))
        await asyncio.sleep(0.05)
        r = await c.get_call(call_id)
        assert r.status == "failed" and r.answered is False and "422" in (r.error or "")
        await c.aclose()

    asyncio.run(run())


# ---------- Photon ----------


def _msg(mid: str, phone: str, text: str, ts: str):
    return NS(
        root=NS(
            root=NS(
                id=mid,
                sentBy=NS(root=NS(handle=phone)),
                space=NS(root=NS(id="spc_1")),
                receivedBy=NS(root=NS(id="usr_agent")),
                content=TextContent.model_validate(
                    {"type": "text", "format": "plain", "text": text}
                ),
                createdAt=ts,
            )
        )
    )


class FakePhoton:
    def __init__(self, pages):
        self.pages = list(pages)
        self.sent = []

        async def list_messages(inp):
            return self.pages.pop(0) if self.pages else NS(items=[], nextPageToken=None)

        async def send_message(inp):
            self.sent.append(inp.body)
            return NS(id=f"msg_out_{len(self.sent)}")

        self.projects = NS(list_messages=list_messages, send_message=send_message)


def test_photon_poll_dedupes_and_learns_route_then_sends(tmp_path):
    async def run():
        m1 = _msg("m1", "+15555550100", " JOIN ", "2026-11-08T05:00:01.000Z")
        fake = FakePhoton(
            [NS(items=[m1], nextPageToken=None), NS(items=[m1], nextPageToken=None)]
        )
        p = PhotonMessenger(
            api_key="k", project_id="prj", routes_file=tmp_path / "r.json", client=fake
        )
        first = await p.poll_inbound()
        again = await p.poll_inbound()
        assert [(m.phone, m.text) for m in first] == [("+15555550100", "JOIN")]
        assert again == []  # same message not delivered twice
        assert p.has_route("+15555550100")
        mid = await p.send("+15555550100", "Reply 1 Safe, 2 Need help")
        assert mid == "msg_out_1"
        body = fake.sent[0]
        assert body.spaceId == "spc_1" and body.senderId == "usr_agent"
        # the route survives a restart
        p2 = PhotonMessenger(
            api_key="k",
            project_id="prj",
            routes_file=tmp_path / "r.json",
            client=FakePhoton([]),
        )
        assert p2.has_route("+15555550100")

    asyncio.run(run())


def test_photon_send_without_join_raises(tmp_path):
    async def run():
        p = PhotonMessenger(
            api_key="k",
            project_id="prj",
            routes_file=tmp_path / "r.json",
            client=FakePhoton([]),
        )
        try:
            await p.send("+15555550199", "hi")
        except PhotonError as e:
            assert "JOIN" in str(e)
        else:
            raise AssertionError("expected PhotonError")

    asyncio.run(run())


def test_emergency_call_opens_with_911_line():
    v = build_dynamic_variables(CallContext(name="Maria", reason="emergency"))
    assert v["case_opening"] == "If you're in danger, hang up and call 911 now."
    assert "ONLY safety questions" in v["call_reason"]
    assert v["first_message"].startswith(
        "If you're in danger, hang up and call 911 now."
    )
