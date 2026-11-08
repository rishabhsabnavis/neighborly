# Prompt for the backend coding agent

Paste everything below the line into your coding agent, started from the repo root.

---

You are building the **SafeFarm backend core**, a FastAPI service for our HackUTD 2026 project (24h hackathon, State Farm track). Read these first, in order: `CLAUDE.md` (rules and commands), `docs/CONTEXT.md` (status), `docs/SPEC.md` (scope, demo script, **data contracts**). SPEC.md is the source of truth. If something here conflicts with it, SPEC wins. Don't build anything in SPEC's "Not doing" list.

## What it is
After Hurricane Isaias (FEMA-4955, 15 FL panhandle counties), an AI agent texts every opted-in State Farm policyholder an iMessage menu, asks follow-ups based on their policy, calls them by voice on request or after silence, flags people who ask for a human, and writes a claim draft from the whole case. A Next.js console (built later, after the Figma design) polls this API to show the map, the priority queue, each case, and the agent's step log.

## Ownership (important: two people work in `backend/` at once)
- **You own:** `app/models.py`, `app/store.py`, `app/steps.py`, `app/flow.py`, `app/agent.py` (loop + rule-based planner), `app/fallbacks.py`, `app/integrations/base.py`, `app/integrations/fake.py`, `app/routes/*`, `app/seed/*`, `app/main.py`, and `tests/*` for those.
- **The owner (another person) owns:** `app/integrations/photon.py`, `app/integrations/elevenlabs.py`, `app/integrations/nemotron.py`, and later a Nemotron planner. **Don't create or edit those files.** Your job is the interfaces they plug into and fakes that let everything run without keys.
- Commit small working steps with plain imperative messages. **No AI attribution in commits** (no Co-Authored-By trailer, no "Generated with" line). Pull/rebase often. Before every push: `just test && just lint && just build` must pass (a hook enforces this in Claude Code).
- Python via `uv` only (`cd backend && uv add <pkg>`), never pip. Justify each new dependency in one line and add it to README.md "Built with". You should need nothing beyond what's installed (FastAPI, Pydantic, httpx). `pytest-asyncio` is fine if you need it.
- Port 8000 may be taken on the owner's Mac. Use `API_PORT=8001 just dev` if needed.

## The seam: integration interfaces (`app/integrations/base.py`)
```python
class Messenger(Protocol):          # iMessage (live = Photon)
    async def send(self, phone: str, text: str) -> str: ...          # returns message id
    async def poll_inbound(self) -> list[InboundMessage]: ...        # new messages since last poll: phone, text, ts, id

class Caller(Protocol):             # voice (live = ElevenLabs over Photon SIP)
    async def place_call(self, phone: str, context: CallContext) -> str: ...  # returns call_id; context = name, case summary, reason
    async def get_call(self, call_id: str) -> CallResult: ...        # status calling|done|failed, duration_s, transcript (list of turns), summary

class Brain(Protocol):              # LLM (live = Nemotron)
    async def triage(self, case: Case) -> Triage: ...
    async def follow_up(self, case: Case) -> str | None: ...         # next policy-aware question, None when done
    async def draft_claim(self, case: Case) -> ClaimDraft: ...
```
- `app/integrations/__init__.py` picks the implementation from env: `MESSENGER=fake|photon`, `CALLER=fake|elevenlabs`, `BRAIN=heuristic|nemotron` (defaults: fake, fake, heuristic). Import live modules **lazily** (inside the selector) so a missing live file never breaks startup. If a live import or a call fails, log an `error` step and use the fake/heuristic one.
- **Every** integration call is wrapped with a 10s timeout (`asyncio.wait_for`). On timeout or exception, log an `error` step and fall back. The demo can't hang or crash.
- `fake.py`: `FakeMessenger` records outbound messages in memory and gets inbound messages from `POST /dev/simulate-reply`. `FakeCaller` finishes a call 10s after `place_call` with a canned transcript that fits the case (e.g. "water's coming in, we're stuck upstairs").
- `fallbacks.py` (the heuristic Brain): keyword triage (oxygen/trapped/injured/water rising → 4; roof/flood/no power → 3; minor damage → 2; "safe/fine" → 1) with needs tags, policy-aware follow-up templates (asks about the covered dwelling or vehicle; mentions the ALE dollar limit when shelter is needed), and a template claim draft built from case fields. This is the demo's safety net, so make its output look good.

## Data and state
- `app/models.py`: Pydantic models for every request/response in SPEC "Data contracts" (`DashboardResponse`, `PolicyholderRow`, `CaseResponse`, `Policy`, `Message`, `Call`, `Triage`, `HumanRequest`, `ClaimDraft`, `Damage`, `Step`, ...). Enums as `Literal[...]`. Field names exactly as in SPEC. Every route declares `response_model`.
- `app/seed/isaias.json` plus a small, deterministic generator script (`app/seed/make_seed.py`, fixed random seed) that writes it: ~40 synthetic policyholders spread across the 15 counties (Bay, Calhoun, Escambia, Franklin, Gadsden, Gulf, Holmes, Jackson, Jefferson, Liberty, Okaloosa, Santa Rosa, Wakulla, Walton, Washington), with lat/lng inside each county, realistic names and addresses, and a mix of homeowners/renters/auto policies with coverages (dwelling, contents, ALE), deductibles, covered property and household/vulnerability notes. About 30 are pre-played cases (statuses, triage, messages, ~10 claim drafts, 2 `human_requested`) so the console is busy with no live input. Include **`ph_017` Maria Lopez** exactly as in SPEC (homeowners SF-HO-88213, 412 Harbor Dr, Panama City, Bay, ALE $18,000, deductible $2,500, mother 74 on home oxygen) as `live: true`, plus one more live slot `ph_041` for phone B. Live slots start `pending` with no history. Their phone numbers come from env `DEMO_PHONE_A` and `DEMO_PHONE_B` (E.164). Phones are masked in every response.
- `app/store.py`: in-memory store loaded from the seed, with `reset()`. Use one `asyncio.Lock` around mutations. Claim ids look like `SF-4955-0017` (the suffix is the policyholder number).
- `app/steps.py`: append-only step log (`id` auto-increments, `ts`, `kind` plan|tool_call|tool_result|triage|claim|error, `policyholder_id`, `tool`, `text`, `ms`). Every integration call and every decision logs a step, because the step log is what the Nvidia judges watch. Keep the last 1000.

## Conversation flow (`app/flow.py`), driven by inbound messages
- Inbound "JOIN" from a live phone → mark opted in, reply with a short confirmation. Check-in only texts opted-in live policyholders (the seeded ones are simulated). Allow `DEMO_ASSUME_OPTED_IN=1` to skip this during development.
- Check-in text: "{first name}, this is State Farm. Hurricane Isaias hit {county} County. Reply 1 Safe, 2 Need help, 3 Emergency, 4 Call me, 0 Talk to a person."
- **1** → status `safe`, urgency 1, thank-you reply, case closed.
- **2** → ask up to 2 `brain.follow_up` questions (one per reply). After each reply: `brain.triage`. Once the follow-ups are done (or after any reply with enough detail): `brain.draft_claim`, then text "We started claim {claim_id} for you. Reply YES to confirm."
- **3** → reply "If you're in danger, call 911 now. We've marked you top priority and are calling you." Set urgency 4 and place a call with `reason: "emergency"`.
- **4** or text containing "call" → place a call with `reason: "requested"`.
- **0** or "agent/person/human" → set `human_request` and reply "A State Farm agent will contact you within 15 min."
- **YES** while a claim draft exists → `claim_draft.status = "confirmed"`.
- Free text at any point → triage it. If the case is still on the menu, treat it as a "2".
- When a call finishes: merge the transcript into `messages` (`from: "voice_agent"/"policyholder"`, `channel: "voice"`), re-triage, draft or refresh the claim, and set `human_request` if the caller asked for a person.

## Agent loop (`app/agent.py`)
- Started as a background task on app startup (FastAPI lifespan). It ticks every `AGENT_TICK_SECONDS` (15) and also runs on every inbound event. A separate poll task runs `messenger.poll_inbound()` every 2s, and one polls `caller.get_call()` for active calls every 3s.
- Planner interface: `async def plan(snapshot) -> list[Action]` where an Action is one of the SPEC tools (`send_imessage`, `place_call`, `record_triage`, `request_human`, `draft_claim`). Implement `RulePlanner`: anyone `texted` with no reply after `NO_REPLY_SECONDS` (60) → `place_call(reason="no_reply")`. A failed call → mark `unreachable` and text the inbound number "(701) 888-0282". The owner will add a `NemotronPlanner` with the same signature later, selected by `PLANNER=rules|nemotron`.
- Each tick logs a `plan` step summarizing what it decided, then one step per action, so the log keeps moving.

## Endpoints (shapes exactly as in SPEC "Data contracts")
| Endpoint | Notes |
|---|---|
| `GET /health` | exists already |
| `POST /checkins/run` | texts every opted-in live policyholder (seeded ones move to `texted` too, for realism); returns `run_id`, `queued`, `live` |
| `GET /dashboard` | counts + rows, sorted: `human_requested` first, then urgency desc (null last), then `last_contact_at` oldest first |
| `GET /cases/{id}` | full case; 404 `{"detail":"unknown policyholder"}` |
| `GET /steps?since=<id>` | steps with id > since (all when missing) |
| `POST /policyholders/{id}/call` | manual call; 404 unknown; 502 `{"detail":"call failed: ..."}` |
| `POST /demo/reset` | reload seed, clear steps and live state |
| `POST /dev/simulate-reply` `{"policyholder_id":"ph_017","text":"2"}` | **dev + demo backup**: feeds an inbound message through the real flow, as if it came over iMessage. Returns `{"ok":true}` |

Add these to `backend/.env.example` with placeholders and comments: `MESSENGER`, `CALLER`, `BRAIN`, `PLANNER`, `DEMO_PHONE_A`, `DEMO_PHONE_B`, `DEMO_ASSUME_OPTED_IN`, `NO_REPLY_SECONDS`, `AGENT_TICK_SECONDS`. Never commit `backend/.env`.

## Done when (show the command and output for each)
1. `just test` passes, with pytest covering: menu parsing for 1/2/3/4/0/YES/free text; heuristic triage of "roof caved in, mom needs oxygen" → urgency 4 with `medical` in needs; the follow-up for a homeowners policy with ALE mentions "$18,000"; a claim draft validates against `ClaimDraft` and has non-empty `missing_info`; `/dashboard` sort order; `/cases/nope` → 404; and a full fake-integration run (check-in → simulate "2" → follow-up → simulate detail → claim → "YES" confirmed; and silence → `place_call` step with `reason: "no_reply"` using a tiny `NO_REPLY_SECONDS`).
2. `just lint` and `just build` exit 0.
3. Live smoke test with all fakes (`API_PORT=8001 just api`): `curl` every endpoint in the table, and the shapes match SPEC. After `POST /checkins/run` and `POST /dev/simulate-reply` with "4", `GET /steps` shows a `place_call` step, and within ~15s `GET /cases/ph_017` shows a finished call with transcript lines.
4. With `NVIDIA_API_KEY` and every live key unset, nothing crashes, and live selections that fail show `error` steps and fall back.

Work in this order and commit after each: models → seed + store → read endpoints (`/dashboard`, `/cases`, `/steps`) → integration interfaces + fakes + fallbacks → flow + `/dev/simulate-reply` → agent loop + pollers → `/checkins/run`, `/call`, `/demo/reset` → tests and smoke run. Once the read endpoints work, push and tell the owner, so they can start wiring the live integrations against them. Ask before adding a database, auth, websockets, or anything not listed here.
