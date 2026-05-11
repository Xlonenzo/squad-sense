# Squad Sense

Agente de IA para squads ágeis que **mantém o backlog calibrado e ensina o time com base no histórico**. Combina hygiene contínua (dedup, obsolescência, DoR, epic emergente) com pattern mining longitudinal (subestimação, carryover) e cruza os dois sinais para coaching real:

> "Esta issue ativa o cluster *integração + joão.dev* onde a estimativa final saiu em **2.1× a inicial** nas últimas 4 entregas (SSD-6, SSD-9, SSD-12, SSD-18). A atual está em 5pts. Considere revisar antes da daily ou fazer split em 'descoberta da API' + 'integração'."

Entregue como MVP do teste técnico **AI Agile Transformation Consultant**.

---

## O problema

Squads ágeis acumulam dívida silenciosa em três planos:

1. **Backlog vira lixeira semântica** — duplicatas escritas com palavras diferentes, issues obsoletas que ninguém arquiva, escopo emergente fragmentado em N issues soltas sem epic.
2. **Estimativa não aprende com o passado** — o time tem histórico de subestimar certos tipos de trabalho (integrações, tech-debt) mas isso vive na cabeça das pessoas, não numa ferramenta.
3. **Refinamento manual não escala** — PO/SM gasta horas semanais fazendo o que dá pra automatizar (dedup óbvio, DoR check, agrupamento por tema).

A maioria dos "AI assistants" para squads é wrapper de LLM: cospe sugestões genéricas sem saber se o time já viu aquele padrão antes. **Squad Sense é diferente**: detecção é algorítmica (embeddings, SQL, pattern mining), narração é LLM, e cada recomendação cita evidência específica do histórico do time. Sem alucinação opaca.

---

## Como o agente resolve

```
        ┌─────────────────────────────┐
        │ Jira (Cloud real ou mock)   │
        └──────────────┬──────────────┘
                       │ /ingest/run
                       ▼
        ┌─────────────────────────────┐
        │ Postgres + pgvector         │  embeddings text-embedding-3-small
        └──────────────┬──────────────┘
                       │ /agent/run
                       ▼
   ┌───────────────────────────────────────────┐
   │  Coach Agent — pipeline multi-step        │
   │                                            │
   │  Hygiene Pass         Pattern Mining       │
   │  ─────────────        ────────────────     │
   │  • dedup (pgvector)   • subestimação       │
   │  • obsoletas          • carryover          │
   │  • DoR violation                           │
   │  • epic emergente                          │
   │           ↓                ↓               │
   │       Cross-Reference (issue × pattern)    │
   │                  ↓                         │
   │       RAG (puxa evidência histórica)       │
   │                  ↓                         │
   │       LLM Synthesis (Claude Sonnet 4.6     │
   │                  / GPT-4o-mini)            │
   │                  ↓                         │
   │     recommendation table (proposed)        │
   └───────────────────┬───────────────────────┘
                       │ /agent/post-comments
                       ▼
        ┌─────────────────────────────┐
        │ MCP Server (stdio, Python)  │
        │   tools: get_issue,         │
        │          add_comment,       │
        │          list_comments      │
        └──────────────┬──────────────┘
                       │
                       ▼
        ┌─────────────────────────────┐
        │ Comentário aparece na issue │
        │ → squad responde ss-skip    │
        │   ou ignora ou aceita       │
        └──────────────┬──────────────┘
                       │ feedback fechando o loop
                       ▼
            recommendation.status = accepted | rejected
```

**Princípio não-negociável:** o agente **propõe, não executa**. Toda finding vira comentário no Jira. O squad decide. Issues nunca são apagadas/fechadas pelo agente. [Detalhe](#autonomia--propor-não-executar).

---

## Status — MVP completo

| Etapa | Entrega |
|---|---|
| 1 | Backend FastAPI + JiraClient com toggle REST real ↔ Mock + bootstrap + seed sintético |
| 2 | Postgres + pgvector + ingestion job + EmbeddingClient (OpenAI/Voyage/Null) |
| 3a | Hygiene Pass: 4 detectores algorítmicos (dedup, obsoleta, DoR, epic emergente) |
| 3b | Pattern Mining + cross-reference + Coach Agent (LLM com RAG e prompt caching) + closed loop (recommendation table) |
| 3c | **MCP server real** (Python SDK, stdio) + `JiraMCPClient` com lifecycle de subprocess + comments postados via tools MCP |

**Demo validado em duas frentes:**
- **Mock**: 6 sprints + 39 issues + 5 padrões plantados → 31 recommendations, 29 comments, todos os patterns detectados
- **Jira Cloud real** (`xlontest.atlassian.net`): 6 issues criadas → 8 findings → 8 comments postados via MCP → visíveis na UI

---

## Pré-requisitos

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) (gerenciador de deps)
- Docker Desktop (Postgres + pgvector)
- (Opcional) Conta Atlassian Cloud + API token — só para o modo real
- (Opcional) `OPENAI_API_KEY` — sem chave, embeddings caem em zeros e LLM em texto canônico (pipeline ainda roda)
- (Opcional) `ANTHROPIC_API_KEY` — alternativa preferida ao OpenAI para síntese LLM

## Instalação

```powershell
# 1. Deps Python
uv sync

# 2. Variáveis de ambiente
copy .env.example .env
# Edite .env (ver seção Configuração abaixo)

# 3. Postgres + pgvector
docker compose up -d

# 4. Schema
uv run alembic upgrade head
```

## Rodar

```powershell
uv run uvicorn app.main:app --reload
```

API em `http://localhost:8000` · Docs interativas em `http://localhost:8000/docs`.

---

## Como demonstrar — duas frentes em ~10 minutos

### Bloco 1 — Mock (longitudinal completo)

`.env`: `JIRA_MOCK=true`, `JIRA_PROJECT_KEY=SSD`

```powershell
curl -X POST http://localhost:8000/bootstrap/project   # cria projeto SSD no mock
curl -X POST http://localhost:8000/bootstrap/seed      # 6 sprints + 39 issues + 5 padrões plantados
curl -X POST http://localhost:8000/ingest/run          # Postgres + embeddings
curl -X POST http://localhost:8000/agent/run           # hygiene + mining + cross-ref + LLM
curl -X POST http://localhost:8000/agent/post-comments # MCP posta nos issues mock
curl http://localhost:8000/agent/recommendations | jq  # vê todas as recomendações
```

Nesse bloco você vê os 5 padrões plantados sendo detectados:

| Plant | Sinal |
|---|---|
| **P1** — joão.dev em integração | Cross-ref em SSD-21/SSD-22 citando SSD-6/9/12/18 com ratio 2.119× |
| **P2** — tech-debt carryover | Pattern alert standalone: 5/5 sprints carregaram |
| **P3** — duplicatas | 2 dos 3 pares (SSD-23↔24 sim 0.77, SSD-25↔26 sim 0.82) |
| **P4** — 5 obsoletas | Todas as 5 (SSD-29..33, 260 dias) |
| **P5** — epic emergente | 6 issues `notifications` sem epic agrupadas → "Sistema de Notifications" |

### Bloco 2 — Jira Cloud real (integração ponta a ponta)

`.env`: `JIRA_MOCK=false`, `JIRA_BASE_URL=https://<seu>.atlassian.net`, `JIRA_EMAIL=...`, `JIRA_API_TOKEN=...`, `JIRA_PROJECT_KEY=SSDEMO`

Reinicia uvicorn e roda:

```powershell
curl -X POST http://localhost:8000/bootstrap/project   # cria SSDEMO no Atlassian real
# Crie ~6 issues na UI do Jira (ou via JiraRestClient)
curl -X POST http://localhost:8000/ingest/run          # puxa as reais
curl -X POST http://localhost:8000/agent/run           # hygiene + LLM
curl -X POST http://localhost:8000/agent/post-comments # MCP posta nas issues reais
```

Aí você abre `https://<seu>.atlassian.net/browse/SSDEMO-1` e vê o comentário do bot na UI do Jira.

> **Por que dois blocos?** Pattern mining longitudinal exige timestamps históricos; Jira Cloud não permite criar issue retroativa via API. Mock injeta a história. Jira real prova que a integração funciona ponta a ponta.

---

## Configuração (`.env`)

```env
# Toggle do JiraClient
JIRA_MOCK=true                                # ou false p/ apontar Cloud real
JIRA_BASE_URL=https://yourco.atlassian.net    # só p/ JIRA_MOCK=false
JIRA_EMAIL=you@yourco.com
JIRA_API_TOKEN=...                            # gerar em id.atlassian.com/manage-profile/security/api-tokens
JIRA_PROJECT_KEY=SSD                          # ou SSDEMO p/ não colidir com mock

# Database
DATABASE_URL=postgresql+asyncpg://squad:squad@localhost:5434/squad_sense

# Embeddings
OPENAI_API_KEY=                               # vazio → NullEmbeddingClient
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

# LLM (auto-detect: ANTHROPIC > OPENAI > Null)
ANTHROPIC_API_KEY=
LLM_PROVIDER=                                 # vazio = auto, ou "anthropic"|"openai"
LLM_MODEL_ANTHROPIC=claude-sonnet-4-6
LLM_MODEL_OPENAI=gpt-4o-mini
```

---

## Decisões técnicas

### REST direto + MCP só para o agente

| Operação | Protocolo | Por quê |
|---|---|---|
| Bootstrap, seed, ingestion | **JiraRestClient** (httpx + Basic Auth) | Tipado, fácil de debugar, retry com tenacity |
| Loop do agente LLM (Etapa 3c) | **JiraMCPClient** → MCP server → JiraClient | MCP foi desenhado para LLMs descobrirem/escolherem tools, não como camada de transporte CRUD |

Misturar os dois sem critério gera código ruim. O `JiraMCPClient` spawna `python -m app.mcp_server` como subprocess; trocar pelo `mcp-atlassian` da comunidade é mudar 1 linha.

### Dual mode (mock ↔ real) com `Protocol`

`JiraClient` é um `Protocol`. Duas implementações conformes:
- `JiraMockClient` — JSON em `data/mock_jira.json`, usado para o seed sintético longitudinal
- `JiraRestClient` — Atlassian Cloud REST API v3

O resto do app (services, routers, agent) consome `JiraClient` sem saber qual está conectado. Switch de modo = uma env var.

### Embeddings com Protocol e auto-detect

`EmbeddingClient` (OpenAI / Voyage / Null) — fallback para `NullEmbeddingClient` (zeros) quando nenhuma chave existe, para a pipeline rodar mesmo offline. `text_hash` em SHA-256 evita reembedar issues inalteradas — cache trivial.

### Pattern caching no LLM

`AnthropicLLM` usa `cache_control: ephemeral` no system prompt. `OpenAILLM` faz cache implícito quando system prompt > 1024 tokens. **Telemetria de tokens cached é exposta** em `CoachRunStats.llm_cached_input_tokens_total` — no smoke do mock vimos **70% cache hit rate** em 31 chamadas.

### Autonomia: propor, não executar

| Nível | Ação | Default? |
|---|---|---|
| 0 — Observer | Só dashboard, zero toque no Jira | Ao instalar |
| 1 — Commenter | Comenta no Jira via MCP | **Recomendado** |
| 2 — Linker | Adiciona link "duplicates" entre issues | Opt-in |
| 3 — Actor | Fecha (não exclui) com confidence > 0.92 | Opt-in raro |

O MCP server **não expõe** `delete_issue` no toolset, mesmo quando o Jira API permitiria. Decisão de produto.

---

## Como os prompts foram estruturados

`app/agent/prompts.py` tem **um system prompt longo (>1k tokens, cacheável)** com:
- Princípios não-negociáveis (propor, citar evidência, reversibilidade, português direto, anti-alucinação)
- Formato de saída (JSON `{summary, body}`)
- 3 exemplos few-shot (dedup, underestimation_warning, emerging_epic)
- 4 anti-exemplos do que NÃO fazer

User prompt é **a finding específica + cross-refs + evidence_issues_full** (do RAG) serializados em JSON. O LLM tem todos os fatos no contexto e a regra explícita de só usar o que está ali. Resultado: zero alucinação de issue keys que não existem nos dados.

---

## Como contexto, memória, RAG e MCP foram tratados

### Contexto / memória

- **Curto prazo**: o pipeline do agente roda em uma única sessão SQLAlchemy; cada call do LLM tem o contexto completo da finding + evidence
- **Longo prazo**: tabela `recommendation` com `status (proposed|accepted|rejected)` + `human_feedback` — esse é o **closed loop** que treina o agente para o time específico ao longo do tempo
- **Memória do agente entre runs**: `text_hash` por issue evita reembedar; `recommendation.jira_comment_id` evita repostar; `recommendation.status` filtra propostas já decididas

### RAG

Duas frentes:

1. **Recuperação por similaridade** — pgvector cosine search com IVFFlat index. Usado pelo dedup detector e pelo endpoint `/db/issues/{key}/similar`.
2. **Recuperação por chave (citação literal)** — `_rag_load_evidence_issues()` puxa do Postgres o texto completo das `evidence_issue_keys` referenciadas pelos patterns. O LLM cita SSD-6, SSD-9 etc com summary+ratio reais.

### MCP

Ambas as pontas implementadas:

- **Server** (`app/mcp_server/`) — Python SDK oficial (`mcp>=1.0`), stdio transport, 3 tools (`get_issue`, `list_comments`, `add_comment`). Lê env do parent process; usa o mesmo `JiraClient` factory que a app principal.
- **Client** (`app/clients/jira_mcp.py`) — `mcp.client.stdio` para spawnar subprocess, `ClientSession` para protocolo. Lifecycle persistente entre chamadas via `async with`.

A separação client/server permite trocar nosso server pelo `mcp-atlassian` da comunidade em uma linha — esse é o ponto do protocolo.

---

## Estrutura

```
app/
├── main.py                      FastAPI + lifespan + DI
├── config.py                    Pydantic Settings
├── core/                        logging (structlog), exceptions
├── clients/
│   ├── jira_client.py           Protocol + factory
│   ├── jira_rest.py             httpx + tenacity + ADF
│   ├── jira_mock.py             JSON-backed
│   ├── jira_mcp.py              MCP client (stdio)
│   ├── embeddings.py            OpenAI / Null
│   └── llm.py                   Anthropic / OpenAI / Null
├── db/
│   ├── engine.py, session.py    SQLAlchemy 2.0 async
│   └── models.py                Project, Sprint, Issue, IssueEmbedding(Vector), Recommendation
├── schemas/                     Pydantic v2 (jira, bootstrap, db, recommendation)
├── services/
│   ├── bootstrap_service.py
│   ├── seed_service.py
│   ├── ingestion_service.py
│   ├── post_comments_service.py
│   ├── hygiene/                 dedup, obsolescence, dor, emerging_epic, service
│   ├── mining/                  underestimation, carryover, service
│   └── cross_reference.py
├── agent/
│   ├── coach.py                 pipeline multi-step
│   └── prompts.py               system + render_user_prompt
├── mcp_server/
│   ├── __main__.py              python -m app.mcp_server
│   └── server.py                MCP stdio server
├── routers/
│   ├── health.py, jira.py
│   ├── bootstrap.py, ingest.py
│   ├── db.py, hygiene.py, agent.py
└── seed_data/
    └── synthetic_sprint.py      6 sprints + 5 padrões plantados

alembic/versions/                0001 schema base + 0002 recommendation
db/init/                         CREATE EXTENSION vector
docker-compose.yml               Postgres pgvector pg16 (porta host 5434)
```

---

## Cobertura dos critérios do teste

| Critério obrigatório | Onde aparece |
|---|---|
| Python + LLM via API | OpenAI ou Anthropic via SDK oficial; auto-detect em `make_llm_client` |
| **Multi-step** | `CoachAgent.run`: hygiene → mining → cross-ref → trigger → RAG → synthesis → persist → MCP-post |
| **Memória/contexto** | `recommendation` (status + human_feedback) + `text_hash` evitando reembed + `jira_comment_id` evitando repost |
| **RAG** | pgvector cosine no dedup + `_rag_load_evidence_issues` para citação literal pelo LLM |
| **MCP real** | server próprio (Python SDK, stdio, 3 tools) + client real (substitui stub) + 29 comments postados em mock + 8 em Jira real |
| **Raciocínio aplicado** | Pattern Mining longitudinal + cross-reference por (assignee, label) + LLM com evidência estruturada |
| **Qualidade de código** | Protocols, separação de camadas, idempotência, prompt caching com telemetria, structlog, retries, schemas tipados, async-first |
| **README com decisões** | este documento |

---

## Nota sobre versionamento

O projeto foi desenvolvido localmente em iterações ao longo do teste técnico (etapas 1 → 2 → 3a → 3b → 3c, marcadas no README). O repositório no GitHub foi publicado como **snapshot único** ao final, então o histórico de commits aqui não reflete a evolução incremental — mostra apenas o estado final entregue.

Decisões técnicas que normalmente ficariam visíveis no `git log` (escolha de stack, mudanças de abordagem, trade-offs) estão documentadas explicitamente nas seções [Decisões técnicas](#decisões-técnicas) e [Como contexto, memória, RAG e MCP foram tratados](#como-contexto-memória-rag-e-mcp-foram-tratados).

---

## Como evoluir

- **Etapa 4 — calibração** — usa `recommendation.status` para suprimir suggestions que esse time consistently rejeita, ajusta thresholds por tipo
- **Etapa 5 — frontend** — dashboard React em `/recommendations` com Accept/Reject buttons, scorecard de quanto o agente aprendeu sobre o time
- **Slack digest** — cron diário com resumo das recomendações de alta confiança via webhook
- **Outros trackers** — `JiraClient` Protocol abstrai; trocar por `LinearClient` ou `GitHubProjectsClient` reaproveita 80%
- **MCP da comunidade** — substituir nosso server por `mcp-atlassian` é mudar 2 linhas em `JiraMCPClient.__init__`
- **Pattern Mining contra Jira real** — derivar `story_points_actual` de cycle time + reestimações (changelog Jira); implementar `list_sprints` REST via Agile API + board_id

---

## Como medir impacto na squad

Métricas que o próprio Squad Sense calcula a cada run:

| Métrica | Como muda com o agente |
|---|---|
| **Carryover rate** por label | Pattern P2 — mede mês a mês, espera-se queda nas labels que o agente sinalizou |
| **Estimation ratio** (actual/estimated) | Pattern P1 — mede por (assignee, label), espera-se convergência para 1.0× depois de splits sugeridos |
| **# duplicatas mergeadas** | `recommendation.status='accepted' AND type='dedup'` |
| **# epics emergentes criados** | `accepted AND type='emerging_epic'` |
| **Net Acceptance Rate** | `count(accepted) / count(proposed)` — quanto o time confia no agente |
| **DoR compliance trend** | issues novas com description+AC+story_points / total issues novas |

A demo final pode mostrar: *"se as 8 recomendações high-confidence aceitas tivessem sido aplicadas no sprint X, o carryover teria caído de 23% para projetado 8%."* Outcome, não output.

---

## Contato

Construído por Marcos Patricio. Issues no [repo](https://github.com/) ou direto pra `marcospatricio000@gmail.com`.
