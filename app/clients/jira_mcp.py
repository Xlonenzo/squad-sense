"""JiraMCPClient — cliente MCP real (stdio transport).

Spawna o servidor MCP local (`python -m app.mcp_server`) como subprocess,
inicializa a sessão MCP, e expõe call_tool() + helpers tipados.

Trocar este servidor pelo `mcp-atlassian` da comunidade é mudar 1 linha
(o command/args). É essa portabilidade que o protocolo MCP entrega.

Uso:
    async with JiraMCPClient() as mcp:
        await mcp.add_comment("SSD-21", "💡 ...")
        comments = await mcp.list_comments("SSD-21")
"""

import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.exceptions import SquadSenseError
from app.core.logging import get_logger

log = get_logger(__name__)


class MCPClientError(SquadSenseError):
    status_code = 502
    code = "mcp_client_error"


class JiraMCPClient:
    """Cliente MCP-over-stdio. Persistente entre chamadas — o subprocess
    fica vivo enquanto o context manager está aberto."""

    def __init__(
        self,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        # Default: spawna o servidor que está nesta mesma codebase, no mesmo
        # interpretador Python (para garantir que pegou o venv certo).
        self._command = command or sys.executable
        self._args = args or ["-m", "app.mcp_server"]
        # Repassa o ambiente atual (JIRA_MOCK etc) para o subprocess.
        self._env = {**os.environ, **(env or {})}

        self._stdio_cm: Any = None
        self._session_cm: Any = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "JiraMCPClient":
        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env,
        )
        self._stdio_cm = stdio_client(params)
        try:
            read, write = await self._stdio_cm.__aenter__()
        except Exception as e:
            raise MCPClientError(f"falha ao spawnar MCP server: {e}") from e

        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        log.info("mcp_client_initialized", command=self._command)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(exc_type, exc, tb)
        finally:
            if self._stdio_cm is not None:
                await self._stdio_cm.__aexit__(exc_type, exc, tb)
        log.info("mcp_client_closed")

    # ---------------------------------------------------------- raw tools

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._session is None:
            raise MCPClientError("client não inicializado")
        result = await self._session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.inputSchema,
            }
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise MCPClientError("client não inicializado")
        result = await self._session.call_tool(name, arguments)

        if not result.content:
            return None

        first = result.content[0]
        text = getattr(first, "text", None)
        if text is None:
            return None

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text

        if isinstance(payload, dict) and "error" in payload:
            raise MCPClientError(f"tool {name}: {payload['error']}")
        return payload

    # -------------------------------------------------------- convenience

    async def get_issue(self, key: str) -> dict[str, Any]:
        return await self.call_tool("get_issue", {"key": key})

    async def list_comments(self, key: str) -> list[dict[str, Any]]:
        return await self.call_tool("list_comments", {"key": key}) or []

    async def add_comment(self, key: str, body: str) -> dict[str, Any]:
        return await self.call_tool("add_comment", {"key": key, "body": body})
