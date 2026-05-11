"""LLM client — provider-agnostic com Anthropic primário e OpenAI fallback.

Decisões:
- Mesmo Protocol para os dois providers; o Coach Agent não conhece o provider.
- Resposta esperada em JSON {summary, body}; o cliente faz o parse e
  cai num fallback estruturado se o modelo retornar texto livre.
- Anthropic com prompt caching explícito (cache_control no system).
  OpenAI faz caching automático para prompts >= 1024 tokens estáveis.
- Auto-seleção de provider:
    settings.llm_provider explícito vence; senão prefere Anthropic se
    a chave estiver presente; senão OpenAI; senão NullLLM (canned text).
"""

import json
from typing import Protocol, runtime_checkable

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class LLMResponse(BaseModel):
    summary: str
    body: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    raw: str = ""  # texto bruto do modelo, para debug


@runtime_checkable
class LLMClient(Protocol):
    model: str

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
    ) -> LLMResponse: ...

    async def close(self) -> None: ...


def _safe_parse_json(raw: str) -> dict:
    """Parse JSON, descartando markdown fences se vierem."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # tira ```json ... ```
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


def _fallback_response(raw: str, model: str) -> LLMResponse:
    """Quando JSON parse falha: usa o raw inteiro como body, gera summary curto."""
    summary_line = (raw.splitlines() or [""])[0].strip()
    if len(summary_line) > 200:
        summary_line = summary_line[:197] + "…"
    return LLMResponse(summary=summary_line or "(sem summary)", body=raw, model=model, raw=raw)


# ----------------------------------------------------------------- Anthropic


class AnthropicLLM:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
    ) -> LLMResponse:
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            # System prompt cacheado: economiza tokens quando o agente faz
            # várias chamadas no mesmo run (uma por finding/cross-ref).
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

        usage = resp.usage
        input_tokens = getattr(usage, "input_tokens", 0)
        cached_input = getattr(usage, "cache_read_input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0)

        try:
            obj = _safe_parse_json(raw)
            return LLMResponse(
                summary=str(obj.get("summary", "")).strip() or "(sem summary)",
                body=str(obj.get("body", "")).strip() or raw,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input,
                raw=raw,
            )
        except (json.JSONDecodeError, AttributeError):
            log.warning("anthropic_json_parse_failed", model=self.model)
            return _fallback_response(raw, self.model)

    async def close(self) -> None:
        await self._client.close()


# -------------------------------------------------------------------- OpenAI


class OpenAILLM:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        raw = (choice.message.content or "").strip()

        usage = resp.usage
        input_tokens = getattr(usage, "prompt_tokens", 0)
        output_tokens = getattr(usage, "completion_tokens", 0)
        cached_input = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_input = getattr(details, "cached_tokens", 0) or 0

        try:
            obj = _safe_parse_json(raw)
            return LLMResponse(
                summary=str(obj.get("summary", "")).strip() or "(sem summary)",
                body=str(obj.get("body", "")).strip() or raw,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input,
                raw=raw,
            )
        except (json.JSONDecodeError, AttributeError):
            log.warning("openai_json_parse_failed", model=self.model)
            return _fallback_response(raw, self.model)

    async def close(self) -> None:
        await self._client.close()


# ----------------------------------------------------------------- Null/dev


class NullLLM:
    """Roda a pipeline inteira sem API — emite texto canônico."""

    model = "null-llm"

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
    ) -> LLMResponse:
        canned = (
            "[NullLLM] Recomendação não disponível — sem chave de API "
            "configurada. Defina ANTHROPIC_API_KEY ou OPENAI_API_KEY."
        )
        return LLMResponse(summary=canned, body=canned, model=self.model)

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------- factory


def make_llm_client() -> LLMClient:
    forced = (settings.llm_provider or "").lower().strip()

    if forced == "anthropic" and settings.anthropic_api_key:
        log.info("llm_client", impl="anthropic", model=settings.llm_model_anthropic)
        return AnthropicLLM(settings.anthropic_api_key, settings.llm_model_anthropic)

    if forced == "openai" and settings.openai_api_key:
        log.info("llm_client", impl="openai", model=settings.llm_model_openai)
        return OpenAILLM(settings.openai_api_key, settings.llm_model_openai)

    if not forced:
        if settings.anthropic_api_key:
            log.info("llm_client", impl="anthropic", model=settings.llm_model_anthropic)
            return AnthropicLLM(settings.anthropic_api_key, settings.llm_model_anthropic)
        if settings.openai_api_key:
            log.info("llm_client", impl="openai", model=settings.llm_model_openai)
            return OpenAILLM(settings.openai_api_key, settings.llm_model_openai)

    log.warning("llm_client_null", reason="nenhuma chave de LLM configurada")
    return NullLLM()
