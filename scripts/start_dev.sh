#!/usr/bin/env bash
# Start the API and the web client together, and stop both on Ctrl+C.
#
#     bash scripts/start_dev.sh
#
# macOS, Linux, or Git Bash on Windows. Run it from the repository root.
# Prerequisites: backend/.venv exists, frontend/node_modules exists, and
# `python -m app.bootstrap` has been run once. See the README.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then
  echo "backend/.venv is missing. Complete the backend setup in the README first." >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "frontend/node_modules is missing. Run 'npm install' in frontend/ first." >&2
  exit 1
fi

if [ -d backend/.venv/bin ]; then
  PY="backend/.venv/bin/python"          # macOS / Linux
else
  PY="backend/.venv/Scripts/python.exe"  # Git Bash on Windows
fi

pids=()
cleanup() {
  echo
  echo "Stopping..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting the API on http://127.0.0.1:8000"
(cd backend && exec "../$PY" -m uvicorn app.main:app --reload) &
pids+=($!)

for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
  echo "The API did not become healthy. Check the output above (is PostgreSQL running?)." >&2
  exit 1
fi

echo "Starting the web client on http://localhost:5173"
(cd frontend && exec npm run dev) &
pids+=($!)

echo
echo "Both processes are running. Open http://localhost:5173"
echo "Sign in as customer@example.com / DemoPassw0rd! (or agent@example.com)"
echo "Press Ctrl+C to stop both."
wait
