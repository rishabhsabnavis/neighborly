# /// script
# requires-python = ">=3.12"
# dependencies = ["photonhq-api==0.6.0", "python-dotenv>=1.0"]
# ///
"""Spike (Photon 2.0 beta, iMessage shared line).

1. Assign a shared line to PHOTON_TEST_SENDER (your phone) and print the agent number.
2. Wait for you to text that number, reply "echo: <text>".
3. 5s later, send a follow-up in the same conversation without a new inbound
   message (simulates a later disaster check-in to an enrolled person).
PASS = both replies arrive on your phone. Run: just spike-photon
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from photon_api import Photon, PhotonError
from photon_api.generated.models import CreateSharedLineAssignmentRequest, TextContent
from photon_api.rpc_generated import (
    CreateSharedLineAssignmentHeader,
    CreateSharedLineAssignmentInput,
    CreateSharedLineAssignmentPath,
    ListMessagesInput,
    SendMessageInput,
)

load_dotenv(Path(__file__).parent / ".env")
KEY = os.getenv("PHOTON_API_KEY") or os.getenv("SPECTRUM_PROJECT_SECRET")
PROJECT = os.getenv("PHOTON_PROJECT_ID") or os.getenv("SPECTRUM_PROJECT_ID")
SENDER = (
    os.getenv("PHOTON_TEST_SENDER")
    or (os.getenv("OUTBOUND_TO") or "").split(",")[0].strip()
)
if not (KEY and PROJECT and SENDER):
    sys.exit(
        "FAIL: set PHOTON_API_KEY, PHOTON_PROJECT_ID, PHOTON_TEST_SENDER (+1XXXXXXXXXX, your own phone) in spikes/.env"
    )


def send(photon, space_id, sender_id, text, idem, parent=None):
    body = {
        "spaceId": space_id,
        "senderId": sender_id,
        "content": {"type": "text", "format": "plain", "text": text},
    }
    if parent:
        body["parentMessageId"] = parent
    photon.projects.send_message(
        SendMessageInput.model_validate(
            {
                "path": {"id": PROJECT},
                "headers": {"idempotency-key": idem},
                "body": body,
            }
        )
    )


with Photon(headers={"Authorization": f"Bearer {KEY}"}) as photon:
    # 1. shared-line assignment (idempotent per sender)
    try:
        a = photon.projects.platforms.imessage.assignments.create(
            CreateSharedLineAssignmentInput(
                path=CreateSharedLineAssignmentPath(id=PROJECT),
                headers=CreateSharedLineAssignmentHeader.model_validate(
                    {"Idempotency-Key": f"assign:{SENDER}"}
                ),
                body=CreateSharedLineAssignmentRequest(handle=SENDER),
            )
        )
        agent_number = a.assignedPhoneNumber
        print(f"Assigned agent line for {SENDER}: {agent_number}")
    except PhotonError as e:
        agent_number = None
        print(
            f"Assignment via API failed ({type(e).__name__}: {getattr(e, 'status', '')}). "
            "If you already assigned a line in the dashboard (iMessage page), use that number."
        )

    # 2. wait for an inbound text from SENDER
    started = datetime.now(timezone.utc)
    since = (
        (started - timedelta(seconds=5))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    print(
        f"\n>>> From {SENDER}, text the agent number{f' {agent_number}' if agent_number else ''} anything (5 min window)..."
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        page = photon.projects.list_messages(
            ListMessagesInput.model_validate(
                {
                    "path": {"id": PROJECT},
                    "query": {
                        "createdSince": since,
                        "direction": "received",
                        "order": "asc",
                        "pageSize": 100,
                        "platform": "imessage",
                    },
                }
            )
        )
        for item in page.items:
            m = item.root.root
            if (
                m.sentBy.root.handle != SENDER
                or datetime.fromisoformat(m.createdAt) < started
            ):
                continue
            text = (
                m.content.text
                if isinstance(m.content, TextContent)
                else f"<{type(m.content).__name__}>"
            )
            space_id, agent_id = m.space.root.id, m.receivedBy.root.id
            print(f"IN  ({m.space.root.kind}) {SENDER}: {text!r}")
            t0 = time.time()
            send(
                photon, space_id, agent_id, f"echo: {text}", f"echo:{m.id}", parent=m.id
            )
            print(f"OUT echo accepted in {time.time() - t0:.2f}s")
            time.sleep(5)
            try:
                send(
                    photon,
                    space_id,
                    agent_id,
                    "Follow-up check-in: are you safe? Reply 1 = safe, 2 = need help now.",
                    f"followup:{m.id}",
                )
                print("OUT unprompted follow-up accepted")
            except PhotonError as e:
                print(
                    f"FOLLOW-UP REJECTED: {type(e).__name__} {getattr(e, 'status', '')} -> only direct replies allowed"
                )
            print(
                "\nPASS if both messages arrived on your phone (the API accepting them doesn't confirm delivery)."
            )
            sys.exit(0)
        time.sleep(2)
    sys.exit("FAIL: no inbound message from the test sender within 5 minutes")
