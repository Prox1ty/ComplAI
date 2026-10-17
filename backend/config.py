"""Runtime configuration read from the environment (and ``.env`` if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional at import time so pure tools/tests work without it
    from dotenv import load_dotenv

    # override=True: .env is the source of truth. Without it, stale variables
    # already in the shell (VS Code injects .env into terminals when they open)
    # silently win over later edits to .env.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]


def _project_path(p: str) -> Path:
    """Relative paths in .env are relative to the project root, not the shell's cwd."""
    path = Path(p).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    # LLM
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").strip().lower())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    reasoning_effort: str = field(default_factory=lambda: os.getenv("REASONING_EFFORT", "low"))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    small_model: str = field(default_factory=lambda: os.getenv("SMALL_MODEL", "claude-haiku-5-5"))
    large_model: str = field(default_factory=lambda: os.getenv("LARGE_MODEL", "claude-sonnet-5-5"))
    tpm_limit: int = field(default_factory=lambda: _int("LLM_TPM_LIMIT", 40_000))
    rpm_limit: int = field(default_factory=lambda: _int("LLM_RPM_LIMIT", 50))
    llm_concurrency: int = field(default_factory=lambda: _int("LLM_CONCURRENCY", 3))
    run_token_ceiling: int = field(default_factory=lambda: _int("RUN_TOKEN_CEILING", 150_000))
    llm_cache: bool = field(default_factory=lambda: _bool("LLM_CACHE", True))

    # Search
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    web_search_enabled: bool = field(default_factory=lambda: _bool("WEB_SEARCH_ENABLED", True))

    # Retrieval
    embed_backend: str = field(default_factory=lambda: os.getenv("EMBED_BACKEND", "st"))  # st | hash
    embed_model: str = field(default_factory=lambda: os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small"))
    vector_backend: str = field(default_factory=lambda: os.getenv("VECTOR_BACKEND", "sqlite"))  # sqlite (sqlite-vec index) | sqlite-plain | chroma | memory
    coverage_high: float = field(default_factory=lambda: _float("COVERAGE_HIGH", 0.88))
    coverage_low: float = field(default_factory=lambda: _float("COVERAGE_LOW", 0.80))

    # App
    data_dir: Path = field(default_factory=lambda: _project_path(os.getenv("DATA_DIR", "data")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    )
    fake_pipeline: bool = field(default_factory=lambda: _bool("FAKE_PIPELINE", False))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 10))

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.runs_dir, self.cache_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()


def reload_settings() -> Settings:
    """Re-read the environment (used by tests)."""
    global settings
    new = Settings()
    settings.__dict__.update(new.__dict__)
    return settings
