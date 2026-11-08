# <Project name> (State Farm disaster check-in agent)

> <One-line pitch: what it does, for whom.>

**Live demo:** <deployed URL> · **Video:** <YouTube/Loom link> · **Devpost:** <link>

![demo](<path or URL to GIF/screenshot>)

## What it does
<2-4 sentences. The problem, who has it, and what our project lets them do.>

## How we built it
<Architecture in a few sentences: Next.js frontend talks to a FastAPI backend, which ... Include the diagram from SPEC.md if useful.>

## Built with
Every framework, library, API, and service used (hackathon rule: keep this complete).

| Category | Tech |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, Leaflet, React Leaflet |
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic, python-dotenv, httpx |
| Tooling | uv, pnpm, Ruff, Prettier, ESLint, pytest, just, PostCSS (@tailwindcss/postcss) |
| Hosting | Vercel, Cloudflare Tunnel |
| APIs / AI | NVIDIA Nemotron (nemotron-3.5-super-vl, nemotron-3.5-lightning), OpenFEMA API, OpenStreetMap tiles, plotly county GeoJSON |
| Sponsor tech | NVIDIA Nemotron, Photon 2.0 (photonhq-api Python SDK: iMessage + Voice SIP), ElevenLabs Agents |
| Dev assistance | Claude Code |

## Challenges we ran into
-

## Accomplishments we're proud of
-

## What we learned
-

## What's next
-

## How to run
Prereqs: Node LTS, pnpm, uv, just.
```bash
git clone <repo> && cd <repo>
cp backend/.env.example backend/.env        # fill in keys
cp frontend/.env.example frontend/.env.local
(cd frontend && pnpm install) && (cd backend && uv sync)
just dev    # http://localhost:3000 (frontend), http://localhost:8000/health (backend)
just test
```

## Team
| Name | Role | GitHub |
|---|---|---|
| | | |
