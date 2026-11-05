<#
.SYNOPSIS
  Windows-friendly equivalent of the Makefile (no GNU make needed).

.EXAMPLE
  .\scripts\dev.ps1 setup      # uv sync + corepack/pnpm install
  .\scripts\dev.ps1 dev        # whole stack in Docker
  .\scripts\dev.ps1 help
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('help', 'env', 'setup', 'dev', 'up', 'down', 'logs', 'ps', 'dev-local',
               'dev-local-demo', 'test', 'lint', 'seed-demo', 'sandbox', 'observability',
               'clean-volumes')]
  [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Native {
  # Run a native command and stop on a non-zero exit code.
  $exe = $args[0]
  $rest = @($args | Select-Object -Skip 1)
  & $exe @rest
  if ($LASTEXITCODE -ne 0) { throw "'$($args -join ' ')' failed with exit code $LASTEXITCODE" }
}

function Use-Venv {
  # Put the uv virtual environment first on PATH so the Python dev servers resolve to it.
  if (-not (Test-Path .venv)) { throw 'No .venv found: run .\scripts\dev.ps1 setup first.' }
  $env:PATH = "$PWD\.venv\Scripts;$env:PATH"
}

function Ensure-Env {
  # Creates .env with RANDOM local-dev secrets (scripts/gen_dev_env.py); never overwrites.
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $py) { throw 'Python is required to create .env (python or py not on PATH).' }
  Invoke-Native $py.Source scripts/gen_dev_env.py --env-file .env
}

# `dev` layers docker-compose.dev.yml (RADIUS_ENV=development, localhost CORS, auto-verify,
# logged sign-in links, one random dev API key) over the production-like docker-compose.yml.
$ComposeDev = @('compose', '--env-file', '.env', '-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml')

switch ($Target) {
  'help' {
    @'
Targets (same names as the Makefile):
  env              create .env for LOCAL DEV with random secrets if missing
  setup            uv sync + corepack enable + pnpm install
  dev              ONE COMMAND: postgres, migrations, api, worker, dashboard in Docker
  down | logs | ps stop / follow logs / status
  dev-local        api + worker + dashboard natively with hot reload (memory storage)
  dev-local-demo   same, with OPT-IN demo data (illustrative fixtures + demo login)
  test | lint      pytest / ruff
  seed-demo        OPT-IN demo data into the SQL database (DEMO ONLY)
  sandbox          build the sandbox test image (compose profile: sandbox)
  observability    Jaeger + Prometheus (compose profile: observability)
  clean-volumes    DESTRUCTIVE: delete the database volume
'@ | Write-Host
  }
  'env' { Ensure-Env }
  'setup' {
    Ensure-Env
    Invoke-Native uv sync --frozen --extra dev
    try { Invoke-Native corepack enable }
    catch { Write-Warning "corepack enable failed (EPERM without admin rights?). See 'Windows notes' in docs/DEVELOPMENT_GUIDE.md; continuing if pnpm is already on PATH." }
    Invoke-Native pnpm install --frozen-lockfile
  }
  { $_ -in 'dev', 'up' } {
    Ensure-Env
    Invoke-Native docker @ComposeDev up --build -d --wait --wait-timeout 300 postgres migrations api worker dashboard
    Write-Host ''
    Write-Host 'LOCAL DEV stack (RADIUS_ENV=development). Sign-in links are printed in the api log: .\scripts\dev.ps1 logs'
    Write-Host 'Dashboard http://localhost:3000   API http://localhost:8000/docs   Health http://localhost:8000/api/v1/health'
    Write-Host 'Logs: .\scripts\dev.ps1 logs   Stop: .\scripts\dev.ps1 down'
  }
  'down' { Invoke-Native docker @ComposeDev --profile sandbox --profile observability down }
  'logs' { Invoke-Native docker @ComposeDev logs -f api worker dashboard }
  'ps' { Invoke-Native docker @ComposeDev ps }
  'dev-local' { Ensure-Env; Use-Venv; Invoke-Native pnpm dev }
  'dev-local-demo' {
    Ensure-Env
    $env:RADIUS_SEED_DEMO_DATA = 'true'
    Use-Venv
    Invoke-Native pnpm dev
  }
  'test' { Invoke-Native uv run --frozen python -m pytest }
  'lint' { Invoke-Native uv run --frozen python -m ruff check . }
  'seed-demo' {
    $env:STORAGE_BACKEND = 'sql'
    $pgPort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { '5432' }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
    $env:DATABASE_URL = (& $py.Source scripts/gen_dev_env.py --env-file .env --print-database-url $pgPort)
    Invoke-Native uv run --frozen python scripts/seed_demo.py --yes
  }
  'sandbox' { Invoke-Native docker compose --profile sandbox up --build sandbox-image }
  'observability' { Invoke-Native docker compose --profile observability up jaeger prometheus }
  'clean-volumes' { Invoke-Native docker @ComposeDev --profile sandbox --profile observability down -v }
}
