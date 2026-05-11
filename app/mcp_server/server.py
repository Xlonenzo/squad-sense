"""Squad Sense — Jira MCP server (stdio transport).

Servidor MCP que expõe um conjunto enxuto de tools sobre Jira para o
agente LLM. Implementação canônica do Model Context Protocol — não
um proxy: as tools são definidas, descobertas via list_tools, chamadas
via call_tool, exatamente como qualquer outro servidor MCP da
comunidade (mcp-atlassian, etc.).

Ponto importante de design:
- O servidor lê JIRA_MOCK do .env e instancia um JiraClient real ou mock.
- Em mock, ele lê/escreve o mesmo data/mock_jira.json que a FastAPI app.
  Não há contenção porque, na Etapa 3c, só o MCP server escreve nesse
  arquivo durante o flow de post-comments (a app só lê a tabela
  recommendation no Postgres).
- O JiraMCPClient na FastAPI app spawna ESTE arquivo como subprocess.

Tools expostas (no toolset NÃO incluímos delete/close — coerente com a
decisão de produto "propor, não executar"):
    get_issue(key)       leitura para o agente confirmar contexto
    list_comments(key)   leitura para detectar 'ss-skip' do squad
    add_comment(key, body)  ação primária do Coach: postar a recomendação

Run: python -m app.mcp_server
"""

import asyncio
import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from app.clients.jira_client import JiraClient, make_jira_client
from app.core.exceptions import JiraClientError
from app.core.logging import configure_logging, get_logger

# Força UTF-8 nos streams stdio do interpretador. No Windows, o default
# costuma ser cp1252 e quebra na serialização de emojis (ex: 💡 nas
# recomendações). MCP usa stdout puro como JSON-RPC — qualquer corrupção
# de bytes derruba o canal.
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
if sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

configure_logging()
log = get_logger(__name__)


def _build_server(jira: JiraClient) -> Server:
    server = Server("squad-sense-jira")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_issue",
                description=(
                    "Leitura completa de uma issue Jira pelo key (ex: SSD-21). "
                    "Use para confirmar contexto antes de comentar."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Issue key (ex: SSD-21)",
                        },
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="list_comments",
                description=(
                    "Lista comentários de uma issue. Use para detectar respostas "
                    "do squad ao agente — ex: 'ss-skip duplicate' = rejeição."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="add_comment",
                description=(
                    "Posta um comentário em uma issue. Esta é a ação primária "
                    "do Squad Sense — é como as recomendações chegam no squad."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "body": {
                            "type": "string",
                            "description": "Markdown do comentário",
                        },
                    },
                    "required": ["key", "body"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        log.info("mcp_call_tool", name=name, args_keys=list(arguments.keys()))
        try:
            if name == "get_issue":
                issues = await jira.search_issues(
                    project_key=arguments["key"].split("-")[0],
                    max_results=500,
                )
                target = next((i for i in issues if i.key == arguments["key"]), None)
                if target is None:
                    return [_err_text(f"issue {arguments['key']} não encontrada")]
                return [_json_text(target.model_dump(mode="json"))]

            if name == "list_comments":
                comments = await jira.list_comments(arguments["key"])
                return [
                    _json_text(
                        [c.model_dump(mode="json") for c in comments]
                    )
                ]

            if name == "add_comment":
                comment = await jira.add_comment(
                    issue_key=arguments["key"],
                    body=arguments["body"],
                )
                return [_json_text(comment.model_dump(mode="json"))]

            return [_err_text(f"tool desconhecido: {name}")]

        except JiraClientError as e:
            log.exception("mcp_tool_jira_error", tool=name)
            return [_err_text(f"jira_error: {e.message}")]
        except Exception as e:
            log.exception("mcp_tool_failed", tool=name)
            return [_err_text(f"erro interno: {e}")]

    return server


def _json_text(payload: Any) -> TextContent:
    return TextContent(
        type="text",
        text=json.dumps(payload, default=str, ensure_ascii=False),
    )


def _err_text(message: str) -> TextContent:
    return TextContent(
        type="text",
        text=json.dumps({"error": message}, ensure_ascii=False),
    )


async def main() -> None:
    jira = make_jira_client()
    server = _build_server(jira)
    log.info("mcp_server_starting", jira_mode=jira.mode)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await jira.close()
        log.info("mcp_server_stopped")


if __name__ == "__main__":
    asyncio.run(main())
