"""Runtime configuration, read from ``CODEJUDGE_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str) -> str:
    return os.environ.get(f"CODEJUDGE_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite:///./codejudge.db")
    )
    # "docker" (default, production) or "local" (development / CI without Docker).
    sandbox_backend: str = field(default_factory=lambda: _env("SANDBOX_BACKEND", "docker"))
    sandbox_image: str = field(
        default_factory=lambda: _env("SANDBOX_IMAGE", "codejudge-sandbox:latest")
    )
    # The local backend executes code on the host with only rlimits for
    # protection. It must be opted into explicitly.
    allow_local_sandbox: bool = field(
        default_factory=lambda: _env_bool("ALLOW_LOCAL_SANDBOX", False)
    )
    # API servers enqueue work; only workers execute it. Setting this lets a
    # single process do both (handy for demos, never for production).
    inline_worker: bool = field(default_factory=lambda: _env_bool("INLINE_WORKER", False))
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", True))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: _env("LLM_EFFORT", "medium"))
    api_token: str | None = field(default_factory=lambda: os.environ.get("CODEJUDGE_API_TOKEN"))
    github_token: str | None = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN"))
    github_webhook_secret: str | None = field(
        default_factory=lambda: os.environ.get("CODEJUDGE_GITHUB_WEBHOOK_SECRET")
    )
    max_candidates: int = field(default_factory=lambda: int(_env("MAX_CANDIDATES", "8")))
    max_file_bytes: int = field(
        default_factory=lambda: int(_env("MAX_FILE_BYTES", str(256 * 1024)))
    )
    worker_poll_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_POLL_SECONDS", "1.0"))
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
