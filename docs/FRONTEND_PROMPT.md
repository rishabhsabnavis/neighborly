# Prompt for the frontend plumbing agent (Dev B, phase 2)

Start this once the backend's read endpoints (`/dashboard`, `/cases/{id}`, `/steps`) work, around 7pm Saturday. Designs don't block you. Paste everything below the line into your coding agent, started from the repo root.

---

You are building the **technical layer of the SafeFarm agent console** (Next.js frontend) for our HackUTD 2026 project. Read these first: `CLAUDE.md`, `docs/CONTEXT.md`, `docs/SPEC.md` (**data contracts** = the source of truth). Figma brief: https://claude.ai/artifact/7bZErNhK8kDqRttxuDaK4S.

## Who does what in `frontend/`
- **You own:** `frontend/lib/*` (types, API client, polling, mocks), `frontend/app/page.tsx` (the console), `frontend/components/map/*` (Leaflet), `frontend/components/raw/*` (temporary unstyled pieces), and all data wiring and state.
- **Designer 1 owns `frontend/components/console/*` and `frontend/app/preview/*`:** visual-only components built from her Figma frames (they draw only the props they're handed: no fetching, no global state; see the contract below). She works with a coding agent and has less dev experience. Don't edit her files. If a component needs a fix, tell her or leave a `// TODO(devB):` note in your own code. Review her PRs/pushes for prop mismatches.
- Stack: Next.js 16 App Router, TypeScript, Tailwind v4, shadcn/ui (base-ui). `npx shadcn@latest add <name>` for primitives; never hand-edit `components/ui/*`. pnpm.
- Backend URL: `process.env.NEXT_PUBLIC_API_URL` only (default `http://localhost:8000`). Never hardcode it.
- New deps: `leaflet` + `react-leaflet` + `@types/leaflet` (the county map; nothing installed does maps). Justify anything else in one line and add every dep to README.md "Built with".
- Commits: small, plain imperative messages, **no AI attribution**. Before every push, `just test && just lint && just build` must pass.

## Step 1 (first 30 min, push right away; Designer 1 depends on it)
- `frontend/lib/types.ts`: TypeScript types copied **exactly** from SPEC "Data contracts" (`Dashboard`, `PolicyholderRow`, `Case`, `Policy`, `Message`, `Call`, `Triage`, `HumanRequest`, `ClaimDraft`, `Damage`, `Step`, `Counts`). String-literal unions for enums.
- `frontend/lib/mock/`: run `just snapshot` with the backend up. It saves real responses as JSON (dashboard, every case, steps). Export typed fixtures from `frontend/lib/mock/index.ts`. These are the shared sample data for you and Designer 1. Re-run it whenever the backend seed changes.
- `frontend/lib/api.ts`: one typed function per endpoint. If `NEXT_PUBLIC_USE_MOCK=1`, serve the fixtures (fake a new step every 1.5s). Add `NEXT_PUBLIC_USE_MOCK=` to `frontend/.env.example`.
- `frontend/lib/usePoll.ts`: `usePoll(fn, ms)` that pauses when the tab is hidden, keeps the last good data on error, and exposes `{data, error, stale}`.

## Step 2: **an unstyled console that works end to end by 9pm** (`app/page.tsx` + `components/raw/*`)
Ugly is fine. It must prove the flow: a real phone texts "2", and within a few seconds it shows up here, ranked.
- Header: disaster line, the `counts` as plain numbers, a **Run check-in** button (`POST /checkins/run`, disabled while running, toast with `queued`/`live`), and Reset demo in a menu with an **in-app** confirm (**no `window.confirm`**: browser dialogs freeze our browser automation).
- Queue: rows in API order (it's already sorted), with filter tabs All / Critical / Needs help / No response / Human requested. Click = select.
- Step log: `GET /steps?since=` every 1.5s, append, keep 200, auto-scroll unless the user scrolled up.
- Case panel: a shadcn `Sheet` on the right showing `GET /cases/{id}` (poll 2s while open), with sections for policy, triage, human request, the conversation timeline (messages + calls merged by time) and the claim draft. **Call now** → `POST /policyholders/{id}/call` (toast the 502 detail on failure).
- Reconnecting: on a fetch error, keep the data on screen and show a small "Reconnecting..." badge. **Never blank the page.**
- Polling: `/dashboard` every 2s.

## Step 3: the map (`components/map/CountyMap.tsx`)
- Make `frontend/public/fl-counties.geojson` once: download `https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json`, keep features whose id starts with `12`, and mark the 15 FEMA-4955 counties (Bay, Calhoun, Escambia, Franklin, Gadsden, Gulf, Holmes, Jackson, Jefferson, Liberty, Okaloosa, Santa Rosa, Wakulla, Walton, Washington) so they can be shaded. Commit the small file and **never fetch it at runtime**.
- Load it client-only: `dynamic(() => import(...), { ssr: false })`, or `just build` breaks. OSM tiles, centered on the panhandle.
- Circle-marker pins colored by urgency/status. `live` pins get a ring, `calling` pins pulse, `human_requested` pins get a badge, the selected pin is enlarged. Click a pin = open the case.

## Step 4: swap in Designer 1's components as they land
Replace each `components/raw/*` piece with her `components/console/*` component and delete the raw one. Layout and exact styling come from Figma frames 1-2. The component contract you both code to (props only, no fetching inside):

| Component | Props |
|---|---|
| `UrgencyChip` | `urgency: 1\|2\|3\|4\|null` |
| `StatusIcon` | `status`, `channel`, `humanRequested: boolean` |
| `CountTiles` | `counts: Counts` |
| `QueueRow` | `row: PolicyholderRow`, `selected: boolean`, `onClick(): void` |
| `StepRow` | `step: Step`, `policyholderName?: string`, `onOpenCase?(id: string): void` |
| `MessageBubble` | `message: Message` |
| `CallBlock` | `call: Call` |
| `PolicyCard` | `policy: Policy` |
| `TriageCard` | `triage: Triage \| null` |
| `HumanRequestBanner` | `request: HumanRequest` |
| `ClaimDraftCard` | `claim: ClaimDraft \| null`, `onEvidenceClick?(id: string): void` |

If the contract needs to change, agree on it with Designer 1 first and then update both this table and `docs/COMPONENTS_PROMPT.md`.

## Done when (show evidence)
1. 9pm: with the real backend and a real phone, "Run check-in", then reply "2" → the row updates and the case panel shows the triage. Take a screenshot.
2. `just test`, `just lint` and `just build` exit 0.
3. Stopping the backend shows "Reconnecting..." and the data stays on screen.
4. Final: Figma-styled console at 1440x900 and 1280x720, readable on a projector (body >= 15px, tile numbers >= 28px). Take a screenshot.
