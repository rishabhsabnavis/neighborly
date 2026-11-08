"""Live Messenger: iMessage over Photon 2.0 (photonhq-api).

Implements the Messenger interface from docs/BACKEND_PROMPT.md:
    async send(phone, text) -> message id
    async poll_inbound() -> list[InboundMessage]

Photon facts this relies on (verified in spikes/photon_beta.py, docs/CONTEXT.md):
- A shared iMessage line cannot message someone first. Each demo phone texts JOIN once;
  after that we can message that conversation ("space") any time.
- Sending needs the space id and the agent-side user id. Both come from the person's
  inbound message (space.id, receivedBy.id), so we cache phone -> route and persist it to
  ROUTES_FILE, which survives restarts.
- Receiving is polling list_messages(direction=received, createdSince=cursor).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from photon_api import AsyncPhoton
from photon_api.generated.models import TextContent
from photon_api.rpc_generated import (
    CreateSharedLineAssignmentInput,
    ListMessagesInput,
    SendMessageInput,
)

ROUTES_FILE = Path(__file__).resolve().parents[2] / ".photon_routes.json"


@dataclass
class InboundMessage:
    """Structurally matches the core's InboundMessage (phone, text, ts, id)."""

    id: str
    phone: str  # E.164 handle of the sender
    text: str
    ts: str  # ISO 8601 UTC


@dataclass
class Route:
    space_id: str
    agent_user_id: str
    last_message_id: str | None = None


class PhotonError(RuntimeError):
    pass


def _unwrap(obj):
    """Photon models nest RootModels (SentMessage.root -> Message.root -> TextMessage)."""
    for _ in range(4):
        inner = getattr(obj, "root", None)
        if inner is None or isinstance(inner, (str, int)):
            break
        obj = inner
    return obj


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _env(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


class PhotonMessenger:
    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        routes_file: Path = ROUTES_FILE,
        lookback_seconds: int = 10,
        client=None,  # injectable for tests
    ) -> None:
        self.api_key = api_key or _env("PHOTON_API_KEY", "SPECTRUM_PROJECT_SECRET")
        self.project_id = project_id or _env("PHOTON_PROJECT_ID", "SPECTRUM_PROJECT_ID")
        if not (self.api_key and self.project_id):
            raise PhotonError("PHOTON_API_KEY / PHOTON_PROJECT_ID not set")
        self._client = client or AsyncPhoton(
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.routes_file = routes_file
        self.routes: dict[str, Route] = self._load_routes()
        # Only pick up messages from (just before) startup on; older ones were handled already.
        self._cursor = _iso(datetime.now(UTC) - timedelta(seconds=lookback_seconds))
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()

    # ---------- routes (phone -> space) ----------
    def _load_routes(self) -> dict[str, Route]:
        try:
            raw = json.loads(self.routes_file.read_text())
            return {p: Route(**r) for p, r in raw.items()}
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return {}

    def _save_routes(self) -> None:
        tmp = self.routes_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({p: r.__dict__ for p, r in self.routes.items()}, indent=1)
        )
        tmp.replace(self.routes_file)

    def has_route(self, phone: str) -> bool:
        return phone in self.routes

    # ---------- setup ----------
    async def ensure_line(self, phone: str) -> str:
        """Assign a shared iMessage line to this phone (idempotent). Returns the number
        the person must text (JOIN) to opt in."""
        a = await self._client.projects.platforms.imessage.assignments.create(
            CreateSharedLineAssignmentInput.model_validate(
                {
                    "path": {"id": self.project_id},
                    "headers": {"Idempotency-Key": f"assign:{phone}"},
                    "body": {"handle": phone},
                }
            )
        )
        return a.assignedPhoneNumber

    # ---------- Messenger interface ----------
    async def send(self, phone: str, text: str) -> str:
        route = self.routes.get(phone)
        if route is None:
            route = await self._discover_route(phone)
        if route is None:
            raise PhotonError(
                f"no iMessage conversation with {phone[-4:]} yet (they must text JOIN first)"
            )
        sent = await self._client.projects.send_message(
            SendMessageInput.model_validate(
                {
                    "path": {"id": self.project_id},
                    "headers": {"idempotency-key": str(uuid.uuid4())},
                    "body": {
                        "spaceId": route.space_id,
                        "senderId": route.agent_user_id,
                        "content": {"type": "text", "format": "plain", "text": text},
                    },
                }
            )
        )
        return getattr(_unwrap(sent), "id", "") or ""

    async def poll_inbound(self) -> list[InboundMessage]:
        async with self._lock:
            out: list[InboundMessage] = []
            page_token = None
            newest = self._cursor
            while True:
                query = {
                    "createdSince": self._cursor,
                    "direction": "received",
                    "order": "asc",
                    "pageSize": 100,
                    "platform": "imessage",
                }
                if page_token:
                    query["pageToken"] = page_token
                page = await self._client.projects.list_messages(
                    ListMessagesInput.model_validate(
                        {"path": {"id": self.project_id}, "query": query}
                    )
                )
                for item in page.items:
                    msg = self._parse(item)
                    if msg is None or msg.id in self._seen:
                        continue
                    self._seen.add(msg.id)
                    out.append(msg)
                    newest = max(newest, msg.ts)
                page_token = getattr(page, "nextPageToken", None)
                if not isinstance(page_token, str) or not page_token:
                    break
            if newest != self._cursor:
                # Step back 1s for clock skew; _seen dedupes the overlap.
                dt = datetime.fromisoformat(newest) - timedelta(seconds=1)
                self._cursor = max(self._cursor, _iso(dt))
            if len(self._seen) > 5000:
                self._seen = set(list(self._seen)[-1000:])
            return out

    # ---------- helpers ----------
    def _parse(self, item) -> InboundMessage | None:
        m = _unwrap(item)
        try:
            phone = m.sentBy.root.handle
            space_id = m.space.root.id
            agent_user_id = m.receivedBy.root.id
        except AttributeError:
            return None
        text = m.content.text if isinstance(m.content, TextContent) else ""
        route = Route(
            space_id=space_id, agent_user_id=agent_user_id, last_message_id=m.id
        )
        if self.routes.get(phone) != route:
            self.routes[phone] = route
            self._save_routes()
        return InboundMessage(id=m.id, phone=phone, text=text.strip(), ts=m.createdAt)

    async def _discover_route(self, phone: str) -> Route | None:
        """Route not cached (e.g. fresh machine): find this phone's last inbound message
        in the past 7 days."""
        since = _iso(datetime.now(UTC) - timedelta(days=7))
        page = await self._client.projects.list_messages(
            ListMessagesInput.model_validate(
                {
                    "path": {"id": self.project_id},
                    "query": {
                        "createdSince": since,
                        "direction": "received",
                        "order": "desc",
                        "pageSize": 100,
                        "platform": "imessage",
                    },
                }
            )
        )
        for item in page.items:
            m = _unwrap(item)
            try:
                if m.sentBy.root.handle == phone:
                    self._parse(item)
                    return self.routes.get(phone)
            except AttributeError:
                continue
        return None

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None) or getattr(
            self._client, "close", None
        )
        if close:
            res = close()
            if asyncio.iscoroutine(res):
                await res
