#!/usr/bin/env bash
# Create a virtualenv and install every ForgeFlow package in editable mode, plus the web app.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
$PY -m venv .venv
if [ -x .venv/bin/python ]; then VPY=.venv/bin/python; else VPY=.venv/Scripts/python.exe; fi
$VPY -m pip install --upgrade pip
$VPY -m pip install -e packages/version-engine -e packages/semantic-diff -e packages/risk-engine \
  -e packages/policy-engine -e packages/provenance -e packages/sandbox -e packages/merge-engine \
  -e packages/agent-sdk -e "apps/api[postgres,s3]" -e apps/agent-runtime -e apps/cli \
  pytest pytest-asyncio
(cd apps/web && npm install --no-audit --no-fund)
echo "done. activate with: source .venv/bin/activate  (Windows: .venv\Scripts\activate)"
