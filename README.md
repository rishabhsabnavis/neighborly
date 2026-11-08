# Neighborly (disaster check-in agent)

Neighborly is a check-in and claim-starting agent for State Farm policyholders. Our demo uses Hurricane Isaias (FEMA declaration 4955, fifteen Florida panhandle counties). A coordinator clicks "Run check-in," and every opted-in policyholder in the zone gets an iMessage: reply 1 for Safe, 2 for Need help, 3 for Emergency, 4 for Call me, 0 to talk to a person.

**Live demo:** https://neighborly-ecru-two.vercel.app/  · **Video:**  · **Devpost:** https://devpost.com/software/neighborly-p5zh8b?ref_content=user-portfolio&ref_feature=in_progress 

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
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic, python-dotenv, httpx, fpdf2 |
| Tooling | uv, pnpm, Ruff, Prettier, ESLint, pytest, just, PostCSS (@tailwindcss/postcss) |
| Hosting | Vercel, Railway, Docker, Cloudflare Tunnel |
| APIs / AI | NVIDIA Nemotron (nemotron-3.5-super-vl, nemotron-3.5-lightning), OpenFEMA API, OpenStreetMap tiles, plotly county GeoJSON |
| Sponsor tech | NVIDIA Nemotron, Photon 2.0 (photonhq-api Python SDK: iMessage + Voice SIP), ElevenLabs Agents |
| Dev assistance | Claude Code |

##Inspiration
The three of us grew up in Dallas in close enough proximity to watch hurricanes tear through Houston and other surrounding areas. Whether it was Hurricane Harvey or Katrina, we know people who were personally affected, and we’ve seen how one disaster can upend a family’s life for years. When we were discussing which prompt to choose, this one specifically felt personal, and it was a problem where a small team could make an actual difference.
Our research showed that current insurer outreach after a catastrophe mostly is along the lines of “file a claim when it’s safe.” We wanted to create the connecting piece. Get a person help first, then use that same conversation for their claim, so nobody sits on hold or has to retell the worst day of their life.

##What it does
Neighborly is a check-in and claim-starting agent for State Farm policyholders. Our demo uses Hurricane Isaias (FEMA declaration 4955, fifteen Florida panhandle counties). A coordinator clicks "Run check-in," and every opted-in policyholder in the zone gets an iMessage: reply 1 for Safe, 2 for Need help, 3 for Emergency, 4 for Call me, 0 to talk to a person.
Each number triggers something different. A 1 closes the case. A 2 starts a conversation where the agent already knows the person's policy and asks up to two follow-ups, like whether their home is damaged and whether they need somewhere to stay, quoting their actual hotel coverage. A 3 texts "call 911 now," marks the case top priority, and places a short safety-only call. A 4, or 60 seconds of silence, makes a voice agent call them, and it already knows what they told us by text. A 0 puts them at the top of a human agent's queue.
Everything the person says by text or voice goes into one case record. From that record the agent drafts a claim (damaged items, matching coverage, hotel needs, medical flags like a parent on oxygen) and texts the person a claim number to confirm with YES. A coordinator console shows a county map with urgency-colored pins, a queue of policyholders ranked on risk level, the full conversation and claim draft for each case, and a live log of every step the AI took.

##How we built it
Photon runs every point of contact with the policyholder. The iMessage API makes the thread interactive, so each reply sets off an action. Photon's voice line handles the calls: when someone replies 4 or goes quiet, our server places an outbound call over Photon SIP to an ElevenLabs voice agent, along with the person's name and case so far, so it opens with context. The transcript then merges back into the same case, which makes text and voice feel like one conversation.
NVIDIA Nemotron does the thinking. A larger model plans each case, calls tools, and writes the claim draft, and a smaller, faster one rates every reply for urgency from 1 to 4. The backend is FastAPI and the console is Next.js. All policies and policyholders are synthetic, layered onto the real FEMA declaration, and nothing connects to a real State Farm system.

##What we learned
Our biggest lesson was to think like the company, not like a first responder. It was tempting to try to do the job of 911 and on-the-ground rescue, but State Farm’s core role in a disaster is the claim: helping policyholders recover as painlessly as possible. Because of this, we pivoted from trying to dispatch help. Instead, in an emergency, our agent tells the person to call 911, flags a human, and keeps things focused on safety. Everything else is aimed at what an insurer does best, which is starting the claim early and accurately.
We also learned how much the customer experience matters in the worst moment of someone’s life. People want to feel heard and cared for, not processed, so we put a lot of our time into the UI, from the simple one-number text menu to the coordinator console, so nobody has to retell their story.

##Challenges
One of our biggest challenges was ideating. The prompt was extremely broad, so we had to find an idea that was both feasible and unique while still addressing the root of the problem. Designing for someone in crisis was the other big one. At most hackathons you can assume users can work an app, but a person in a disaster may have a dying battery and no patience for a screen full of buttons. To address this, we really honed in on putting ourselves in the shoes of the user. We tried to make the experience as simple but accommodating as possible. Our final challenge was navigating the new set of tools including Photon and Nemotron which we eventually figured out through research and trial and error.

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
