# /// script
# requires-python = ">=3.12"
# dependencies = ["twilio>=9.0", "python-dotenv>=1.0"]
# ///
"""Spike: can the agent CALL someone (follow up on non-responders)?

Places a call to CALL_TO that speaks a check-in and gathers a spoken answer,
posting it to the voice webhook (just spike-voice + cloudflared on :8010).
Twilio trial accounts can only call numbers verified in the console.
PASS = phone rings, you hear the prompt, your answer prints in spike-voice.
Run: just spike-call
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv(Path(__file__).parent / ".env")
need = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM",
    "CALL_TO",
    "VOICE_WEBHOOK_BASE",
]
missing = [k for k in need if not os.getenv(k)]
if missing:
    sys.exit(f"FAIL: set {', '.join(missing)} in spikes/.env")

base = os.environ["VOICE_WEBHOOK_BASE"].rstrip("/")
twiml = (
    "<Response>"
    f'<Gather input="speech" action="{base}/voice/heard" method="POST" speechTimeout="auto">'
    "<Say>This is a State Farm check-in after the storm. Are you safe? Tell me if you need help.</Say>"
    "</Gather><Say>We did not hear you. We will try again soon.</Say></Response>"
)
call = Client(
    os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
).calls.create(to=os.environ["CALL_TO"], from_=os.environ["TWILIO_FROM"], twiml=twiml)
print(
    f"call queued: {call.sid} status={call.status}. Answer your phone; watch the spike-voice terminal."
)
