"""One model client for every agent.

    from llm import get_llm, usage_cost
    model = get_llm()              # strong model (scoring, skeptic, coach)
    fast = get_llm(role="fast")    # cheaper model (weigher, summaries) -> saves rate limit
    reply = model.invoke("...")
    tokens, usd = usage_cost(reply)

Provider is chosen in .env: LLM_PROVIDER=auto uses Groq's free tier when
GROQ_API_KEY is set and falls back to local Ollama otherwise, so the repo
still runs for someone without a key. Rate-limit errors (HTTP 429) are
retried with backoff (LLM_MAX_RETRIES).
"""

from __future__ import annotations

from typing import Any

from config import Settings, settings as default_settings


def get_llm(cfg: Settings | None = None, role: str = "smart", **overrides: Any):
    """Return a LangChain chat model for the configured provider.

    role="smart" for judgement-heavy nodes, role="fast" for light ones.
    """
    cfg = cfg or default_settings
    provider = cfg.provider
    if provider == "groq":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=overrides.pop("model", cfg.model_name(role)),
            base_url=cfg.groq_base_url,
            api_key=cfg.groq_api_key,
            temperature=overrides.pop("temperature", cfg.llm_temperature),
            max_retries=overrides.pop("max_retries", cfg.llm_max_retries),
            **overrides,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        # Defaults for local runs; every one can be overridden per call, and any other
        # ChatOllama option (for example format="json") is passed straight through.
        return ChatOllama(
            model=overrides.pop("model", cfg.model_name(role)),
            base_url=overrides.pop("base_url", cfg.ollama_base_url),
            temperature=overrides.pop("temperature", cfg.llm_temperature),
            # Ollama's default context is small and silently cuts long prompts.
            num_ctx=overrides.pop("num_ctx", cfg.ollama_num_ctx),
            # Max tokens to generate (Ollama's name for max_tokens).
            num_predict=overrides.pop("num_predict", overrides.pop("max_tokens", cfg.ollama_num_predict)),
            # False turns off qwen3's thinking block, which makes runs slow.
            reasoning=overrides.pop("reasoning", False),
            # Keep the model loaded between calls so each step doesn't reload it.
            keep_alive=overrides.pop("keep_alive", cfg.ollama_keep_alive),
            **overrides,
        )
    if provider == "openai_compatible":
        if not (cfg.openai_compat_base_url and cfg.openai_compat_model and cfg.openai_compat_api_key):
            raise RuntimeError(
                "LLM_PROVIDER=openai_compatible needs OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_MODEL "
                "and OPENAI_COMPAT_API_KEY in your local .env. The default local Ollama provider needs none."
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=overrides.pop("model", cfg.openai_compat_model),
            base_url=cfg.openai_compat_base_url,
            api_key=cfg.openai_compat_api_key,
            temperature=overrides.pop("temperature", cfg.llm_temperature),
            max_retries=overrides.pop("max_retries", cfg.llm_max_retries),
            **overrides,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {cfg.llm_provider!r} (use 'auto', 'groq', 'ollama' or 'openai_compatible')")


def usage_cost(message: Any, cfg: Settings | None = None) -> tuple[int, float]:
    """Return (total_tokens, cost_usd) for a model reply, from its usage metadata."""
    cfg = cfg or default_settings
    usage = getattr(message, "usage_metadata", None) or {}
    tokens = int(usage.get("total_tokens", 0) or 0)
    return tokens, round(tokens / 1000 * cfg.llm_cost_per_1k_tokens, 6)
