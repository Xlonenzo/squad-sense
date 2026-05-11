"""Gerador do dataset sintético longitudinal.

Produz uma "história" de 6 sprints + ~50 issues com sinais propositais
plantados — esse é o eval suite que as etapas 3-5 precisam derrotar.

Padrões plantados (ver README.md → "Padrões plantados"):

    P1  joão.dev sempre estoura prazo em integrações externas (~2× est)
    P2  Label "tech-debt" tem alto carryover (~70%)
    P3  Três pares de duplicatas semânticas no backlog atual
    P4  Cinco issues obsoletas (criadas há 8+ meses, sem atividade)
    P5  Seis issues soltas formando epic emergente (notificações)

Saída: lista de SeedSprint e SeedIssue (não chama Jira aqui — o
seed_service que chama o JiraClient).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.schemas.jira import IssueStatus, IssueType, SprintState

UTC = timezone.utc

USERS = {
    "joao": "joao.dev",
    "maria": "maria.eng",
    "carlos": "carlos.eng",
    "ana": "ana.junior",
}

PLANTED_PATTERNS = [
    "P1: joao.dev em issues 'integration' → estimativa 2× (n=4)",
    "P2: label 'tech-debt' → carryover ~70% (n=5)",
    "P3: 3 pares de duplicatas semânticas no backlog",
    "P4: 5 issues obsoletas (>180 dias sem atividade)",
    "P5: 6 issues soltas formando epic emergente (sistema de notificações)",
]


@dataclass
class SeedSprint:
    name: str
    goal: str
    start_date: datetime
    end_date: datetime
    state: SprintState
    complete_date: datetime | None = None


@dataclass
class SeedIssue:
    summary: str
    issue_type: IssueType
    description: str | None = None
    labels: list[str] = field(default_factory=list)
    assignee: str | None = None
    story_points: float | None = None
    story_points_actual: float | None = None
    status: IssueStatus = IssueStatus.TODO
    created_offset_days: int = 0  # relativo a "agora"
    resolved_offset_days: int | None = None
    sprint_index: int | None = None  # 0..5; None = backlog/futuro
    epic_summary: str | None = None  # se setado, pertence ao epic com este summary


# --------------------------------------------------------------------- sprints


def _build_sprints(now: datetime) -> list[SeedSprint]:
    """6 sprints fechadas (mais antiga primeiro) + 1 ativa.

    Cada sprint dura 14 dias. Sprint atual em andamento; as 5 anteriores
    estão fechadas. Carryover é calculado pelas issues que estão Done
    porém atribuídas a sprint posterior à criação.
    """
    sprints: list[SeedSprint] = []
    # Sprints fechadas: -84 a -14 dias, em janelas de 14 dias
    closed_goals = [
        "Fundamentos de auth e onboarding",
        "Migração de billing para nova engine",
        "Estabilizar pipeline de ingestão",
        "Reduzir tempo de checkout",
        "Otimização do feed e cache",
    ]
    for i, goal in enumerate(closed_goals):
        start = now - timedelta(days=84 - i * 14)
        end = start + timedelta(days=14)
        sprints.append(
            SeedSprint(
                name=f"Sprint {i + 1}",
                goal=goal,
                start_date=start,
                end_date=end,
                state=SprintState.CLOSED,
                complete_date=end,
            )
        )

    # Sprint ativa
    active_start = now - timedelta(days=4)
    sprints.append(
        SeedSprint(
            name="Sprint 6",
            goal="Reforçar integrações de pagamento (Pix + boleto)",
            start_date=active_start,
            end_date=active_start + timedelta(days=14),
            state=SprintState.ACTIVE,
        )
    )
    return sprints


# ----------------------------------------------------------------------- epics


def _epics() -> list[SeedIssue]:
    return [
        SeedIssue(
            summary="EPIC: Fundamentos de Autenticação",
            issue_type=IssueType.EPIC,
            labels=["auth"],
            created_offset_days=-90,
        ),
        SeedIssue(
            summary="EPIC: Billing v2",
            issue_type=IssueType.EPIC,
            labels=["billing"],
            created_offset_days=-80,
        ),
        SeedIssue(
            summary="EPIC: Performance Checkout",
            issue_type=IssueType.EPIC,
            labels=["performance"],
            created_offset_days=-50,
        ),
        # Note: NÃO há epic explícito para notificações — esse é o P5 (epic emergente).
    ]


# ---------------------------------------------------------------------- stories


def _build_issues() -> list[SeedIssue]:
    issues: list[SeedIssue] = []

    # ── Sprints fechadas (índices 0..4) ──────────────────────────────────────

    # Sprint 1 — auth onboarding
    issues += [
        SeedIssue(
            summary="Implementar login com email + senha",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=5, story_points_actual=5,
            status=IssueStatus.DONE,
            created_offset_days=-84, resolved_offset_days=-72,
            sprint_index=0, epic_summary="EPIC: Fundamentos de Autenticação",
        ),
        SeedIssue(
            summary="Adicionar reset de senha via email",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=3, story_points_actual=3,
            status=IssueStatus.DONE,
            created_offset_days=-83, resolved_offset_days=-71,
            sprint_index=0, epic_summary="EPIC: Fundamentos de Autenticação",
        ),
        # P1: joão em integration → 2x
        SeedIssue(
            summary="Integrar provider OAuth Google",
            description="Integração externa com Google Identity",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration"],
            story_points=5, story_points_actual=10,
            status=IssueStatus.DONE,
            created_offset_days=-84, resolved_offset_days=-68,
            sprint_index=0, epic_summary="EPIC: Fundamentos de Autenticação",
        ),
        # P2: tech-debt carrega
        SeedIssue(
            summary="Refatorar middleware de auth legado",
            issue_type=IssueType.TASK, labels=["tech-debt"],
            assignee=USERS["carlos"],
            story_points=8, story_points_actual=8,
            status=IssueStatus.DONE,  # carregou de Sprint 1 para Sprint 2
            created_offset_days=-84, resolved_offset_days=-58,
            sprint_index=1,  # entregue na Sprint 2 mas criada na 1 → carryover
        ),
    ]

    # Sprint 2 — billing
    issues += [
        SeedIssue(
            summary="Modelar nova engine de cobrança recorrente",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=8, story_points_actual=8,
            status=IssueStatus.DONE,
            created_offset_days=-70, resolved_offset_days=-58,
            sprint_index=1, epic_summary="EPIC: Billing v2",
        ),
        # P1: joão em integration → 2x
        SeedIssue(
            summary="Integrar gateway Stripe para cartões",
            description="Integração externa com Stripe",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration"],
            story_points=5, story_points_actual=11,
            status=IssueStatus.DONE,
            created_offset_days=-70, resolved_offset_days=-54,
            sprint_index=1, epic_summary="EPIC: Billing v2",
        ),
        # P2: tech-debt carrega
        SeedIssue(
            summary="Limpar campos legados na tabela invoices",
            issue_type=IssueType.TASK, labels=["tech-debt"],
            assignee=USERS["carlos"],
            story_points=3, story_points_actual=3,
            status=IssueStatus.DONE,
            created_offset_days=-70, resolved_offset_days=-44,
            sprint_index=2,  # carregou
        ),
    ]

    # Sprint 3 — pipeline
    issues += [
        SeedIssue(
            summary="Adicionar dead-letter queue ao pipeline de ingestão",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=5, story_points_actual=5,
            status=IssueStatus.DONE,
            created_offset_days=-56, resolved_offset_days=-44,
            sprint_index=2,
        ),
        # P1: joão em integration → 2x
        SeedIssue(
            summary="Integrar webhook do parceiro logístico",
            description="Integração externa de tracking",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration"],
            story_points=8, story_points_actual=15,
            status=IssueStatus.DONE,
            created_offset_days=-56, resolved_offset_days=-38,
            sprint_index=2,
        ),
        # P2: tech-debt carrega
        SeedIssue(
            summary="Migrar logs do pipeline para o novo formato",
            issue_type=IssueType.TASK, labels=["tech-debt"],
            assignee=USERS["ana"],
            story_points=3, story_points_actual=4,
            status=IssueStatus.DONE,
            created_offset_days=-56, resolved_offset_days=-30,
            sprint_index=3,  # carregou
        ),
    ]

    # Sprint 4 — checkout
    issues += [
        SeedIssue(
            summary="Reduzir TTFB do /checkout para <300ms",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=8, story_points_actual=8,
            status=IssueStatus.DONE,
            created_offset_days=-42, resolved_offset_days=-30,
            sprint_index=3, epic_summary="EPIC: Performance Checkout",
        ),
        # P2: tech-debt carrega de novo
        SeedIssue(
            summary="Remover JS bloqueante na página de checkout",
            issue_type=IssueType.TASK, labels=["tech-debt"],
            assignee=USERS["carlos"],
            story_points=5, story_points_actual=5,
            status=IssueStatus.DONE,
            created_offset_days=-42, resolved_offset_days=-16,
            sprint_index=4,  # carregou
        ),
        SeedIssue(
            summary="Cachear página de produto no edge",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=5, story_points_actual=5,
            status=IssueStatus.DONE,
            created_offset_days=-42, resolved_offset_days=-30,
            sprint_index=3, epic_summary="EPIC: Performance Checkout",
        ),
    ]

    # Sprint 5 — feed/cache
    issues += [
        SeedIssue(
            summary="Implementar cache de feed por usuário",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=5, story_points_actual=5,
            status=IssueStatus.DONE,
            created_offset_days=-28, resolved_offset_days=-16,
            sprint_index=4,
        ),
        # P1: joão em integration → 2x
        SeedIssue(
            summary="Integrar provider de notificação SMS Twilio",
            description="Integração externa com Twilio para SMS",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration", "notifications"],
            story_points=5, story_points_actual=12,
            status=IssueStatus.DONE,
            created_offset_days=-28, resolved_offset_days=-12,
            sprint_index=4,
        ),
        # P2: tech-debt carrega
        SeedIssue(
            summary="Substituir lib de cache deprecated",
            issue_type=IssueType.TASK, labels=["tech-debt"],
            assignee=USERS["carlos"],
            story_points=5, story_points_actual=6,
            status=IssueStatus.DONE,
            created_offset_days=-28, resolved_offset_days=-2,
            sprint_index=5,  # carregou para sprint ativa
        ),
    ]

    # ── Sprint 6 (ativa) ─────────────────────────────────────────────────────
    issues += [
        SeedIssue(
            summary="Suporte a Pix no checkout",
            issue_type=IssueType.STORY,
            assignee=USERS["maria"],
            story_points=8,
            status=IssueStatus.IN_PROGRESS,
            created_offset_days=-10,
            sprint_index=5,
        ),
        # P1 ativo: joão em integração → o agente deve flagar
        SeedIssue(
            summary="Integrar gateway Pix do banco parceiro",
            description="Integração externa com API Pix do banco",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration"],
            story_points=5,  # subestimado; o agente deve detectar
            status=IssueStatus.IN_PROGRESS,
            created_offset_days=-8,
            sprint_index=5,
        ),
        SeedIssue(
            summary="Adicionar boleto bancário registrado como meio de pagamento",
            issue_type=IssueType.STORY,
            assignee=USERS["joao"], labels=["integration"],
            story_points=8,
            status=IssueStatus.TODO,
            created_offset_days=-6,
            sprint_index=5,
        ),
    ]

    # ── Backlog: P3 duplicatas, P4 obsoletas, P5 epic emergente ──────────────

    # P3a: par duplicado sobre rate-limit
    issues += [
        SeedIssue(
            summary="Aplicar rate limiting no endpoint /api/login",
            description="Limitar tentativas de login para mitigar brute force",
            issue_type=IssueType.STORY, labels=["security"],
            story_points=3, status=IssueStatus.TODO,
            created_offset_days=-12,
        ),
        SeedIssue(
            summary="Limitar requests por minuto na rota de autenticação",
            description="Proteção contra brute force no /api/login",
            issue_type=IssueType.STORY, labels=["security"],
            story_points=3, status=IssueStatus.TODO,
            created_offset_days=-9,
        ),
    ]

    # P3b: par duplicado sobre exportação de relatórios
    issues += [
        SeedIssue(
            summary="Exportar relatório de vendas em CSV",
            description="Export CSV do dashboard de vendas",
            issue_type=IssueType.STORY, labels=["reporting"],
            story_points=3, status=IssueStatus.TODO,
            created_offset_days=-15,
        ),
        SeedIssue(
            summary="Adicionar download CSV ao dashboard de vendas",
            description="Permitir baixar dados de vendas em formato CSV",
            issue_type=IssueType.STORY, labels=["reporting"],
            story_points=2, status=IssueStatus.TODO,
            created_offset_days=-7,
        ),
    ]

    # P3c: par duplicado sobre dark mode
    issues += [
        SeedIssue(
            summary="Adicionar suporte a tema escuro no dashboard",
            issue_type=IssueType.STORY, labels=["ui"],
            story_points=5, status=IssueStatus.TODO,
            created_offset_days=-20,
        ),
        SeedIssue(
            summary="Permitir alternar para dark mode na interface",
            issue_type=IssueType.STORY, labels=["ui"],
            story_points=3, status=IssueStatus.TODO,
            created_offset_days=-5,
        ),
    ]

    # P4: 5 issues obsoletas (>180 dias, sem atividade)
    obsolete_summaries = [
        "Avaliar migração para framework deprecado XYZ",
        "PoC com biblioteca de gráficos antiga (não mais usada)",
        "Adicionar suporte ao Internet Explorer 11",
        "Reabilitar integração com sistema legado descontinuado",
        "Investigar bug em fluxo removido em 2023",
    ]
    for s in obsolete_summaries:
        issues.append(
            SeedIssue(
                summary=s,
                issue_type=IssueType.TASK,
                story_points=3, status=IssueStatus.TODO,
                created_offset_days=-260,
            )
        )

    # P5: 6 issues que formam um epic emergente (notificações), todas SOLTAS
    emerging = [
        "Permitir notificações por email para eventos críticos",
        "Adicionar push notifications no app mobile",
        "Configurar templates de notificação por canal",
        "Criar centro de preferências de notificação para o usuário",
        "Suportar notificações in-app no header",
        "Throttle de notificações para evitar spam",
    ]
    for i, s in enumerate(emerging):
        issues.append(
            SeedIssue(
                summary=s,
                issue_type=IssueType.STORY,
                labels=["notifications"],
                story_points=3 + (i % 3),
                status=IssueStatus.TODO,
                created_offset_days=-(20 + i * 2),
                # Note: epic_summary deliberadamente None → o agente deve sugerir agrupar
            )
        )

    return issues


# -------------------------------------------------------------------- public API


def build_dataset(now: datetime | None = None) -> tuple[list[SeedSprint], list[SeedIssue], list[SeedIssue]]:
    """Retorna (sprints, epics, issues). 'epics' são issues do tipo EPIC."""
    now = now or datetime.now(UTC)
    sprints = _build_sprints(now)
    epics = _epics()
    stories = _build_issues()
    return sprints, epics, stories
