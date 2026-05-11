# Roteiro de demo — Squad Sense

**Objetivo:** mostrar o produto em ação e fazer cada critério obrigatório aparecer naturalmente na tela.
**Duração-alvo:** 9-10 min.
**Setup antes de gravar:**
- 2 abas do navegador: (a) `https://xlontest.atlassian.net/jira/projects/SSDEMO/board` (Bloco 2), (b) `http://localhost:8000/docs` ou dashboard React.
- Terminal aberto com `uvicorn` rodando.
- `mock_jira.json` zerado e `recommendation` table limpa para gravar do zero.
- Tenha o `.env` pronto para alternar entre `JIRA_MOCK=true/false`.

---

## Cena 1 — Abertura e problema (0:00–0:45)

**Tela:** slide simples com o título e os 3 problemas. Ou só você falando.

**Fala:**
> "Squad Sense é um agente de IA para squads ágeis. Ele resolve três problemas que toda squad ágil tem mas ninguém ataca direito:
>
> Um — backlog vira lixeira semântica: duplicatas, obsoletas, escopo emergente sem epic.
> Dois — estimativa não aprende com o passado: o time subestima cronicamente certos tipos de trabalho mas isso vive na cabeça das pessoas.
> Três — refinamento manual não escala: PO e SM gastam horas em tarefas automatizáveis.
>
> Vou mostrar como o produto resolve cada um. Começo com o Jira real para vocês verem que a integração é de verdade, depois mostro o mock onde o cérebro longitudinal aparece."

---

## Cena 2 — Antes: o Jira real cru (0:45–1:30)

**Tela:** aba (a). Board do projeto SSDEMO no `xlontest.atlassian.net`. Mostra 6 issues em TODO/In Progress, sem comentários.

**Ações:**
1. Abre 1 ou 2 issues (ex.: SSDEMO-1 e SSDEMO-2). Mostra a aba **Comments** vazia.
2. Volta pro board. Aponta visualmente: "olha, é Jira Cloud normal, sem nada do agente."

**Fala:**
> "Aqui está o estado inicial: projeto SSDEMO no Atlassian Cloud, 6 issues criadas, zero comentário. É Jira de verdade — vocês podem auditar a URL. Agora vou rodar o pipeline e voltar."

---

## Cena 3 — Pipeline rodando contra Jira real (1:30–3:00)

**Tela:** terminal + Swagger UI (`/docs`).

**Ações em sequência (4 calls de curl ou via Swagger):**
```powershell
curl -X POST http://localhost:8000/ingest/run
# → puxa as 6 issues, gera embeddings via OpenAI, persiste em pgvector
```

**Aponta no terminal:**
- Logs do `structlog`: `ingestion_started`, `embedding_generated dim=1536`, `issues_persisted count=6`.

**Fala (durante):**
> "Ingest puxa as issues via REST, gera embeddings com `text-embedding-3-small` e persiste em Postgres com pgvector. Esse é o índice que vai alimentar o RAG."

```powershell
curl -X POST http://localhost:8000/agent/run
# → hygiene + mining + cross-ref + LLM synthesis
```

**Aponta no terminal:**
- Logs por etapa: `hygiene_pass_started`, `dedup_candidates n=2`, `dor_violations n=3`, `coach_synthesis_started`, `llm_call cached_tokens=1340`, `recommendations_persisted n=8`.

**Fala:**
> "O Coach Agent é multi-step: detecta padrões algoritmicamente, monta o contexto via RAG, e só aí chama o LLM para sintetizar a recomendação. Reparem nos `cached_tokens` — system prompt longo está sendo cacheado entre chamadas."

```powershell
curl -X POST http://localhost:8000/agent/post-comments
# → MCP server spawnado como subprocess, postando 8 comments
```

**Aponta no terminal:**
- Logs: `mcp_server_started transport=stdio`, `mcp_tool_call name=add_comment`, 8 chamadas, `comments_posted count=8`.

**Fala:**
> "Aqui é o MCP de verdade: nosso server em Python SDK roda como subprocess via stdio, expondo `get_issue`, `list_comments` e `add_comment` como tools. O agente posta 8 comentários."

---

## Cena 4 — Depois: o Jira real com agente trabalhando (3:00–4:00)

**Tela:** volta na aba (a). Recarrega o board.

**Ações:**
1. Abre **SSDEMO-2** (a issue OAuth Google).
2. Aba **Comments**: mostra o comentário do bot. Lê em voz alta os trechos-chave:
   - "💡 **Squad Sense — duplicata possível**"
   - Cita `SSDEMO-X` com similaridade `0.44`
   - Final: "responda `ss-skip duplicate`"
3. Abre 1 ou 2 outras issues com comments diferentes (DoR violation, epic emergente).
4. Aponta o autor do comment: "veja, é o bot, atribuição visível."

**Fala:**
> "Comentário aparece na UI nativa do Jira, atribuição visível ao bot, citando issue keys reais — zero alucinação. E reparem: o agente **propõe**, ele não fechou nem apagou nada. O time decide. Se ignorar é zero dano. Se responder `ss-skip` o feedback fecha o loop."

---

## Cena 5 — Transição para o Mock (4:00–4:30)

**Tela:** terminal. Edita `.env` rapidamente: `JIRA_MOCK=true`. Reinicia uvicorn.

**Fala:**
> "O Bloco 1 prova que a integração é real. Mas o cérebro do produto é o pattern mining longitudinal — e isso só dá para demonstrar com histórico. Jira Cloud não deixa criar issues com timestamp retroativo, então uso o mock pra injetar a história: 6 sprints, 39 issues, 5 padrões plantados. Mesma arquitetura, dataset diferente."

---

## Cena 6 — Mock: pattern mining brilhando (4:30–7:00)

**Tela:** terminal pro pipeline + **dashboard React (`veritis1-web`)** pro resultado.

**Pré-requisito extra:** frontend rodando em paralelo:
```powershell
cd ../veritis1-web && pnpm dev    # ou npm run dev
# abre em http://localhost:5173
```

### 6a — Rodando o pipeline (terminal)

```powershell
.\scripts\demo-mock.ps1
# pausa entre cada etapa pra você narrar
```

**Aponta no painel do uvicorn:**
- `pattern_mining_started`, `underestimation_pattern detected assignee=joao.dev label=integration ratio=2.119 n=4`, `carryover_pattern label=tech-debt rate=1.0 sprints=5/5`.

**Fala:**
> "Pattern mining acabou de detectar dois padrões longitudinais. Olhem: joão.dev em issues de integração tem ratio actual/estimated de 2.119× nas últimas 4 entregas. E a label tech-debt carregou em 5 das 5 sprints fechadas. Isso é SQL puro sobre o histórico — não é LLM chutando."

### 6b — Visão geral no dashboard

**Tela:** abre `http://localhost:5173` (logo Verity na sidebar, dark mode, accent #0041FF).

**Aponta visualmente:**
- KPIs no topo (totals, severity, types, tokens)
- Feed de recomendações com badges por tipo (`dedup`, `underestimation_warning`, `dor_violation`, `emerging_epic`, `carryover_warning`)
- Activity feed lateral

**Fala:**
> "Esse é o painel da squad. Tudo que o agente detectou aparece aqui em um único lugar — o PO ou Scrum Master abre essa tela e vê o estado real do backlog em segundos."

### 6c — Mostrando 3 recomendações específicas + Inspect RAG

**Ação:** abre **a recomendação de cross-reference em SSD-21 (Pix gateway)**. Lê o body do comentário em voz alta:
> "Esta issue está em 5 pts. O cluster (joão.dev, integration) tem ratio histórico 2.1× citando SSD-6, SSD-9, SSD-12, SSD-18..."

**Ação chave:** clica no botão **"Inspect RAG"** do card.

**Aparece o painel `RagInspectorPanel`** com 2 blocos:

**Bloco 1 — Vector retrieval (pgvector cosine)**
- Lista os top-N vizinhos com **similaridade colorida**:
  - 🟢 verde (≥0.70) — match forte
  - 🟡 amarelo (0.50-0.70) — moderado
  - cinza (<0.50) — fraco
- Subtítulo: *"pgvector cosine_distance · IVFFlat · text-embedding-3-small (1536d)"*

**Fala:**
> "Aqui é o RAG funcionando ao vivo. Para essa issue alvo, o pgvector buscou os vizinhos mais próximos no espaço de embedding. Verde é match forte. Esse passo é puramente algorítmico — sem LLM."

**Bloco 2 — Evidence loading no prompt do LLM**
- Lista as issues que foram **literalmente injetadas no user prompt** com chips: assignee, ratio (com badge vermelho se ≥1.5×), status

**Fala:**
> "E aqui é a 'prova viva' que o subtítulo do componente promete: estas são exatamente as issues que entraram no contexto do LLM como `evidence_issues_full`. O system prompt tem regra explícita de só citar o que está aqui. Você consegue auditar issue por issue por que o LLM falou o que falou. Zero alucinação opaca."

### 6d — Mostra mais 2 tipos de recomendação (rapidinho)

**Ação:** fecha o painel, scrolla pro feed:

1. **Duplicata** (SSD-23 ↔ SSD-24 sobre rate-limit):
   - Abre Inspect RAG → mostra similaridade alta (~0.77) entre as duas
   > "Detecção de duplicata é o caso mais limpo: o vector retrieval acha o par e a similaridade vira a confidence."

2. **Epic emergente** (6 issues notifications):
   - Mostra body do comment com keys SSD-34..39 listadas
   - No painel: "esta recomendação é squad-level — não disparou vector retrieval para um issue alvo" (mostra o `NoData` block)
   > "Já epic emergente é detectado por clusterização sobre o backlog inteiro. O painel deixa explícito que não há vector retrieval — porque o pattern não tem alvo único, varre todo o backlog."

**Fala de fechamento da cena:**
> "Reparem que a UX é desenhada pra dar evidência, não esconder. Cada recomendação tem o caminho 'por que você está me dizendo isso?' a um clique de distância. É o oposto de uma sugestão genérica de LLM — é raciocínio auditável."

### Fallback se o frontend não subir

Se algo quebrar no dashboard, cai pro modo terminal:
```powershell
curl http://localhost:8000/agent/recommendations | jq
curl http://localhost:8000/agent/recommendations/1/rag | jq
```
A rota `/rag` retorna o mesmo JSON que alimenta o painel.

---

## Cena 7 — Closed loop (7:00–7:45)

**Tela:** dashboard React, mesma tela da Cena 6.

### 7a — Aceitar uma recomendação

**Ação:** num card de recomendação (idealmente a duplicata SSD-23 ↔ SSD-24, que é a mais óbvia), clica no botão **Aceitar**.

**Aparece o `FeedbackDialog`:**
- Título: *"Aceitar recomendação"*
- Texto: *"Marque como aceita. O comentário citado fica como sinal positivo na calibração do agente."*
- Card resumo da recomendação (target keys, tipo, summary)
- Textarea opcional pra nota
- Botões `Cancelar` / `Aceitar` (verde)

**Ação:** digita uma nota curta tipo *"sim, mergei na SSD-23"* e clica **Aceitar**.

**Resultado visual:** card volta pro feed com status mudado pra `accepted` (badge verde).

**Fala:**
> "Aceitei. O `recommendation.status` virou `accepted` no Postgres com `human_feedback` opcional. Esse não é só um botão de UI — é o sinal que treina o agente para essa squad específica."

### 7b — Rejeitar outra (mostrar o caminho contrário)

**Ação:** noutro card (ideal: uma das obsoletas, P4), clica **Rejeitar**.

**Aparece o mesmo `FeedbackDialog` em modo rejeição:**
- Título: *"Rejeitar recomendação"*
- Texto: *"Marque como rejeitada e (opcional) explique o motivo. O agente usa esse sinal para suprimir sugestões similares no futuro."*
- Botão **Rejeitar** (vermelho)

**Ação:** digita *"essa issue ainda é relevante, vamos retomar Q3"* e clica **Rejeitar**.

**Fala:**
> "E rejeição é simétrica: o agente registra `human_feedback` e usa esse sinal pra calibrar. Se essa squad rejeita consistentemente sugestões de obsolescência com motivos parecidos, na Etapa 4 a gente sobe o threshold daquele detector pra esse time. É calibração por squad, não regra global."

### 7c — Fecha falando da Etapa 4

**Tela:** rapidamente abre o `psql` ou `/agent/recommendations?status=accepted` pra mostrar que tem dado real persistido (opcional, só se tiver tempo).

**Fala:**
> "Cada aceite e cada rejeição vira sinal de calibração para essa squad específica. É o que faz o agente melhorar com o tempo, em vez de cuspir o mesmo conselho genérico para todo mundo. Esse é o eixo de evolução para a Etapa 4: suprimir suggestions que esse time consistentemente rejeita, ajustar thresholds por tipo."

### Fallback se o frontend não subir

```powershell
# Aceitar via API
curl -X PATCH http://localhost:8000/agent/recommendations/1 -H "Content-Type: application/json" -d '{"status":"accepted","human_feedback":"sim, mergei"}'

# Ver o resultado no Postgres
docker exec -it squad-sense-postgres psql -U squad -d squad_sense -c "SELECT id, type, status, human_feedback FROM recommendation WHERE status != 'proposed';"
```

---

## Cena 8 — Cobertura dos critérios (7:45–9:00)

**Tela:** slide ou só fala. Versão visual: tabela rápida do README.

**Fala (linha por linha, apontando):**
> "Pra fechar, vou mapear o que vocês acabaram de ver nos critérios obrigatórios:
>
> **LLM via API** — Anthropic ou OpenAI, auto-detect.
> **Multi-step** — vocês viram: ingest → hygiene → mining → cross-ref → trigger → RAG → LLM → persist → MCP-post.
> **Orquestração — abordagem própria** — pipeline linear em `CoachAgent`, sem LangChain/CrewAI. As etapas são fixas e auditáveis; a ramificação dinâmica fica no MCP. Framework custaria peso sem benefício.
> **Memória/contexto** — tabela recommendation com status e human_feedback, text_hash evitando reembedar, jira_comment_id evitando repostar.
> **RAG** — pgvector cosine no dedup detector, e injeção literal de issues no user prompt do LLM.
> **MCP real** — nosso próprio server em Python SDK rodando via stdio, três tools, vocês viram comentário aparecendo na UI do Jira real.
> **Raciocínio** — Pattern Mining longitudinal e cross-reference são SQL e estatística; o LLM só sintetiza com evidência. Não é Q&A genérico.
> **Qualidade** — Protocols para mock toggle e providers, async-first, structlog, prompt caching com telemetria."

---

## Cena 9 — Evolução e encerramento (9:00–9:30)

**Fala:**
> "Pra evoluir além do MVP: Etapa 4 calibra thresholds com o histórico de aceite/rejeição. Etapa 5 adiciona dashboard React com botões de Accept/Reject e digest no Slack. Pattern mining contra Jira real é factível derivando story_points_actual do changelog. E o JiraClient é Protocol — trocar por LinearClient ou GitHubProjects reaproveita 80% do código.
>
> Squad Sense, em uma frase: detecção é algorítmica, narração é LLM, e cada recomendação tem evidência citável. Obrigado."

---

## Checklist pré-gravação

- [ ] `mock_jira.json` resetado, `recommendation` table truncada
- [ ] SSDEMO no Jira real com as 6 issues, sem comments
- [ ] OBS / gravador de tela testado, fonte do terminal grande (16pt+)
- [ ] Áudio sem ruído, mic testado
- [ ] `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY` no `.env` (sem chave o LLM cai em texto canônico e o cache não aparece)
- [ ] Postgres up, alembic rodado
- [ ] `jq` instalado pra deixar saída do curl bonita

## Notas de filmagem

- **Ritmo:** corte tudo que for >2s sem informação nova. Logs longos vão acelerados.
- **Foco visual:** quando trocar de tela, espera 1s para o espectador acompanhar.
- **Não leia o roteiro.** Internalize as ideias, fale natural. Os trechos em > são pra você se ancorar, não recitar.
- **Se travar:** corta e refilma a cena, não a sessão inteira.
- **Versão curta de 5 min** se precisar: corta Cena 1 (já tá no README), corta Cena 7 (closed loop pode virar nota), reduz Cena 8.
