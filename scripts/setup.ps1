# Windows equivalent of setup.sh
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv .venv
$py = ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -e packages/version-engine -e packages/semantic-diff -e packages/risk-engine `
  -e packages/policy-engine -e packages/provenance -e packages/sandbox -e packages/merge-engine `
  -e packages/agent-sdk -e "apps/api[postgres,s3]" -e apps/agent-runtime -e apps/cli pytest pytest-asyncio
Push-Location apps/web; npm install --no-audit --no-fund; Pop-Location
Write-Host "done. activate with: .venv\Scripts\Activate.ps1"
