"""Local model settings: config.py (OLLAMA_*), llm.get_llm for Ollama, docker-compose and .env.example.

Building a ChatOllama makes no request, so these run offline.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import Settings  # noqa: E402
from llm import get_llm  # noqa: E402


def local(**kw):
    return Settings(llm_provider="ollama", groq_api_key="", **kw)


# ---------------------------------------------------------------- config

def test_default_provider_is_still_auto_and_falls_back_to_ollama():
    # The value at import depends on the developer's .env, so check the code's default itself.
    assert '_env("LLM_PROVIDER", "auto")' in (ROOT_DIR / "config.py").read_text(encoding="utf-8")
    assert Settings(llm_provider="auto", groq_api_key="").provider == "ollama"


def test_fast_model_defaults_to_the_main_model():
    cfg = local(ollama_model="qwen3:8b", ollama_fast_model="")
    assert cfg.model_name("smart") == "qwen3:8b" and cfg.model_name("fast") == "qwen3:8b"


def test_fast_model_is_used_for_role_fast():
    cfg = local(ollama_model="qwen3:8b", ollama_fast_model="qwen3:4b")
    assert cfg.model_name("smart") == "qwen3:8b" and cfg.model_name("fast") == "qwen3:4b"


def test_ollama_defaults():
    cfg = local()
    assert cfg.ollama_num_ctx == 8192 and cfg.ollama_num_predict == 800 and cfg.ollama_keep_alive == "30m"


# ---------------------------------------------------------------- get_llm (Ollama)

def test_ollama_client_gets_context_no_thinking_keep_alive_and_token_cap():
    model = get_llm(local(ollama_model="qwen3:8b", ollama_base_url="http://localhost:11434"))
    assert type(model).__name__ == "ChatOllama"
    assert model.model == "qwen3:8b" and model.base_url == "http://localhost:11434"
    assert model.num_ctx == 8192
    assert model.reasoning is False
    assert model.keep_alive == "30m"
    assert model.num_predict == 800


def test_role_fast_picks_the_fast_model():
    assert get_llm(local(ollama_model="big", ollama_fast_model="small"), role="fast").model == "small"
    assert get_llm(local(ollama_model="big", ollama_fast_model="small"), role="smart").model == "big"


def test_per_call_overrides_and_pass_through():
    model = get_llm(local(), num_predict=200, format="json", num_ctx=4096, reasoning=True, keep_alive="5m", temperature=0)
    assert model.num_predict == 200 and model.num_ctx == 4096
    assert model.format == "json"  # passed straight through to ChatOllama
    assert model.reasoning is True and model.keep_alive == "5m" and model.temperature == 0


def test_max_tokens_is_accepted_as_num_predict():
    assert get_llm(local(), max_tokens=123).num_predict == 123


def test_settings_change_the_defaults():
    model = get_llm(local(ollama_num_ctx=16384, ollama_num_predict=400, ollama_keep_alive="1h"))
    assert (model.num_ctx, model.num_predict, model.keep_alive) == (16384, 400, "1h")


# ---------------------------------------------------------------- docker-compose.yml

@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_app_reads_ollama_url_from_env_with_bundled_default(compose):
    env = compose["services"]["app"]["environment"]
    assert "OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://ollama:11434}" in env
    assert "host.docker.internal:host-gateway" in compose["services"]["app"].get("extra_hosts", [])


def test_compose_keeps_the_fallback_model_services(compose):
    services = compose["services"]
    assert {"ollama", "model-pull", "app"} <= set(services)
    assert "ports" not in services["ollama"]  # never clashes with a native Ollama on 11434
    assert "${OLLAMA_MODEL:-qwen3:4b}" in " ".join(services["model-pull"]["entrypoint"])
    assert services["app"]["command"].startswith("streamlit run app.py --server.port 8000 --server.address 0.0.0.0")


def test_compose_app_never_waits_for_the_model_download(compose):
    deps = compose["services"]["app"]["depends_on"]
    assert "model-pull" not in deps  # the download runs in the background
    assert deps["ollama"]["condition"] == "service_started"
    assert deps["ollama"].get("required") is False  # the app starts even if ollama is stopped
    assert "OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3:4b}" in compose["services"]["app"]["environment"]


def test_compose_writes_decision_log_to_a_mounted_folder(compose):
    app = compose["services"]["app"]
    log_path = next(e.split("=", 1)[1] for e in app["environment"] if e.startswith("DECISION_LOG_PATH="))
    mounts = {v.split(":", 1)[1]: v.split(":", 1)[0] for v in app["volumes"]}
    folder = str(Path(log_path).parent).replace("\\", "/")
    assert mounts.get(folder) == ".", "the log's folder must be the repo folder mounted from the host"
    assert Path(log_path).name == "decision_log.json"


def test_docker_image_never_contains_secrets_or_local_envs():
    ignored = (ROOT_DIR / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".env", ".venv/", ".cache/", "decision_log.json"):
        assert pattern in ignored, pattern
    assert "!.env.example" in ignored


# ---------------------------------------------------------------- .env.example

def test_env_example_documents_the_local_setup_with_placeholders_only():
    text = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
    for key in ("LLM_PROVIDER=", "OLLAMA_MODEL=", "OLLAMA_FAST_MODEL=", "OLLAMA_NUM_CTX=", "OLLAMA_NUM_PREDICT=",
                "OLLAMA_KEEP_ALIVE=", "host.docker.internal"):
        assert key in text, key
    groq_key = next(line for line in text.splitlines() if line.startswith("GROQ_API_KEY="))
    assert groq_key == "GROQ_API_KEY="  # never a real key
