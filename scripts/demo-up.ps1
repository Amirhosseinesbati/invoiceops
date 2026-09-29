param([switch]$ActivateWorkflows)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        $python = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
        & $python scripts/init_env.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not initialize .env' }
    }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed' }
    if ($ActivateWorkflows) {
        $python = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
        & $python scripts/bootstrap_workflows.py import --activate-demo
        if ($LASTEXITCODE -ne 0) { throw 'Workflow activation failed; initialize the local n8n owner and retry' }
    }
    $webPort = '8080'
    $n8nPort = '5678'
    foreach ($line in Get-Content -LiteralPath '.env') {
        if ($line -match '^WEB_HOST_PORT=(\d+)\s*$') { $webPort = $Matches[1] }
        if ($line -match '^N8N_HOST_PORT=(\d+)\s*$') { $n8nPort = $Matches[1] }
    }
    Write-Output "Portal: http://127.0.0.1:$webPort  |  n8n: http://127.0.0.1:$n8nPort"
} finally {
    Pop-Location
}
