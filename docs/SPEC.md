# SPEC: SafeFarm (working name)

> If it's not in here, we're not building it.

## Problem
When a publicly declared catastrophe hits, a policyholder needs help right away and doesn't know how to ask for it. Weeks later they still have to file a claim from memory. **Who has it:** State Farm policyholders in a disaster zone (and the CAT agents serving them). Today they cope by waiting on hold in an overloaded call center, then retelling everything again to file a claim.

**Principle:** victim safety first, the claim second. Every conversation, whether text, voice or human, adds to one case record, and that record becomes a claim draft.

## Target tracks / prizes
| Track or prize | What judges want | Sponsor tech required | How we qualify |
|---|---|---|---|
| State Farm | Real impact for policyholders in a disaster | none required | Policy-aware check-in, escalation ladder (text, then voice, then human), auto claim draft for FEMA-4955 |
| Nvidia | Nemotron "beyond a chatbot": multi-step planning + tool calls on external APIs | Nemotron via build.nvidia.com | Nemotron agent runs each case: reads policy, picks follow-ups, places calls, triages, drafts the claim; visible step log |
| Photon | Interactive iMessage (replies trigger actions) | Photon 2.0 iMessage API | Menu replies trigger follow-ups, calls, human requests and claim confirmation |
| Photon Voice Call ($300) | Voice calls on Photon | Photon voice profile (SIP) | Outbound call (on request or after silence) over Photon SIP -> ElevenLabs agent |
| Virality (general) | Shareable, memorable | none | Phone rings on stage seconds after replying "4"; claim appears from the conversation |

## 2-minute demo script
Cast: 2 people. Phone A = an iPhone, the victim. Phone B = any phone, the silent policyholder (gets a call only; no iMessage needed). Presenter drives the agent console.
1. (0:00-0:20) Problem: Hurricane Isaias (FEMA-4955) just hit 15 FL panhandle counties. Maria, a State Farm homeowner, is flooded, and the call center has a 3-hour hold.
2. (0:20-0:35) Solution: SafeFarm texts every policyholder in the zone, knows their policy, gets them help over text, voice or a human, and turns the conversation into a claim draft.
3. (0:35-1:35) Live demo: click **Run check-in**. Phone A gets: "Maria, this is State Farm. Hurricane Isaias hit Bay County. Reply 1 Safe, 2 Need help, 3 Emergency, 4 Call me, 0 Talk to a person." She replies **2**. Nemotron uses her policy for the follow-ups: "Is there damage to your home at 412 Harbor Dr? Your policy covers up to $18,000 in hotel costs. Do you need a place to stay tonight?" She replies "roof caved in, water in the living room, yes need hotel", then **4**. **Phone A rings within seconds (wow moment)**, and the voice agent already knows what she said. She adds "my mom's on oxygen and the power is out." Hang up. The console shows urgency 4, the step log, and a **claim draft** (dwelling roof, contents water damage, ALE hotel, medical-needs flag). She gets "We started claim SF-4955-0017. Reply YES to confirm." Meanwhile phone B never answered, so after 60s the agent logs "no reply, calling" and phone B rings.
4. (1:35-1:50) Impact: help in minutes instead of hours on hold, the victim never tells their story twice, and State Farm gets a structured first notice of loss on day 0.
5. (1:50-2:00) Tech: Nemotron agent + triage, Photon iMessage + SIP voice, ElevenLabs voice agent, FastAPI, Next.js. Hardest part: one case record shared across text, voice and human.

## MVP features (max 3)
1. **Policy-aware iMessage check-in**: the agent clicks "Run check-in". Each opted-in policyholder in the zone gets the menu (1 Safe / 2 Need help / 3 Emergency / 4 Call me / 0 Talk to a person). Nemotron reads their seeded policy (type, covered property, coverages and deductible, household and vulnerability notes) and asks at most 2 tailored follow-ups. Every reply is triaged into urgency 1-4 with needs, a summary and an action. **3** also replies "If you're in danger, call 911 now", sets urgency 4 and places a call. **1** closes the case as safe.
2. **Escalation ladder: voice, then human**: replying **4** (or "call") makes the ElevenLabs agent call the phone over Photon SIP. The call is seeded with the case so far, and its transcript is merged back into the case. Policyholders who don't reply within `NO_REPLY_SECONDS` (60 in the demo) are called automatically. Replying **0**, or asking for a person on the call, sets `human_requested` and gets the reply "A State Farm agent will contact you within 15 min." The case jumps up the human queue in the console.
3. **Claim draft + agent console**: after enough context (or at the end of a call), Nemotron writes a structured claim draft from the case and policy. The policyholder gets a short text summary with the claim # and can reply YES to confirm. Next.js console: county map with pins colored by urgency, a ranked queue (human-requested first, then urgency, then time waiting), a case panel (policy, full text and call transcript, triage, claim draft) and a live Nemotron step log.

**Stretch (only after all 3 pass verification):** a live human handoff, where the voice call is transferred to the teammate playing the State Farm agent, or that teammate replies to the victim's iMessage from the case panel.

## Not doing
- Filing real claims or any real State Farm system, policy data or integration (policies are synthetic seed data)
- Dispatching 911/rescue (we only *tell* people to call 911 and *recommend* actions)
- Damage photo analysis (Nemotron VL is tempting, but it's not in the demo)
- SMS (10DLC approval takes days); group chats; iMessage polls/mini apps/tapbacks (not in the beta)
- Auth / accounts, multi-tenant setup, settings pages, admin panels, mobile app
- Live NWS/FEMA fetching during the demo (the scenario is seeded from FEMA-4955)
- Multiple languages; claim PDF export; payments/payouts; adjuster scheduling

## Architecture and data flow
```
[Phone A/B] <-iMessage-> [Photon 2.0] <-poll 2s / send-> [FastAPI]
[Phone A/B] <-voice---- [Photon SIP] <-> [ElevenLabs agent] <-outbound-call / GET transcript- [FastAPI]
[Next.js console] --poll 2s--> [FastAPI]
FastAPI: case store (in-memory) + agent loop (15s tick + on every inbound event) --> Nemotron super (plan, tool calls, claim draft)
                                                                                 --> Nemotron lightning (triage)
```
State is in memory and seeded from `backend/app/seed/isaias.json` (~40 synthetic policyholders with policies, lat/lng across the FEMA-4955 counties, and pre-triaged cases, some with claim drafts) plus a local FL county GeoJSON. Only the demo phones are live. Phone A opts in by texting JOIN first (a Photon shared line can't send the first message). Phone B only gets calls. We poll instead of using webhooks, so no tunnel is needed. Every external call has a 10s timeout: on failure the step is logged as `error` and the demo continues (heuristic keyword triage; template claim draft from the case fields).

Nemotron agent tools (internal): `get_case(id)` (policy + history), `send_imessage(id, text)`, `place_call(id, context)`, `record_triage(id, urgency, needs[], summary, action)`, `request_human(id, reason)`, `draft_claim(id)`, `list_due_policyholders()`.

## Data contracts
### `GET /health` -> `{"status":"ok"}`

### `POST /checkins/run`
Request: `{"disaster_number": 4955}` · Response 200: `{"run_id":"run_01","queued":42,"live":2}`

### `GET /dashboard`
```json
{
  "disaster": {"number": 4955, "name": "Hurricane Isaias", "state": "FL", "counties": ["Bay", "Gulf"]},
  "counts": {"total": 42, "safe": 20, "needs_help": 9, "critical": 3, "no_response": 8, "calling": 1, "human_requested": 2, "claims_drafted": 11},
  "policyholders": [
    {"id": "ph_017", "name": "Maria Lopez", "phone_masked": "***-***-4410", "county": "Bay",
     "lat": 30.16, "lng": -85.66, "live": true,
     "status": "pending|texted|replied|calling|called|unreachable|safe",
     "channel": "imessage|voice|human",
     "human_requested": false,
     "urgency": 4, "summary": "Roof caved in, water inside, mother on oxygen, no power",
     "claim_id": "SF-4955-0017",
     "last_contact_at": "2026-11-07T23:41:02Z"}
  ]
}
```
Sorted by `human_requested` first, then urgency (descending), then `last_contact_at` (oldest first). `urgency` and `claim_id` may be null.

### `GET /cases/{id}`
```json
{
  "policyholder": {"id": "ph_017", "name": "Maria Lopez", "address": "412 Harbor Dr, Panama City, FL", "county": "Bay"},
  "policy": {"number": "SF-HO-88213", "type": "homeowners|renters|auto",
             "covered_property": ["Dwelling: 412 Harbor Dr", "2019 Toyota Camry"],
             "coverages": {"dwelling": 320000, "contents": 160000, "ale": 18000}, "deductible": 2500,
             "household": {"size": 3, "notes": ["Mother, 74, home oxygen"]}},
  "messages": [{"id": "m_1", "ts": "2026-11-07T23:40:00Z", "from": "agent|policyholder|voice_agent", "channel": "imessage|voice", "text": "Reply 1 Safe, 2 Need help..."}],
  "calls": [{"call_id": "conv_abc", "reason": "requested|no_reply|emergency", "status": "calling|done|failed", "duration_s": 74, "transcript_summary": "..."}],
  "triage": {"urgency": 4, "label": "critical", "needs": ["medical", "shelter", "power"], "summary": "...", "action": "Welfare check; book ALE hotel", "source": "imessage|call|seed"},
  "human_request": {"requested": true, "reason": "Asked for a person on the call", "ts": "2026-11-07T23:45:10Z"},
  "claim_draft": {
    "claim_id": "SF-4955-0017", "status": "draft|confirmed",
    "policy_number": "SF-HO-88213", "date_of_loss": "2026-10-27", "cause_of_loss": "Hurricane Isaias (FEMA-4955): wind + water",
    "loss_location": "412 Harbor Dr, Panama City, FL",
    "damages": [{"item": "Roof", "description": "Caved in", "coverage": "dwelling", "severity": "major"},
                {"item": "Living room contents", "description": "Water intrusion", "coverage": "contents", "severity": "moderate"}],
    "ale_requested": true, "injuries_or_medical": ["Mother on home oxygen, power out"],
    "deductible": 2500, "missing_info": ["Photos of damage", "Estimated repair cost"],
    "evidence": ["m_4", "conv_abc"]
  }
}
```
`calls`, `human_request` and `claim_draft` may be empty/null. Unknown id -> `404 {"detail":"unknown policyholder"}`.

### `GET /steps?since=<step_id>`
```json
{"steps": [{"id": 57, "ts": "2026-11-07T23:42:10Z", "kind": "plan|tool_call|tool_result|triage|claim|error",
            "policyholder_id": "ph_017", "tool": "place_call", "text": "Replied 4 -> calling with case context", "ms": 812}]}
```

### `POST /policyholders/{id}/call` (manual backup button)
Response 200: `{"call_id":"conv_abc","status":"calling"}` · Errors: `404 {"detail":"unknown policyholder"}`, `502 {"detail":"call failed: ..."}`

### `POST /demo/reset` -> `{"ok": true}` (reloads the seed, clears live state)

## Riskiest part (test first)
1. **Outbound call over Photon SIP -> ElevenLabs, with case context.** Inbound calls pass, but outbound hasn't been tried. **Spike:** run `configure_voice_profile_outbound`, put the creds on the ElevenLabs number's outbound trunk, then `POST /v1/convai/sip-trunk/outbound-call` to phone A, passing `conversation_initiation_client_data.dynamic_variables` (name and case summary) so the agent greets with context, then fetch the transcript. **Pass** = the phone rings, the agent mentions the policyholder's issue, and the transcript comes back over the API. **Fallback:** text "Call us now at (701) 888-0282" (the inbound path already passes); we lose the auto-call wow moment and probably the Photon Voice prize.
2. **Claim draft quality.** Spike: feed one fixture case (policy + 4 messages + a transcript) to Nemotron super with the `claim_draft` JSON schema. Pass = valid JSON, correct coverages mapped, no invented damages, in under 8s. Fallback: template fill from triage fields.

## Verification
| Feature | Pass/fail check |
|---|---|
| Backend up | `curl localhost:8000/health` returns `{"status":"ok"}` |
| Policy-aware check-in | pytest: menu parser maps 1/2/3/4/0 + free text; follow-up for a homeowners policy with ALE mentions the ALE limit (mocked Nemotron); live: `POST /checkins/run`, phone A gets the menu, replies 2, gets a policy-specific follow-up, and `GET /cases/ph_017` shows the triage within 15s |
| Voice + human ladder | live: reply 4, phone A rings within 20s, the agent references the case, and after hangup `calls[0].status:"done"` and the transcript is merged into `messages`; the silent phone B rings within 90s with `reason:"no_reply"`; reply 0 sets `human_requested:true` and sorts the case to the top of `/dashboard` |
| Claim draft + console | pytest: claim draft from the fixture validates against the Pydantic model, `missing_info` is non-empty when there are no photos; live: the YES reply sets `status:"confirmed"`; `just build` exits 0; screenshot of the console with map pins, queue, case panel with claim draft, and step log updating |
| Demo resilience | Nemotron key unset -> `/dashboard` and `/cases/{id}` still return seeded data, and the step log shows `error` steps instead of a crash |
| Deployed | production URL returns 200 and the happy path works there |
