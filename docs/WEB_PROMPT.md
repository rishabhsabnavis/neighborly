# Prompt for the web-app coding agent

Paste everything below the line into your coding agent, started from the repo root.

---

You are building the **SafeFarm agent console**, the web frontend for our HackUTD 2026 project (24h hackathon, State Farm track). Read these first, in order: `CLAUDE.md` (rules and commands), `docs/CONTEXT.md` (status), `docs/SPEC.md` (scope, demo script, **data contracts**). SPEC.md is the source of truth. If something here conflicts with it, SPEC wins. Don't build anything in SPEC's "Not doing" list.

## What it is
After Hurricane Isaias (FEMA-4955, 15 FL panhandle counties), a Nemotron AI agent texts every State Farm policyholder over iMessage, escalates to a voice call or a human, and writes a claim draft. This console is what a State Farm CAT agent (and the judges) watch: who needs help, the full conversation for each person, the claim draft, and the AI agent's steps as they happen. It runs on the presenting laptop (1440x900, also on a projector), so text must be readable from across a room.

## Ownership and boundaries
- You own `frontend/` only. The backend (`backend/`, FastAPI) is built in parallel by someone else and may not exist yet, so **build against mock data first** (see Mock mode).
- Stack already set up: Next.js 16 App Router, TypeScript, Tailwind v4, shadcn/ui (base-ui). Add shadcn components with `npx shadcn@latest add <name>` and never hand-edit `components/ui/*`. Package manager: pnpm.
- Backend base URL: `process.env.NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). Never hardcode it.
- Design comes from our Figma (the designer is working on it now). Until it lands, use clean shadcn defaults with the layout and color system below, and keep styling in a few components so restyling later is cheap.
- New deps: justify each in one line and add it to README.md "Built with". Expected: `leaflet` + `react-leaflet` + `@types/leaflet` (county map; nothing installed does maps). Avoid anything else unless needed.
- Commit small working steps with plain imperative messages. **No AI attribution in commits** (no Co-Authored-By trailer). Before each push run `just test && just lint && just build` (a hook enforces it in Claude Code).

## Mock mode (do this first)
- `frontend/lib/api.ts`: typed client with one function per endpoint. If `NEXT_PUBLIC_USE_MOCK=1` (or the backend is unreachable), return fixtures from `frontend/lib/mock/*.ts`.
- `frontend/lib/types.ts`: TypeScript types copied **exactly** from SPEC.md "Data contracts" (`Dashboard`, `PolicyholderRow`, `Case`, `ClaimDraft`, `Step`, ...). Use string-literal unions for enums.
- Fixtures: ~40 realistic policyholders spread across the 15 counties (Bay, Calhoun, Escambia, Franklin, Gadsden, Gulf, Holmes, Jackson, Jefferson, Liberty, Okaloosa, Santa Rosa, Wakulla, Walton, Washington) with lat/lng inside them, a mix of urgencies and statuses, 2 `human_requested`, 1 `calling`, ~10 with claim drafts. Include the full demo case `ph_017` Maria Lopez from SPEC (menu, reply "2", policy-aware follow-up, "roof caved in...", reply "4", call transcript, claim draft). Mock `/steps` should emit a new step every 1-2s so the log visibly moves.
- Add `NEXT_PUBLIC_USE_MOCK=` to `frontend/.env.example`.

## Endpoints you consume (shapes in SPEC.md)
| Endpoint | Use |
|---|---|
| `GET /dashboard` | poll every 2s: counts, policyholder rows (already sorted) |
| `GET /cases/{id}` | poll every 2s while a case is open |
| `GET /steps?since=<id>` | poll every 1.5s and append; keep the last 200 |
| `POST /checkins/run` `{"disaster_number":4955}` | "Run check-in" button |
| `POST /policyholders/{id}/call` | "Call now" backup button in the case panel |
| `POST /demo/reset` | "Reset demo" (small, in a menu; confirm first in-app, **no `window.confirm`**) |

Polling: one interval hook (`usePoll(fn, ms)`), pause it when the tab is hidden, and keep the last good data on error with a small "reconnecting..." badge. **Never blank the screen on a failed fetch.**

## Layout: one page, `/` (no auth, no other routes needed)
```
+--------------------------------------------------------------------------------+
| SafeFarm · Hurricane Isaias FEMA-4955 · FL   [counts tiles x6]  [Run check-in] ⋮ |
+------------------------------+-------------------------+-----------------------+
|  County map (Leaflet)        |  Priority queue         |  Agent step log       |
|  15 counties outlined,       |  ranked rows            |  (Nemotron live)      |
|  pins colored by urgency     |                         |                       |
+------------------------------+-------------------------+-----------------------+
   clicking a pin or row opens the Case panel (right-side Sheet, ~560px wide)
```
1. **Header**: disaster name/number/state; count tiles for `total, safe, needs_help, critical, no_response, human_requested, claims_drafted` (and a pulsing `calling` indicator when > 0); a primary **Run check-in** button (disabled + spinner while running; toast with `queued`/`live` after); overflow menu with Reset demo.
2. **Map**: OSM tiles; FL county outlines from a **local** file `frontend/public/fl-counties.geojson`. Make it once: download `https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json`, keep features whose id starts with `12` (optionally only the 15 FEMA-4955 counties, shaded), and commit the small result. Never fetch it at runtime. The map is centered on the panhandle. Pins are circle markers colored by urgency/status. `live:true` pins get a ring. `calling` pins pulse. `human_requested` pins get a person badge. The selected pin is enlarged. Leaflet must be loaded client-only (`dynamic(..., {ssr:false})`) or the build breaks.
3. **Priority queue**: rows in the order the API returns (human-requested, then urgency, then oldest contact). Each row shows the urgency chip, name, county, status/channel icon (iMessage / phone / person), a one-line summary, "x min ago", and a claim chip if `claim_id` exists. A row briefly highlights when its data changes. Filter tabs: All / Critical / Needs help / No response / Human requested.
4. **Agent step log**: monospace-ish feed, newest at the bottom with auto-scroll (pause auto-scroll when the user scrolls up). Each step: time, kind badge (`plan`, `tool_call`, `tool_result`, `triage`, `claim`, `error`), tool name, text, `ms`, and policyholder name (clicking it opens the case). `error` steps are red but never crash anything. This panel is what the Nvidia judges look at, so make it legible and alive.
5. **Case panel** (Sheet) for `GET /cases/{id}`, top to bottom:
   - Name, address, county, masked phone; urgency chip; status + channel.
   - **Human requested** banner (reason + time) when set.
   - **Policy card**: number, type, covered property, coverages (dwelling/contents/ALE as $), deductible, household notes (vulnerability notes are highlighted).
   - **Triage card**: urgency 1-4 + label, needs as chips, summary, recommended action, source (imessage/call/seed).
   - **Conversation timeline**: merged messages in time order, as chat bubbles (agent vs. policyholder vs. voice agent, with channel icon), plus call blocks (reason requested/no_reply/emergency, status, duration, transcript summary). It scrolls to the newest message.
   - **Claim draft card**: claim id, status badge (draft / confirmed by policyholder), policy #, date and cause of loss, loss location, damages table (item, description, coverage, severity), ALE requested, injuries/medical, deductible, **missing info** checklist, evidence links that scroll to the referenced message/call. Empty state: "No claim yet. The agent drafts one once it has enough detail."
   - Actions: **Call now** (POST call, show the 502 error text in a toast if it fails).

## Color and status system (keep these as Tailwind/CSS tokens)
- Urgency 4 critical = red, 3 high = orange, 2 moderate = amber, 1 low/safe = green; no response = gray; calling = blue (pulsing); human requested = purple accent.
- Never rely on color alone: chips carry the text label, and pins carry an icon or ring for live/calling/human.

## Done when (show evidence for each)
1. `NEXT_PUBLIC_USE_MOCK=1 pnpm dev`: the page renders 40 pins, the queue, the moving step log, and Maria's full case panel with the claim draft. Take a screenshot.
2. `just test` and `just build` exit 0 (paste the output).
3. With the backend running (`NEXT_PUBLIC_USE_MOCK=` unset), the same UI fills from the real API, and stopping the backend shows "reconnecting..." without blanking.
4. Nothing breaks at 1440x900 or 1280x720. Fonts are readable on a projector (body >= 15px, numbers in the tiles >= 28px).

Work in this order and commit after each: types + api client + mocks → page layout + header/tiles → queue → step log → case panel + claim card → map → polish/empty/error states. Ask before adding routes, auth, or anything not listed here.
