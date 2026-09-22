"""
Modular LLM client
==================
A thin, dependency-light provider abstraction over chat-completion APIs.

Supported providers
-------------------
  openai     — OpenAI & any OpenAI-compatible endpoint (Azure, Together,
               Groq, OpenRouter, local vLLM/Ollama, …) via LLM_BASE_URL.
  anthropic  — Anthropic Messages API.
  gemini     — Google Gemini generateContent API.
  mock       — offline provider (no network) used for CI and demos without
               credentials.

Design notes
------------
* Keys are read from the environment only (never hardcoded, never logged).
* `complete_json` enforces a JSON object response and defensively repairs the
  most common LLM formatting failures (markdown fences, prose preambles,
  trailing commas) before parsing.
* Every call returns rich provenance (`engine`, `model`, latency, token usage)
  so the UI can attribute each artefact to the exact engine that produced it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("firmwareai.llm")


class LLMError(RuntimeError):
    """Raised when the provider cannot deliver a usable response."""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def engine(self) -> str:
        return f"{self.provider}:{self.model}"


# ---------------------------------------------------------------------------
# JSON repair utilities
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """
    Best-effort extraction of a single JSON object from a model response.

    Handles: fenced blocks, leading/trailing prose, trailing commas, and
    unbalanced tails produced by truncated generations.
    """
    if not text or not text.strip():
        raise LLMError("empty response from model")

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(fenced)
    candidates.append(text)

    # Also try the outermost {...} span.
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        for attempt in (cand, _strip_trailing_commas(cand), _balance_braces(cand)):
            try:
                parsed = json.loads(attempt)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    return {"items": parsed}
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from model response (first 400 chars): {text[:400]}")


def _strip_trailing_commas(s: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", s)


def _balance_braces(s: str) -> str:
    """Close unbalanced braces/brackets from a truncated generation."""
    opens = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_str, esc = False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in opens:
            stack.append(opens[ch])
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    tail = '"' if in_str else ""
    return _strip_trailing_commas(s + tail + "".join(reversed(stack)))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class LLMClient:
    """Provider-agnostic async chat client."""

    def __init__(
        self,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.provider = (provider or settings.resolved_llm_provider or "openai").lower()
        self.api_key = api_key if api_key is not None else settings.resolved_llm_api_key
        self.base_url = (base_url or settings.resolved_llm_base_url).rstrip("/")
        self.model = model or settings.resolved_llm_model
        self.timeout = timeout or settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.api_key)

    # ------------------------------------------------------------------
    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResponse:
        if not self.available:
            if settings.llm_allow_heuristic_fallback:
                logger.warning("No LLM API key configured; using deterministic mock response.")
                return self._mock_response(system, user)
            raise LLMError(
                "No LLM API key configured. Set LLM_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY "
                "in the environment, or set LLM_PROVIDER=mock."
            )
        if self.provider == "mock":
            return self._mock_response(system, user)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.provider == "anthropic":
                    return await self._anthropic(system, user, temperature, max_tokens)
                if self.provider == "gemini":
                    return await self._gemini(system, user, temperature, max_tokens, json_mode)
                return await self._openai(system, user, temperature, max_tokens, json_mode)
            except Exception as exc:  # noqa: BLE001 — retried & re-raised below
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 1.5 * (attempt + 1)
                    logger.warning(
                        "LLM call failed (attempt %s/%s): %s — retrying in %.1fs",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
        raise LLMError(f"LLM request failed after {self.max_retries + 1} attempt(s): {last_error}")

    # ------------------------------------------------------------------
    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Chat completion constrained to a JSON object result."""
        response = await self.complete(
            system + "\n\nRespond with a single valid JSON object and nothing else.",
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return extract_json(response.text), response

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------
    async def _openai(
        self, system: str, user: str, temperature: float, max_tokens: int, json_mode: bool
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Newer reasoning models reject `temperature`/`max_tokens`; only send
        # the tuning knobs to models that accept them.
        legacy_tuning = not re.match(r"^(gpt-5|o[13456])", self.model or "")
        if legacy_tuning:
            payload["temperature"] = temperature
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        latency = (time.perf_counter() - t0) * 1000

        if resp.status_code >= 400:
            # Retry once without response_format for endpoints that reject it.
            if json_mode and resp.status_code == 400 and "response_format" in resp.text:
                payload.pop("response_format", None)
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
            if resp.status_code >= 400:
                raise LLMError(f"OpenAI-compatible API error {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"malformed provider response: {json.dumps(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            provider="openai",
            latency_ms=round(latency, 2),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=usage,
        )

    async def _anthropic(
        self, system: str, user: str, temperature: float, max_tokens: int
    ) -> LLMResponse:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": user}],
                },
            )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise LLMError(f"Anthropic API error {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            provider="anthropic",
            latency_ms=round(latency, 2),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            raw=usage,
        )

    async def _gemini(
        self, system: str, user: str, temperature: float, max_tokens: int, json_mode: bool
    ) -> LLMResponse:
        model = self.model.removeprefix("models/")
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/models/{model}:generateContent",
                params={"key": self.api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
            )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise LLMError(f"Gemini API error {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"malformed Gemini response: {json.dumps(data)[:300]}")
        parts = (((candidates[0].get("content") or {}).get("parts")) or [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=model,
            provider="gemini",
            latency_ms=round(latency, 2),
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            raw=usage,
        )

    def _mock_response(self, system: str, user: str) -> LLMResponse:
        """Offline provider: signals callers to use the heuristic engine."""
        return LLMResponse(
            text=json.dumps({"mock": True, "reason": "LLM_PROVIDER=mock"}),
            model="mock",
            provider="mock",
            latency_ms=0.0,
        )


def get_llm_client() -> LLMClient:
    return LLMClient()
