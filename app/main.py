from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.embeddings import make_embedding_client
from app.clients.jira_client import make_jira_client
from app.clients.llm import make_llm_client
from app.core.exceptions import (
    SquadSenseError,
    squad_sense_exception_handler,
    unhandled_exception_handler,
)
from app.core.logging import configure_logging, get_logger
from app.routers import agent, bootstrap, db, health, hygiene, ingest, jira

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.jira = make_jira_client()
    app.state.embedder = make_embedding_client()
    app.state.llm = make_llm_client()
    log.info(
        "app_started",
        jira_mode=app.state.jira.mode,
        embedding_model=app.state.embedder.model,
        llm_model=app.state.llm.model,
    )
    try:
        yield
    finally:
        await app.state.jira.close()
        await app.state.embedder.close()
        await app.state.llm.close()
        log.info("app_stopped")


app = FastAPI(
    title="Squad Sense",
    description=(
        "Agente de IA para hygiene de backlog e pattern mining longitudinal "
        "de squads ágeis. Etapa 1: backend + Jira client (REST/mock) + bootstrap + seed."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(SquadSenseError, squad_sense_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router)
app.include_router(bootstrap.router, prefix="/bootstrap", tags=["bootstrap"])
app.include_router(jira.router, prefix="/jira", tags=["jira"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(db.router, prefix="/db", tags=["db"])
app.include_router(hygiene.router, prefix="/hygiene", tags=["hygiene"])
app.include_router(agent.router, prefix="/agent", tags=["agent"])
