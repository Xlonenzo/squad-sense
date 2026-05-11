# Squad Sense — script da demo do Bloco 1 (Mock).
#
# Roda da Cena 5 em diante: bootstrap -> seed -> ingest -> agent -> post-comments.
# Cada etapa pausa antes da proxima pra voce narrar.
#
# Pre-requisitos:
#   1. .env com JIRA_MOCK=true
#   2. uvicorn reiniciado APOS trocar a env (uv run uvicorn app.main:app --reload)
#   3. Postgres up (docker compose up -d)
#   4. Opcional: .\scripts\reset.ps1 antes pra zerar estado anterior

param(
    [string]$BaseUrl = "http://localhost:8000"
)

function Show-Header($title) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
}

function Wait-ForNext($label) {
    Write-Host ""
    Write-Host "[Enter para $label]  " -ForegroundColor Yellow -NoNewline
    [void][System.Console]::ReadLine()
}

function Invoke-Step($method, $path, $label) {
    Show-Header "$label  --  $method $path"
    try {
        $response = Invoke-RestMethod -Method $method -Uri "$BaseUrl$path" -ErrorAction Stop
        $response | ConvertTo-Json -Depth 6
    } catch {
        Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Sanity check: confirma que a app esta em modo mock
Write-Host ""
Write-Host "Squad Sense Demo - BLOCO 1 (Mock)" -ForegroundColor Green
Write-Host "Base URL: $BaseUrl"
Write-Host ""

try {
    $health = Invoke-RestMethod -Method "GET" -Uri "$BaseUrl/health" -ErrorAction Stop
    if ($health.jira_mock -eq $false) {
        Write-Host "AVISO: a app esta em modo REAL (JIRA_MOCK=false)." -ForegroundColor Yellow
        Write-Host "Edite .env -> JIRA_MOCK=true e reinicie uvicorn antes de continuar." -ForegroundColor Yellow
        Write-Host ""
        Wait-ForNext "continuar mesmo assim"
    }
} catch {
    Write-Host "Nao deu pra checar /health (ok se a rota nao existir). Continuando." -ForegroundColor DarkGray
}

Wait-ForNext "BOOTSTRAP do projeto"

# Cria o projeto SSD no mock (idempotente: se ja existir, retorna o existente)
Invoke-Step "POST" "/bootstrap/project" "BOOTSTRAP  (cria projeto SSD no mock)"
Wait-ForNext "SEED de 6 sprints + 39 issues"

# Planta o dataset sintetico longitudinal (P1 a P5)
Invoke-Step "POST" "/bootstrap/seed" "SEED  (6 sprints, 39 issues, 5 padroes plantados)"
Wait-ForNext "INGEST"

# Puxa do mock pro Postgres + gera embeddings
Invoke-Step "POST" "/ingest/run" "INGEST  (mock -> embeddings -> pgvector)"
Wait-ForNext "AGENT RUN"

# Pipeline completo: hygiene + mining + cross-ref + LLM
Invoke-Step "POST" "/agent/run" "AGENT RUN  (hygiene + mining + RAG + LLM)"
Wait-ForNext "POST COMMENTS via MCP"

# Posta os comments via MCP server (stdio subprocess)
Invoke-Step "POST" "/agent/post-comments" "POST COMMENTS  (MCP server stdio)"

Show-Header "BLOCO 1 CONCLUIDO"
Write-Host "Para a Cena 7 (closed loop):" -ForegroundColor Green
Write-Host "  - Lista recomendacoes:  curl $BaseUrl/agent/recommendations | jq"
Write-Host "  - Tabela direta no DB:  docker exec -it squad-sense-postgres psql -U squad -d squad_sense -c 'SELECT id, type, status, target_keys FROM recommendation;'"
Write-Host ""
