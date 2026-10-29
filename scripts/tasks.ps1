# Windows equivalent of the Makefile (no `make` needed):  .\scripts\tasks.ps1 <task>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("setup", "corpus", "index", "test", "live", "run")]
    [string]$Task
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = ".venv\Scripts\python.exe"

switch ($Task) {
    "setup" {
        python -m venv .venv
        & $py -m pip install -e ".[dev]"
        if (-not (Test-Path .env)) { Copy-Item .env.example .env }
    }
    "corpus" { & $py -m scripts.fetch_corpus }
    "index"  { & $py -m scripts.build_index }
    "test" {
        New-Item -ItemType Directory -Force results | Out-Null
        & $py -m pytest --cov=app --cov-report=term-missing | Tee-Object results\coverage.txt
    }
    "live"   { & $py -m pytest -m live -v }
    "run"    { & $py -m uvicorn app.main:app --reload }
}
