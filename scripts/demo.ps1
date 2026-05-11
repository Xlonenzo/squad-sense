# Squad Sense — script de demo com pausas controladas.
#
# Uso:
#   .\scripts\demo.ps1
#
# Cada etapa pausa antes da proxima. Voce aperta Enter quando estiver pronto
# pra narrar a proxima parte. ESC ou Ctrl+C aborta.
#
# Pre-requisitos:
#   - uvicorn rodando em http://localhost:8000
#   - Postgres up (docker compose up -d)
#   - .env configurado (JIRA_MOCK=true ou false conforme o bloco)
#   - Para Bloco 1 (mock): rode antes /bootstrap/project e /bootstrap/seed

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

Write-Host ""
Write-Host "Squad Sense Demo" -ForegroundColor Green
Write-Host "Base URL: $BaseUrl"
Write-Host "Olhe o painel do uvicorn pros logs do structlog em tempo real."
Wait-ForNext "iniciar"

# Etapa 1 - Ingestao
Invoke-Step "POST" "/ingest/run" "INGEST  (REST -> embeddings -> pgvector)"
Wait-ForNext "AGENT RUN"

# Etapa 2 - Agente
Invoke-Step "POST" "/agent/run" "AGENT RUN  (hygiene + mining + RAG + LLM)"
Wait-ForNext "POST COMMENTS via MCP"

# Etapa 3 - Posta comentarios via MCP
Invoke-Step "POST" "/agent/post-comments" "POST COMMENTS  (MCP server stdio)"

Show-Header "DEMO CONCLUIDA"
Write-Host "Abra o Jira e veja os comentarios postados pelo bot." -ForegroundColor Green
Write-Host ""
