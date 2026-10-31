#!/usr/bin/env bash
# Run the API (port 8000) and the dashboard (port 3000) for local development.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/uvicorn ]; then UV=.venv/bin/uvicorn; else UV=.venv/Scripts/uvicorn.exe; fi
FORGEFLOW_DATA_DIR=${FORGEFLOW_DATA_DIR:-.forgeflow} $UV forgeflow_api.main:create_app --factory --reload --port 8000 &
API=$!
trap 'kill $API' EXIT
(cd apps/web && npm run dev)
