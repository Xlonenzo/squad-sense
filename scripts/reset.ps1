# Squad Sense — reset entre takes da demo.
#
# Zera:
#   - tabelas do Postgres (recommendation, issue_embedding, issue, sprint, project)
#   - data/mock_jira.json (Bloco 1)
#
# NAO mexe nos comments do Jira real. Pra limpar SSDEMO, ver instrucoes
# no fim deste script (ou rode o painel /admin do Atlassian).
#
# Uso:
#   .\scripts\reset.ps1            # reseta DB e mock
#   .\scripts\reset.ps1 -DbOnly    # so o DB
#   .\scripts\reset.ps1 -MockOnly  # so o mock

param(
    [switch]$DbOnly,
    [switch]$MockOnly
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$MockPath = Join-Path $ProjectRoot "data\mock_jira.json"

function Reset-Database {
    Write-Host ""
    Write-Host "=== Resetando Postgres (squad-sense-postgres) ===" -ForegroundColor Cyan

    $sql = @"
TRUNCATE TABLE
    recommendation,
    issue_embedding,
    issue,
    sprint,
    project
RESTART IDENTITY CASCADE;
"@

    docker exec -i squad-sense-postgres psql -U squad -d squad_sense -c $sql
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: docker exec falhou. O container squad-sense-postgres esta rodando?" -ForegroundColor Red
        Write-Host "Tente: docker compose up -d" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Postgres limpo." -ForegroundColor Green
}

function Reset-Mock {
    Write-Host ""
    Write-Host "=== Resetando mock_jira.json ===" -ForegroundColor Cyan
    if (Test-Path $MockPath) {
        Remove-Item $MockPath -Force
        Write-Host "Removido: $MockPath" -ForegroundColor Green
    } else {
        Write-Host "Mock ja estava limpo." -ForegroundColor Yellow
    }
}

if ($MockOnly) {
    Reset-Mock
} elseif ($DbOnly) {
    Reset-Database
} else {
    Reset-Database
    Reset-Mock
}

Write-Host ""
Write-Host "PROXIMOS PASSOS para re-rodar a demo:" -ForegroundColor Yellow
Write-Host "  1. Bloco 1 (mock): .\scripts\bootstrap-mock.ps1  ou  curls de bootstrap+seed"
Write-Host "  2. Bloco 2 (Jira real): .\scripts\demo.ps1  (issues SSDEMO ja existem no Atlassian)"
Write-Host ""
Write-Host "Atencao - comments no Jira real (SSDEMO):" -ForegroundColor Yellow
Write-Host "  Este script NAO apaga comments postados em SSDEMO-1..6 anteriormente."
Write-Host "  Pra limpar manualmente: abra cada issue no Atlassian e delete os comments do bot."
Write-Host "  Ou rode: .\scripts\delete-jira-comments.ps1 (se existir)."
Write-Host ""
