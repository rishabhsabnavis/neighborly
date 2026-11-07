#!/usr/bin/env bash
# Kickoff scaffold. Generates the app from PUBLIC generators only
# (create-next-app, shadcn, uv). Safe to re-run: each step skips if already done.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

for t in node npx uv git; do
  command -v "$t" >/dev/null || { echo "missing required tool: $t" >&2; exit 1; }
done

if command -v pnpm >/dev/null; then PM=pnpm; PM_FLAG=--use-pnpm; ADD_DEV="pnpm add -D"
else PM=npm; PM_FLAG=--use-npm; ADD_DEV="npm install -D"; fi
say "package manager: $PM"

# ---------- frontend ----------
if [ ! -f frontend/package.json ]; then
  say "create-next-app -> frontend/"
  npx --yes create-next-app@latest frontend \
    --ts --app --tailwind --eslint --no-src-dir --import-alias "@/*" \
    "$PM_FLAG" --disable-git --yes
else
  say "frontend/ exists, skipping create-next-app"
fi

if [ ! -f frontend/components.json ]; then
  say "shadcn init"
  (cd frontend && npx --yes shadcn@latest init --yes --defaults)
else
  say "shadcn already initialised, skipping"
fi

if ! grep -q '"prettier"' frontend/package.json; then
  say "adding prettier (used by format hook + just fmt)"
  (cd frontend && $ADD_DEV prettier)
fi

[ -f frontend/.env.example ] || cat > frontend/.env.example <<'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF

# ---------- backend ----------
if [ ! -f backend/pyproject.toml ]; then
  say "uv init -> backend/"
  uv init --app --python 3.12 --vcs none --no-readme backend
  rm -f backend/main.py
else
  say "backend/ exists, skipping uv init"
fi

(
  cd backend
  if ! grep -q 'fastapi' pyproject.toml; then
    say "uv add backend deps"
    uv add fastapi 'uvicorn[standard]' python-dotenv httpx
    uv add --dev pytest ruff
  fi
  grep -q 'tool.pytest.ini_options' pyproject.toml || cat >> pyproject.toml <<'EOF'

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
EOF

  mkdir -p app tests
  [ -f app/__init__.py ] || : > app/__init__.py
  [ -f app/main.py ] || cat > app/main.py <<'EOF'
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI()

# Any localhost port (default frontend is :3000) + deployed origins from CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_origins=[o for o in os.getenv("CORS_ORIGINS", "").split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
EOF

  [ -f tests/test_health.py ] || cat > tests/test_health.py <<'EOF'
from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
EOF

  [ -f .env.example ] || cat > .env.example <<'EOF'
# Placeholders only. Copy to .env and fill in. Never commit .env.
# Comma-separated deployed frontend origins (localhost is always allowed)
CORS_ORIGINS=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
EOF
)

# ---------- git ----------
[ -d .git ] || { say "git init"; git init -q -b main; }
git add -A
if ! git diff --cached --quiet; then
  if git log --oneline 2>/dev/null | grep -q 'kickoff: scaffold from public generators'; then
    git commit -q -m "kickoff: re-run bootstrap"
  else
    git commit -q -m "kickoff: scaffold from public generators"
  fi
  say "committed"
else
  say "nothing new to commit"
fi

say "done. next: cp backend/.env.example backend/.env && cp frontend/.env.example frontend/.env.local && just dev"
