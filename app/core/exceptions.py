from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

log = get_logger(__name__)


class SquadSenseError(Exception):
    """Erro de domínio do Squad Sense. Mapeado para 4xx/5xx pelo handler."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class JiraClientError(SquadSenseError):
    status_code = 502
    code = "jira_client_error"


class JiraAuthError(SquadSenseError):
    status_code = 401
    code = "jira_auth_error"


class BootstrapError(SquadSenseError):
    status_code = 400
    code = "bootstrap_error"


async def squad_sense_exception_handler(_: Request, exc: SquadSenseError) -> JSONResponse:
    log.error("squad_sense_error", code=exc.code, status_code=exc.status_code, message=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", exc_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Erro interno"}},
    )
