# Squad Sense - popula o banco do zero, sem pausa.
#
# Pre-requisitos:
#   - Docker Desktop ligado e `docker compose up -d` rodando
#   - uvicorn de pe (uv run uvicorn app.main:app --reload)
#   - .env com JIRA_MOCK=true

param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

function Invoke-Step($label, $method, $path) {
    Write-Host ""
    Write-Host ">>> $label" -ForegroundColor Cyan
    Write-Host "    $method $BaseUrl$path" -ForegroundColor DarkGray
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -Method $method -Uri "$BaseUrl$path"
        $sw.Stop()
        Write-Host "    ok ($([int]$sw.Elapsed.TotalSeconds)s)" -ForegroundColor Green
        return $response
    } catch {
        $sw.Stop()
        Write-Host "    FALHOU: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Squad Sense - seed completo" -ForegroundColor Green
Write-Host "Base URL: $BaseUrl"

try {
    $health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
    if ($health.jira_mock -eq $false) {
        Write-Host "AVISO: app esta em modo REAL (JIRA_MOCK=false). Esse script e do mock." -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "API nao respondeu em $BaseUrl/health. Sobe o uvicorn antes." -ForegroundColor Red
    exit 1
}

Invoke-Step "Bootstrap do projeto SSD"      "POST" "/bootstrap/project"  | Out-Null
Invoke-Step "Seed (6 sprints, 39 issues)"   "POST" "/bootstrap/seed"     | Out-Null
Invoke-Step "Ingest (mock -> pgvector)"     "POST" "/ingest/run"         | Out-Null
$agent = Invoke-Step "Agent run (hygiene + mining + LLM)" "POST" "/agent/run"

Write-Host ""
Write-Host "Pronto. Recarrega o frontend." -ForegroundColor Green
if ($agent) {
    Write-Host ("Recomendacoes geradas: {0}" -f $agent.recommendations_total) -ForegroundColor Green
}
