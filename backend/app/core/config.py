"""
Central application configuration.

All secrets are read from the environment (or a local .env file) — nothing is
ever hardcoded.  See `.env.example` at the repository root for the full list of
supported variables.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Path anchors
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[2]          # backend/
APP_DIR = BACKEND_DIR / "app"                              # backend/app/
REPO_DIR = BACKEND_DIR.parent                              # repo root
DATA_DIR = BACKEND_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
WORKSPACE_DIR = DATA_DIR / "workspaces"
REPORT_DIR = DATA_DIR / "reports"
EXAMPLES_DIR = APP_DIR / "firmware" / "examples"
HAL_DIR = APP_DIR / "simulator" / "hal"

for _d in (DATA_DIR, UPLOAD_DIR, WORKSPACE_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Runtime settings, populated from env vars / .env."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- App ---------------------------------------------------------------
    app_name: str = "FirmwareAI — Autonomous Embedded Firmware Testing Agent"
    app_version: str = "1.0.0"
    debug: bool = True
    api_prefix: str = "/api"

    # -- Database ----------------------------------------------------------
    # Async SQLite by default; swap for Postgres by setting DATABASE_URL.
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'firmware_ai.db'}"

    # -- CORS --------------------------------------------------------------
    cors_origins: str = "*"

    # -- LLM ---------------------------------------------------------------
    # Provider abstraction: "openai" | "anthropic" | "gemini" | "mock"
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    # When no key is configured the agent degrades to a deterministic,
    # rule-based generator/analyzer instead of failing.  Every artefact is
    # explicitly labelled with the engine that produced it.
    llm_allow_heuristic_fallback: bool = True

    # -- Simulation --------------------------------------------------------
    # "local_deterministic" | "wokwi" | "renode"
    simulator_backend: str = "local_deterministic"
    simulator_compile_timeout: float = 60.0
    simulator_run_timeout: float = 20.0
    cxx_compiler: str = "g++"

    # -- Demo --------------------------------------------------------------
    demo_firmware_file: str = "temperature_controller_buggy.ino"

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_llm_api_key(self) -> str:
        """LLM_API_KEY wins; fall back to standard provider env vars."""
        return (
            self.llm_api_key
            or self.gemini_api_key
            or self.openai_api_key
            or self.anthropic_api_key
            or os.getenv("GEMINI_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
            or os.getenv("ANTHROPIC_API_KEY", "")
        )

    @property
    def resolved_llm_provider(self) -> str:
        provider = self.llm_provider.lower()
        if (
            provider == "openai"
            and os.getenv("GEMINI_API_KEY", "")
            and not self.llm_api_key
            and not os.getenv("OPENAI_API_KEY", "")
        ):
            return "gemini"
        return provider

    @property
    def resolved_llm_model(self) -> str:
        if self.resolved_llm_provider == "gemini" and (self.llm_model in ("gpt-5-mini", "gemini-1.5-flash")):
            return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return self.llm_model

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        provider = self.resolved_llm_provider
        if provider == "anthropic":
            return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        if provider == "gemini":
            return os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    @property
    def llm_enabled(self) -> bool:
        return self.resolved_llm_provider != "mock" and bool(self.resolved_llm_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
