# SPEC: <project name>

> Fill this in with /spec at kickoff. Keep it to one screen. If it's not in here, we're not building it.

## Problem
<One sentence.> **Who has it:** <specific person/role>, who today copes by <current workaround>.

## Target tracks / prizes
| Track or prize | What judges want | Sponsor tech required | How we qualify |
|---|---|---|---|
| | | | |

## 2-minute demo script
1. (0:00-0:20) Problem: <person + pain>
2. (0:20-0:35) Solution: <one sentence>
3. (0:35-1:30) Live demo: <happy-path steps; mark the wow moment>
4. (1:30-1:45) Impact: <who benefits, how much>
5. (1:45-2:00) Tech: <stack + hardest problem solved>

## MVP features (max 3)
1. <feature>: <what the user does> -> <what they see>
2.
3.

## Not doing
- <tempting feature we're explicitly skipping>
- Auth / accounts (unless the demo needs it)
- Mobile app, settings pages, admin panels

## Architecture and data flow
```
[Browser: Next.js] --fetch--> [FastAPI :8000] --> [<external API / model / DB>]
        ^                              |
        +---------- JSON --------------+
```
<1-3 sentences: where state lives, what's seeded vs live, what's mocked.>

## Data contracts
### `POST /<endpoint>`
Request:
```json
{}
```
Response 200:
```json
{}
```
Errors: `4xx {"detail": "..."}`

## Riskiest part (test first)
<The thing most likely to sink the demo: unknown API, model quality, latency, data access.>
**Spike:** <smallest experiment that proves it works>. **Fallback if it fails:** <plan B>.

## Verification
| Feature | Pass/fail check |
|---|---|
| Backend up | `curl localhost:8000/health` returns `{"status":"ok"}` |
| | |
| Deployed | production URL returns 200 and the happy path works there |
