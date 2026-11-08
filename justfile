pm := `command -v pnpm >/dev/null && echo pnpm || echo npm`
vercel := `command -v vercel >/dev/null && echo vercel || echo "npx --yes vercel@latest"`
web_port := env("WEB_PORT", "3000")
api_port := env("API_PORT", "8000")

default:
    @just --list

# frontend + backend together; Ctrl-C (or either one crashing) stops both
dev:
    #!/usr/bin/env bash
    for p in {{web_port}} {{api_port}}; do
      if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then
        echo "port $p is already in use (lsof -iTCP:$p). Free it or run e.g. API_PORT=8001 WEB_PORT=3001 just dev" >&2
        exit 1
      fi
    done
    trap 'kill 0' EXIT INT TERM
    just api & API=$!
    just web & WEB=$!
    while kill -0 $API 2>/dev/null && kill -0 $WEB 2>/dev/null; do sleep 1; done
    echo "a server exited; stopping both" >&2
    exit 1

web:
    cd frontend && {{ if env("API_PORT", "") != "" { "NEXT_PUBLIC_API_URL=http://localhost:" + api_port } else { "" } }} {{pm}} run dev --port {{web_port}}

api:
    cd backend && uv run uvicorn app.main:app --reload --port {{api_port}}

test:
    cd backend && uv run pytest -q
    cd frontend && npx tsc --noEmit

lint:
    cd backend && uv run ruff check . && uv run ruff format --check .
    cd frontend && {{pm}} run lint

fmt:
    cd backend && uv run ruff check --fix . && uv run ruff format .
    cd frontend && npx prettier --write .

build:
    cd frontend && {{pm}} run build

# public URL for the frontend (wifi fallback for the demo)
tunnel:
    cloudflared tunnel --url http://localhost:{{web_port}}

deploy:
    cd frontend && {{vercel}} --prod

# ---- first-hour spikes (keys go in spikes/.env) ----
spike-nemotron:
    uv run spikes/nemotron_tools.py

spike-photon-v1:
    cd spikes/photon && {{pm}} install --silent && npx tsx echo.ts

# voice webhook on :8010; expose with: cloudflared tunnel --url http://localhost:8010
spike-voice:
    uv run spikes/voice_webhook.py

spike-photon-out:
    cd spikes/photon && {{pm}} install --silent && npx tsx outbound.ts

spike-call:
    uv run spikes/call_outbound.py

# Photon 2.0 (beta) iMessage: assign line, echo, unprompted follow-up
spike-photon:
    uv run spikes/photon_beta.py

# Photon number -> ElevenLabs agent (re-runnable). Needs ELEVENLABS_API_KEY in backend/.env
voice-setup:
    PYTHONUNBUFFERED=1 uv run spikes/voice_setup.py

# save live backend responses as frontend mock fixtures (backend must be running; API_PORT=8001 if needed)
snapshot:
    #!/usr/bin/env bash
    set -euo pipefail
    base="http://localhost:{{api_port}}"
    out=frontend/lib/mock
    mkdir -p "$out/cases"
    curl -sf "$base/dashboard" | jq . > "$out/dashboard.json"
    curl -sf "$base/steps" | jq . > "$out/steps.json"
    for id in $(jq -r '.policyholders[].id' "$out/dashboard.json"); do
      curl -sf "$base/cases/$id" | jq . > "$out/cases/$id.json"
    done
    echo "snapshot: $(ls "$out/cases" | wc -l | tr -d ' ') cases -> $out"

# outbound call spike: Photon SIP -> ElevenLabs agent with case context (--setup = no call)
voice-outbound *args:
    PYTHONUNBUFFERED=1 uv run spikes/voice_outbound.py {{args}}

# Nemotron claim-draft + policy-aware follow-up quality (SPEC risk #2)
spike-claim:
    PYTHONUNBUFFERED=1 uv run spikes/nemotron_claim.py

# voice demo rehearsal through the real backend modules (costs ElevenLabs credits per call)
voice-rehearse *args:
    cd backend && PYTHONUNBUFFERED=1 uv run python ../spikes/voice_rehearse.py {{args}}
