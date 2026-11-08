# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "photonhq-api==0.6.0", "python-dotenv>=1.0"]
# ///
"""Spike: outbound call Photon SIP -> ElevenLabs agent, greeting with case context.

1. Photon: configure (or reuse / rotate) the default voice profile's OUTBOUND SIP credential.
   The password is returned ONCE; it is saved to backend/.env immediately.
2. ElevenLabs: put Photon's SIP host + credential on our number's outbound_trunk_config.
3. ElevenLabs: give the agent case-aware dynamic variables (with defaults, so inbound still works).
4. Place an outbound call to CALL_TO with the case context; poll until done; print the transcript.

PASS = phone rings, agent mentions the case, transcript comes back.
Run: just voice-outbound            (setup + call)
     just voice-outbound --setup    (setup only, no call)
"""

import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from photon_api import Photon, PhotonError

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = ROOT / "backend" / ".env"
load_dotenv(BACKEND_ENV)
load_dotenv(ROOT / "spikes" / ".env")

EL_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "").strip()
PHONE_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "").strip()
PH_KEY = (
    os.getenv("PHOTON_API_KEY") or os.getenv("SPECTRUM_PROJECT_SECRET") or ""
).strip()
PH_PROJECT = (
    os.getenv("PHOTON_PROJECT_ID") or os.getenv("SPECTRUM_PROJECT_ID") or ""
).strip()
CALL_TO = (
    os.getenv("CALL_TO")
    or os.getenv("DEMO_PHONE_A")
    or os.getenv("PHOTON_TEST_SENDER")
    or os.getenv("OUTBOUND_TO", "").split(",")[0]
).strip()
SETUP_ONLY = "--setup" in sys.argv

need = {
    "ELEVENLABS_API_KEY": EL_KEY,
    "ELEVENLABS_AGENT_ID": AGENT_ID,
    "ELEVENLABS_PHONE_NUMBER_ID": PHONE_ID,
    "PHOTON_API_KEY": PH_KEY,
    "PHOTON_PROJECT_ID": PH_PROJECT,
}
if not SETUP_ONLY:
    need["CALL_TO (E.164)"] = CALL_TO
missing = [k for k, v in need.items() if not v]
if missing:
    sys.exit(f"FAIL: missing {', '.join(missing)} (backend/.env or spikes/.env)")


def save_env(values: dict[str, str]) -> None:
    text = BACKEND_ENV.read_text() if BACKEND_ENV.exists() else ""
    for k, v in values.items():
        if re.search(rf"^{k}=", text, re.M):
            text = re.sub(rf"^{k}=.*$", lambda _: f"{k}={v}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{k}={v}\n"
    BACKEND_ENV.write_text(text)


def mask(p: str) -> str:
    return f"***{p[-4:]}" if p else "?"


# ---------- 1. Photon outbound credential ----------
from photon_api.rpc_generated import (  # noqa: E402
    ConfigureVoiceProfileOutboundInput,
    GetDefaultVoiceProfileInput,
    RotateVoiceProfileOutboundCredentialInput,
)

auth = {"Authorization": f"Bearer {PH_KEY}"}
saved_user = os.getenv("PHOTON_SIP_OUT_USERNAME", "").strip()
saved_pass = os.getenv("PHOTON_SIP_OUT_PASSWORD", "").strip()

with Photon(headers=auth) as ph:
    prof = ph.projects.platforms.get_default_voice_profile(
        GetDefaultVoiceProfileInput.model_validate({"path": {"id": PH_PROJECT}})
    )
    out = prof.configuration.outbound if prof.configuration else None
    password = None
    try:
        if out and saved_pass and out.authentication.username == saved_user:
            print(f"[1] reuse Photon outbound credential (user {saved_user})")
            password = saved_pass
        elif out:
            r = ph.projects.platforms.rotate_voice_profile_outbound_credential(
                RotateVoiceProfileOutboundCredentialInput.model_validate(
                    {
                        "path": {"id": PH_PROJECT, "profileId": prof.profileId},
                        "headers": {"Idempotency-Key": str(uuid.uuid4())},
                        "body": {"expectedVersion": prof.version, "mode": "emergency"},
                    }
                )
            )
            r = getattr(r, "data", r)
            password = r.password
            print("[1] outbound existed but no saved password -> rotated credential")
        else:
            r = ph.projects.platforms.configure_voice_profile_outbound(
                ConfigureVoiceProfileOutboundInput.model_validate(
                    {
                        "path": {"id": PH_PROJECT, "profileId": prof.profileId},
                        "headers": {"Idempotency-Key": str(uuid.uuid4())},
                        "body": {
                            "authentication": {"algorithm": "sha-256"},
                            "expectedVersion": prof.version,
                        },
                    }
                )
            )
            r = getattr(r, "data", r)
            password = r.password
            out = r.outbound
            print("[1] configured Photon outbound credential (sha-256)")
    except PhotonError as e:
        sys.exit(
            f"FAIL (Photon outbound): {type(e).__name__} {getattr(e, 'status', '')} {e}"
            " - 402 = payment method needed; 403 = key needs platforms:write"
        )
    # re-read for connection details (rotate response has none)
    prof = ph.projects.platforms.get_default_voice_profile(
        GetDefaultVoiceProfileInput.model_validate({"path": {"id": PH_PROJECT}})
    )
    out = prof.configuration.outbound

if not password:
    sys.exit("FAIL: Photon returned no password (and none saved in backend/.env)")

username = out.authentication.username
eps = out.connection.endpoints
ep = next((e for e in eps if e.transport == "tls"), eps[0])
address = f"{ep.host}:{ep.port}"
save_env(
    {
        "PHOTON_SIP_OUT_USERNAME": username,
        "PHOTON_SIP_OUT_PASSWORD": password,
        "PHOTON_SIP_OUT_ADDRESS": address,
        "PHOTON_SIP_OUT_TRANSPORT": ep.transport,
    }
)
print(
    f"[1] Photon outbound: {address} ({ep.transport}), realm {out.connection.realm}, "
    f"user {username}, password saved to backend/.env"
)
print(f"    all endpoints: {[f'{e.host}:{e.port}/{e.transport}' for e in eps]}")

# ---------- 2. ElevenLabs outbound trunk ----------
el = httpx.Client(
    base_url="https://api.elevenlabs.io", headers={"xi-api-key": EL_KEY}, timeout=30
)


def check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        sys.exit(f"FAIL ({what}): HTTP {r.status_code} {r.text[:600]}")
    return r.json() if r.content else {}


trunk = {
    "address": address,
    "transport": ep.transport,
    "media_encryption": "allowed",
    "credentials": {"username": username, "password": password},
}
check(
    el.patch(
        f"/v1/convai/phone-numbers/{PHONE_ID}", json={"outbound_trunk_config": trunk}
    ),
    "set outbound trunk",
)
num = check(el.get(f"/v1/convai/phone-numbers/{PHONE_ID}"), "read number")
ot = num.get("outbound_trunk") or num.get("outbound_trunk_config") or {}
print(
    f"[2] ElevenLabs number {num.get('phone_number')} outbound -> {ot.get('address', ot)}"
)

# ---------- 3. Agent: case-aware greeting via dynamic variables ----------
FIRST_MESSAGE = (
    "Hi {{first_name}}, this is State Farm's storm check-in line. {{case_opening}} "
    "Are you and everyone with you safe right now?"
)
PROMPT = (
    "You are a calm, brief State Farm catastrophe check-in agent after Hurricane Isaias. "
    "Why we are calling: {{call_reason}}. What we know so far: {{case_summary}}. "
    "Do not ask again for what you already know. Ask one question at a time: is anyone injured or trapped, "
    "do they have power, water and needed medication, what is damaged (home, car, belongings), "
    "and do they need a place to stay tonight. If anyone is in immediate danger, tell them to hang up and call 911 now. "
    "If they ask for a person, say a State Farm agent will contact them within 15 minutes. "
    "Keep every reply under two sentences. Never promise claim payments."
)
VOICEMAIL_MESSAGE = (
    "Hi {{first_name}}, this is State Farm checking on you after Hurricane Isaias. "
    "Please text us back, or call us at 7 0 1, 8 8 8, 0 2 8 2. If you are in danger, call 9 1 1."
)
DEFAULTS = {
    "first_name": "there",
    "case_opening": "We're checking on everyone affected by Hurricane Isaias.",
    "call_reason": "a routine storm check-in",
    "case_summary": "nothing yet",
}
check(
    el.patch(
        f"/v1/convai/agents/{AGENT_ID}",
        json={
            "conversation_config": {
                "agent": {
                    "first_message": FIRST_MESSAGE,
                    "prompt": {
                        "prompt": PROMPT
                        + " If you reach voicemail or an automated menu, do not converse with it.",
                        # Unanswered calls hit voicemail: leave one line and hang up instead of
                        # talking to the greeting (seen in test: 263s with a voicemail menu).
                        "built_in_tools": {
                            "voicemail_detection": {
                                "type": "system",
                                "name": "voicemail_detection",
                                "description": "Use when the call reaches voicemail or an answering machine.",
                                "params": {
                                    "system_tool_type": "voicemail_detection",
                                    "voicemail_message": VOICEMAIL_MESSAGE,
                                },
                            },
                            "end_call": {
                                "type": "system",
                                "name": "end_call",
                                "description": "End the call when the conversation is finished or nobody is responding.",
                                "params": {"system_tool_type": "end_call"},
                            },
                        },
                    },
                    "dynamic_variables": {"dynamic_variable_placeholders": DEFAULTS},
                },
                "turn": {"silence_end_call_timeout": 20},
                "conversation": {"max_duration_seconds": 240},
            }
        },
    ),
    "update agent",
)
print(
    "[3] agent greeting/prompt now use {{first_name}}, {{case_opening}}, {{call_reason}}, {{case_summary}}"
)

if SETUP_ONLY:
    print("\nSETUP DONE (no call placed).")
    sys.exit(0)

# ---------- 4. Outbound call ----------
case = {
    "first_name": os.getenv("CALL_NAME", "Maria"),
    "case_opening": "You texted us that your roof caved in and there's water in the living room.",
    "call_reason": "the policyholder replied 4, asking for a call",
    "case_summary": "Homeowner at 412 Harbor Dr, Panama City. Roof caved in, water in living room, needs a hotel tonight. Policy covers up to $18,000 in hotel costs.",
}
t0 = time.time()
# The outbound-call request blocks until the call is set up (it can exceed 30s), so wait
# longer; on timeout, recover the conversation from the agent's newest outbound conversation.
try:
    r = check(
        el.post(
            "/v1/convai/sip-trunk/outbound-call",
            json={
                "agent_id": AGENT_ID,
                "agent_phone_number_id": PHONE_ID,
                "to_number": CALL_TO,
                "conversation_initiation_client_data": {"dynamic_variables": case},
            },
            timeout=90,
        ),
        "outbound call",
    )
except httpx.TimeoutException:
    print("[4] outbound-call request timed out; looking up the conversation instead")
    convs = check(
        el.get(
            "/v1/convai/conversations", params={"agent_id": AGENT_ID, "page_size": 5}
        ),
        "list conversations",
    ).get("conversations", [])
    recent = [
        c
        for c in convs
        if c.get("direction") == "outbound"
        and c.get("start_time_unix_secs", 0) >= t0 - 5
    ]
    r = {
        "conversation_id": recent[0]["conversation_id"] if recent else None,
        "success": None,
    }
conv = r.get("conversation_id")
print(
    f"[4] calling {mask(CALL_TO)}: success={r.get('success')} conv={conv} sip_call={r.get('sip_call_id')} msg={r.get('message')!r}"
)
if not conv:
    sys.exit("FAIL: no conversation_id returned")

status, d = None, {}
while time.time() - t0 < 300:
    d = el.get(f"/v1/convai/conversations/{conv}").json()
    if d.get("status") != status:
        status = d.get("status")
        print(f"    {time.time() - t0:5.1f}s status={status}")
    if status in ("done", "failed"):
        break
    time.sleep(3)

turns = d.get("transcript") or []
print("\n--- transcript ---")
for t in turns:
    print(f"{t.get('role', '?'):>5}: {t.get('message')}")
meta = d.get("metadata") or {}
an = d.get("analysis") or {}
print(
    f"--- duration {meta.get('call_duration_secs')}s, call_successful={an.get('call_successful')}"
)
if an.get("transcript_summary"):
    print(f"--- summary: {an['transcript_summary']}")

ok = status == "done" and any(t.get("role") == "user" for t in turns)
print(
    "\nPASS"
    if ok
    else f"\nFAIL: status={status}, user turns={sum(t.get('role') == 'user' for t in turns)}"
)
sys.exit(0 if ok else 1)
