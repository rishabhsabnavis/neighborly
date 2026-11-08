# Prompt for Designer 1: build the console components from Figma

**When:** after your Figma frames 1 (main console) and 2 (case panel) are shared, and once Dev B has pushed `frontend/lib/types.ts` and `frontend/lib/mock/`. Ask him if they're not there yet.

**Setup (once, ask Dev B or the owner for help):** clone the repo, run `git pull`, then `just dev` (or `cd frontend && pnpm dev`) and open http://localhost:3000/preview. Start your coding agent (Claude Code) in the repo folder and paste everything below the line. Attach screenshots of your Figma frames, or give it Figma links if it has the Figma connector.

---

You are helping a UI/UX designer, who has limited coding experience, turn her Figma designs into **visual-only React components** for the Neighborly agent console (HackUTD 2026). Explain what you're doing in plain words, keep changes small, and show her the result in the browser after each component.

Read first: `CLAUDE.md` and `docs/SPEC.md` ("Data contracts" section only). Figma brief: https://claude.ai/artifact/7bZErNhK8kDqRttxuDaK4S.

## Rules (important: there are strict boundaries)
- **Only create or edit files in `frontend/components/console/` and `frontend/app/preview/`.** Don't touch anything else, especially not `frontend/lib/*`, `frontend/app/page.tsx`, `frontend/components/ui/*` (shadcn, never hand-edited), or anything in `backend/`. If something outside these folders seems to need changing, stop and tell her to ask Dev B.
- Components are **visual-only**: they render the props they're handed. No `fetch`, no API calls, no global state, no timers (local hover/expand state is fine). Types come from `@/lib/types`, and sample data from `@/lib/mock`.
- Stack: Next.js + TypeScript + Tailwind v4 + shadcn/ui. Use existing shadcn primitives (Card, Badge, Table, Tabs, Tooltip, ScrollArea). If one is missing, `npx shadcn@latest add <name>` is allowed. Icons: `lucide-react` (already installed). **No new npm packages.**
- Colors and sizes as Tailwind theme tokens (CSS variables in a `console-theme.css` inside `components/console/`, imported by the components), matching her Figma variables. Urgency: 4 red "Critical", 3 orange "High", 2 amber "Moderate", 1 green "Safe", no response gray, calling blue (pulsing), human requested purple. Always show the text label too, never color alone.
- Projector-readable: body >= 15px, tile numbers >= 28px, step log >= 13px monospace.
- Commit after each working component with a plain message like `ui: add QueueRow`. **No AI attribution** in commits. Before every push, `just build` and `just lint` must pass. If they fail, fix the problem or ask Dev B. **Never push a failing build.**

## The components (build in this order; the props are fixed, so Dev B is coding against them)
| # | Component | Props |
|---|---|---|
| 1 | `UrgencyChip` | `urgency: 1\|2\|3\|4\|null` |
| 2 | `StatusIcon` | `status`, `channel`, `humanRequested: boolean` |
| 3 | `QueueRow` | `row: PolicyholderRow`, `selected: boolean`, `onClick(): void` |
| 4 | `CountTiles` | `counts: Counts` |
| 5 | `StepRow` | `step: Step`, `policyholderName?: string`, `onOpenCase?(id: string): void` |
| 6 | `MessageBubble` | `message: Message` (agent, policyholder and voice-agent styles, channel icon) |
| 7 | `CallBlock` | `call: Call` (reason, status, duration, summary; expandable) |
| 8 | `PolicyCard` | `policy: Policy` (dollar amounts formatted, vulnerability notes highlighted) |
| 9 | `TriageCard` | `triage: Triage \| null` (null = an empty state) |
| 10 | `HumanRequestBanner` | `request: HumanRequest` |
| 11 | `ClaimDraftCard` | `claim: ClaimDraft \| null`, `onEvidenceClick?(id: string): void` (damages table, missing-info checklist, Draft/Confirmed badge; null = "No claim yet. The agent drafts one once it has enough detail.") |

One file per component: `frontend/components/console/QueueRow.tsx` and so on, each a named export.

## Preview page (`frontend/app/preview/page.tsx`)
A page that shows every component with mock data, in several states: each urgency, calling, human requested, an empty claim, a confirmed claim, and Maria Lopez's full case (`ph_017`). This is where she checks her work against Figma, side by side.

## Done when (for each component)
1. It looks like the Figma frame on http://localhost:3000/preview. Take a screenshot.
2. `just build` and `just lint` exit 0.
3. It's committed and pushed, and Dev B has been told it's ready to wire in.
