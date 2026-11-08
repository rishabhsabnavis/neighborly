# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "photonhq-api==0.6.0", "python-dotenv>=1.0"]
# ///
"""One-shot, re-runnable inbound voice setup: Photon number -> ElevenLabs agent.

1. ElevenLabs: create (or reuse) agent "Neighborly Check-in".
2. ElevenLabs: import the Photon number as a SIP-trunk number, assigned to the agent.
3. Photon: ensure default Voice profile (SIP); set inbound destination to ElevenLabs.
4. Write ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID into backend/.env.
Then call the number. Run: just voice-setup
"""

import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from photon_api import Photon, PhotonError

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = ROOT / "backend" / ".env"
load_dotenv(BACKEND_ENV)
load_dotenv(ROOT / "spikes" / ".env")  # fallback for Photon creds

EL_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
PH_KEY = (
    os.getenv("PHOTON_API_KEY") or os.getenv("SPECTRUM_PROJECT_SECRET") or ""
).strip()
PH_PROJECT = (
    os.getenv("PHOTON_PROJECT_ID") or os.getenv("SPECTRUM_PROJECT_ID") or ""
).strip()
NUMBER = os.getenv("PHOTON_VOICE_NUMBER", "+17018880282").strip()
EL_SIP = os.getenv("ELEVENLABS_SIP_URI", "sips:sip.rtc.elevenlabs.io:5061").strip()
AGENT_NAME = "Neighborly Check-in"

missing = [
    n
    for n, v in [
        ("ELEVENLABS_API_KEY", EL_KEY),
        ("PHOTON_API_KEY", PH_KEY),
        ("PHOTON_PROJECT_ID", PH_PROJECT),
    ]
    if not v
]
if missing:
    sys.exit(f"FAIL: missing {', '.join(missing)} (backend/.env or spikes/.env)")

FIRST_MESSAGE = "Hi, this is Neighborly checking on you after Hurricane Isaias. Are you and everyone with you safe right now?"
PROMPT = (
    "You are a calm, brief disaster check-in agent for Neighborly insurance. Ask whether the person is safe, "
    "whether anyone is injured or trapped, whether they have power, water and needed medication, and their "
    "address or nearest cross street. Ask one question at a time. If anyone is in immediate danger, tell them "
    "to hang up and call 911 now. Keep every reply under two sentences. Never promise claim payments."
)

el = httpx.Client(
    base_url="https://api.elevenlabs.io", headers={"xi-api-key": EL_KEY}, timeout=30
)


def check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        sys.exit(f"FAIL ({what}): HTTP {r.status_code} {r.text[:400]}")
    return r.json() if r.content else {}


# 1. agent
agents = check(
    el.get("/v1/convai/agents", params={"search": AGENT_NAME, "page_size": 30}),
    "list agents",
).get("agents", [])
agent = next((a for a in agents if a.get("name") == AGENT_NAME), None)
if agent:
    agent_id = agent["agent_id"]
    print(f"[1] reuse agent {agent_id}")
else:
    agent_id = check(
        el.post(
            "/v1/convai/agents/create",
            json={
                "name": AGENT_NAME,
                "conversation_config": {
                    "agent": {
                        "first_message": FIRST_MESSAGE,
                        "language": "en",
                        "prompt": {"prompt": PROMPT, "llm": "gpt-4o-mini"},
                    }
                },
            },
        ),
        "create agent",
    )["agent_id"]
    print(f"[1] created agent {agent_id}")

# 2. SIP-trunk number in ElevenLabs
nums = check(el.get("/v1/convai/phone-numbers"), "list numbers")
nums = nums if isinstance(nums, list) else nums.get("phone_numbers", [])
existing = next((n for n in nums if n.get("phone_number") == NUMBER), None)
if existing:
    phone_id = existing["phone_number_id"]
    check(
        el.patch(f"/v1/convai/phone-numbers/{phone_id}", json={"agent_id": agent_id}),
        "assign agent",
    )
    print(f"[2] reuse number {phone_id}, agent assigned")
else:
    phone_id = check(
        el.post(
            "/v1/convai/phone-numbers",
            json={
                "provider": "sip_trunk",
                "label": "Photon Neighborly",
                "phone_number": NUMBER,
                "agent_id": agent_id,
                "inbound_trunk_config": {"media_encryption": "allowed"},
            },
        ),
        "import number",
    )["phone_number_id"]
    print(f"[2] imported {NUMBER} as {phone_id}")

# 3. Photon default voice profile -> ElevenLabs
auth = {"Authorization": f"Bearer {PH_KEY}"}
from photon_api.rpc_generated import (  # noqa: E402
    CreateDefaultVoiceProfileInput,
    GetDefaultVoiceProfileInput,
    ReplaceVoiceProfileInboundInput,
)

with Photon(headers=auth) as ph:
    try:
        prof = ph.projects.platforms.get_default_voice_profile(
            GetDefaultVoiceProfileInput.model_validate({"path": {"id": PH_PROJECT}})
        )
        print(f"[3] default profile exists ({prof.profileId}, v{prof.version})")
    except PhotonError as e:
        if getattr(e, "status", None) != 404:
            sys.exit(
                f"FAIL (get Photon profile): {type(e).__name__} {getattr(e, 'status', '')} - check key has platforms:read/write"
            )
        prof = ph.projects.platforms.create_default_voice_profile(
            CreateDefaultVoiceProfileInput.model_validate(
                {
                    "path": {"id": PH_PROJECT},
                    "body": {"protocol": "sip", "mediaEncryption": "auto"},
                }
            )
        )
        print(f"[3] created default profile ({prof.profileId}, v{prof.version})")
    inbound = prof.configuration.inbound
    current = getattr(inbound, "destinationUri", None) if inbound else None
    if current == EL_SIP:
        print(f"[3] inbound already -> {EL_SIP}")
    else:
        try:
            ph.projects.platforms.replace_voice_profile_inbound(
                ReplaceVoiceProfileInboundInput.model_validate(
                    {
                        "path": {"id": PH_PROJECT, "profileId": prof.profileId},
                        "body": {
                            "destinationUri": EL_SIP,
                            "credentials": None,
                            "expectedVersion": prof.version,
                        },
                    }
                )
            )
        except PhotonError as e:
            sys.exit(
                f"FAIL (set Photon inbound): {type(e).__name__} {getattr(e, 'status', '')} - key needs platforms:write"
            )
        print(f"[3] inbound destination set -> {EL_SIP}")

# 4. persist ids
text = BACKEND_ENV.read_text() if BACKEND_ENV.exists() else ""
for k, v in {
    "ELEVENLABS_AGENT_ID": agent_id,
    "ELEVENLABS_PHONE_NUMBER_ID": phone_id,
}.items():
    text = (
        re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.M)
        if re.search(rf"^{k}=", text, re.M)
        else text.rstrip("\n") + f"\n{k}={v}\n"
    )
BACKEND_ENV.write_text(text)
print(
    f"[4] saved ids to backend/.env\n\nDONE. Call {NUMBER} from your phone; the agent should greet you."
)
