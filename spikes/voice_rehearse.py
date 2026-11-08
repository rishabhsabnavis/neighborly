"""Voice demo rehearsal: place a call through the REAL backend modules and triage the result.

Uses app/integrations/elevenlabs.py (ElevenLabsCaller) and nemotron.py (NemotronBrain), so this
rehearses exactly what the backend will do after a real call. Each call costs ElevenLabs credits.

Run:  just voice-rehearse                       # calls DEMO_PHONE_B as "James", reason no_reply
      just voice-rehearse --to +15551234567 --name "Maria Lopez" --reason requested \
          --summary "Roof caved in, water in the living room, needs a hotel"
      just voice-rehearse --reason emergency    # opens with the 911 line, safety-only questions
Reasons: no_reply (the silent phone, demo phone B), requested (replied 4), emergency (replied 3).
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")
load_dotenv(ROOT / "spikes" / ".env")

from app.integrations.elevenlabs import CallContext, ElevenLabsCaller  # noqa: E402
from app.integrations.nemotron import NemotronBrain  # noqa: E402

DEFAULT_SUMMARY = {
    "no_reply": "We texted a storm check-in 2 minutes ago and got no reply. Lives in Gulf County.",
    "requested": "Roof caved in, water in the living room, couch and TV ruined, needs a hotel tonight.",
    "emergency": "Replied 3 (emergency) to our check-in text.",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--to",
        default=(os.getenv("DEMO_PHONE_B") or os.getenv("CALL_TO") or "").strip(),
    )
    ap.add_argument("--name", default="James Reed")
    ap.add_argument(
        "--reason", choices=["no_reply", "requested", "emergency"], default="no_reply"
    )
    ap.add_argument("--summary", default=None)
    a = ap.parse_args()
    if not a.to.startswith("+"):
        sys.exit("FAIL: give --to +1XXXXXXXXXX (or set DEMO_PHONE_B in backend/.env)")
    asyncio.run(run(a.to, a.name, a.reason, a.summary or DEFAULT_SUMMARY[a.reason]))


async def run(to: str, name: str, reason: str, summary: str) -> None:
    caller = ElevenLabsCaller()
    t0 = time.monotonic()
    call_id = await caller.place_call(
        to, CallContext(name=name, summary=summary, reason=reason)
    )
    print(
        f"[call] {call_id} -> ***{to[-4:]} as {name!r}, reason={reason}  (place_call returned in {time.monotonic() - t0:.2f}s)"
    )
    print(
        "       Answer the phone and talk (or let it go to voicemail to test that path)."
    )
    status, r = None, None
    while time.monotonic() - t0 < 300:
        r = await caller.get_call(call_id)
        if r.status != status:
            status = r.status
            print(
                f"[call] {time.monotonic() - t0:5.1f}s status={status}"
                + (f" error={r.error}" if r.error else "")
            )
        if r.status in ("done", "failed"):
            break
        await asyncio.sleep(3)
    await caller.aclose()
    if r is None or r.status != "done":
        print(f"\nRESULT: call did not finish cleanly (status={status}).")
        return

    print(f"\n--- transcript ({r.duration_s}s, conversation {r.conversation_id}) ---")
    for t in r.transcript:
        print(f"{t.role:>5}: {t.text}")
    print(f"--- answered={r.answered} voicemail={r.voicemail}")
    if r.summary:
        print(f"--- ElevenLabs summary: {r.summary}")
    if not r.answered:
        print(
            "\nRESULT: UNANSWERED -> the planner would send the follow-up text"
            + (" and retry once (emergency)." if reason == "emergency" else ".")
        )
        return

    case = {
        "policyholder": {
            "id": "ph_041",
            "name": name,
            "address": "118 Bayview Ave, Port St. Joe, FL",
            "county": "Gulf",
        },
        "policy": {
            "number": "SF-HO-90417",
            "type": "homeowners",
            "covered_property": ["Dwelling: 118 Bayview Ave", "2017 Ford F-150"],
            "coverages": {
                "dwelling": 240000,
                "contents": 120000,
                "ale": 12000,
                "auto": 25000,
            },
            "deductible": 2000,
            "household": {"size": 2, "notes": []},
        },
        "messages": [
            {
                "id": "m_1",
                "from": "agent",
                "channel": "imessage",
                "text": "Check-in menu",
            }
        ]
        + [
            {
                "id": f"v_{i}",
                "from": "voice_agent" if t.role == "agent" else "policyholder",
                "channel": "voice",
                "text": t.text,
            }
            for i, t in enumerate(r.transcript)
        ],
        "calls": [
            {
                "call_id": r.conversation_id,
                "status": "done",
                "transcript_summary": r.summary,
            }
        ],
    }
    brain = NemotronBrain()
    tri = await brain.triage(case)
    print(
        f"\n[triage {brain.last_ms}ms] urgency {tri.urgency} ({tri.label}) needs={tri.needs} source={tri.source}"
        + (f"  floor: {brain.last_floor_reason}" if brain.last_floor_reason else "")
    )
    print(f"   {tri.summary} -> {tri.action}")
    await brain.aclose()
    print(
        "\nRESULT: ANSWERED -> transcript merged, re-triaged"
        + (", human requested (urgency 4)." if tri.urgency == 4 else ".")
    )


if __name__ == "__main__":
    main()
