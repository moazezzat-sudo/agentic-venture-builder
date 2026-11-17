"""Single place that reads settings from the environment.

Every module imports settings from here instead of reading os.environ itself,
so the model, provider and paths can be changed in one place (.env).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

try:  # read a local .env when running outside Docker
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env", override=False)
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # Model provider: "auto" (Groq if GROQ_API_KEY is set, otherwise local Ollama),
    # "groq" (free tier), "ollama" (local, free) or "openai_compatible".
    llm_provider: str = _env("LLM_PROVIDER", "auto")
    # Groq free tier. The key lives only in each person's local .env, never in git.
    groq_api_key: str = _env("GROQ_API_KEY", "")
    groq_base_url: str = _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_model: str = _env("GROQ_MODEL", "openai/gpt-oss-120b")
    groq_fast_model: str = _env("GROQ_FAST_MODEL", "openai/gpt-oss-20b")
    llm_max_retries: int = int(_env("LLM_MAX_RETRIES", "6"))
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = _env("OLLAMA_MODEL", "qwen3:8b")
    # Model for role="fast" with Ollama; empty means OLLAMA_MODEL (one model to pull).
    ollama_fast_model: str = _env("OLLAMA_FAST_MODEL", "")
    ollama_num_ctx: int = int(_env("OLLAMA_NUM_CTX", "8192"))
    ollama_num_predict: int = int(_env("OLLAMA_NUM_PREDICT", "800"))
    ollama_keep_alive: str = _env("OLLAMA_KEEP_ALIVE", "30m")
    llm_temperature: float = float(_env("LLM_TEMPERATURE", "0.2"))
    # Optional free-tier endpoint. Never required; the key lives only in the local .env.
    openai_compat_base_url: str = _env("OPENAI_COMPAT_BASE_URL", "")
    openai_compat_model: str = _env("OPENAI_COMPAT_MODEL", "")
    openai_compat_api_key: str = _env("OPENAI_COMPAT_API_KEY", "")
    # USD per 1,000 tokens. 0 for local models.
    llm_cost_per_1k_tokens: float = float(_env("LLM_COST_PER_1K_TOKENS", "0"))

    # Paths
    outputs_dir: Path = ROOT_DIR / _env("OUTPUTS_DIR", "outputs")
    decision_log_path: Path = ROOT_DIR / _env("DECISION_LOG_PATH", "decision_log.json")
    cache_dir: Path = ROOT_DIR / _env("CACHE_DIR", ".cache")
    checkpoint_db: Path = ROOT_DIR / _env("CHECKPOINT_DB", ".cache/checkpoints.sqlite")

    # Founder control. Approval is always required; this flag exists only so the
    # setting is visible. Code must not skip approval when it is false.
    require_founder_approval: bool = True

    @property
    def provider(self) -> str:
        """The provider actually used, with "auto" resolved."""
        if self.llm_provider == "auto":
            return "groq" if self.groq_api_key else "ollama"
        return self.llm_provider

    def model_name(self, role: str = "smart") -> str:
        if self.provider == "groq":
            return self.groq_fast_model if role == "fast" else self.groq_model
        if self.provider == "openai_compatible":
            return self.openai_compat_model
        if role == "fast" and self.ollama_fast_model:
            return self.ollama_fast_model
        return self.ollama_model


settings = Settings()


def get_checkpointer(cfg: Settings | None = None):
    """SQLite checkpointer for LangGraph, so gates can pause (interrupt) and runs can resume.

    Note: SqliteSaver is used directly, not as a context manager.
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    cfg = cfg or settings
    cfg.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(str(cfg.checkpoint_db), check_same_thread=False))
