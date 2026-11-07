# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]
# ///
"""Spike: does a real phone call reach our backend with a transcript?

Twilio <Gather input="speech"> flow. Point a Twilio number's "A call comes in"
webhook (POST) at https://<tunnel>/voice. Run: just spike-voice  (port 8010)
PASS = you call the number, hear the greeting, speak, and the transcript
prints here and is read back to you.
"""

import time
from xml.sax.saxutils import escape

import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import Response

app = FastAPI()


def twiml(body: str) -> Response:
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
        media_type="application/xml",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/voice")
def voice(From: str = Form(""), CallSid: str = Form("")) -> Response:
    print(f"[{time.strftime('%X')}] incoming call {CallSid} from {From}", flush=True)
    return twiml(
        '<Gather input="speech" action="/voice/heard" method="POST" speechTimeout="auto">'
        "<Say>Hi, this is the screening assistant. Who is calling, and why?</Say>"
        "</Gather><Say>I didn't hear anything. Goodbye.</Say>"
    )


@app.post("/voice/heard")
def heard(
    SpeechResult: str = Form(""), Confidence: str = Form(""), CallSid: str = Form("")
) -> Response:
    print(
        f"[{time.strftime('%X')}] TRANSCRIPT {CallSid}: {SpeechResult!r} (confidence {Confidence})",
        flush=True,
    )
    return twiml(f"<Say>Thanks. I heard: {escape(SpeechResult)}. Goodbye.</Say>")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010)
