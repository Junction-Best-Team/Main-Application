from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aimo.model_spec import EMBEDDING_MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://aimo:aimo@localhost:55432/aimo"
    db_pool_max_size: int = Field(default=10, ge=1, le=100)
    db_pool_timeout_seconds: float = Field(default=5, gt=0, le=30)
    forwarded_allow_ips: str = "127.0.0.1,::1"
    public_base_url: str = "http://localhost:8000"
    approval_session_secret: str = ""
    secure_cookies: bool = True
    upstream_mode: Literal["auto", "fixture", "live"] = "auto"
    valio_aimo_base_url: str = "https://junction26.valioaimo.fi"
    valio_aimo_api_key: str = ""
    embedding_model: str = EMBEDDING_MODEL
    embedding_model_revision: str = ""
    embedding_backend: Literal["sentence_transformers", "fixture", "openrouter"] = (
        "sentence_transformers"
    )
    # Search credentials are independent of the conversational provider.
    search_api_key: str = ""
    search_timeout_seconds: float = Field(default=15, gt=0, le=30)
    search_max_attempts: int = Field(default=2, ge=1, le=3)
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    embedding_workers: int = Field(default=4, ge=1, le=4)
    rerank_enabled: bool = True
    rerank_candidates: int = Field(default=30, ge=20, le=80)
    catalog_generations_to_keep: int = Field(default=2, ge=1, le=10)
    # Supplier snapshot download bounds for `aimo sync-catalog` / `aimo ingest --download`.
    catalog_download_timeout_seconds: float = Field(default=60, gt=0, le=300)
    catalog_download_deadline_seconds: float = Field(default=900, gt=0, le=3600)
    catalog_download_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    catalog_download_attempts: int = Field(default=3, ge=1, le=5)
    # Blank uses the system temporary directory; the Job mounts a bounded emptyDir there.
    catalog_work_dir: str = ""
    proposal_ttl_seconds: int = 900
    # Reusable native Google client; independent of the active chat/search providers.
    gemini_api_key: str = Field(default="", repr=False)
    cloudinary_url: str = Field(default="", repr=False)
    recipe_images_enabled: bool = True
    recipe_image_model: str = "gemini-nano-banana-2.1"
    recipe_image_timeout_seconds: float = Field(default=45, gt=0, le=60)
    recipe_image_hourly_limit: int = Field(default=5, ge=1, le=60)
    # Conversational provider configuration is independent of local embeddings.
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-sonnet-5.5"
    llm_timeout_seconds: float = Field(default=45, gt=0, le=60)
    llm_reasoning_effort: Literal["", "low", "medium", "high"] = "low"
    llm_max_completion_tokens: int = Field(default=8192, ge=1024, le=32768)
    llm_max_tool_rounds: int = Field(default=20, ge=1, le=24)
    # Semantic guardrails (TypeSafe Jev through OpenRouter, using LLM_API_KEY): enforce, shadow
    # (record only) or off. Deterministic purchasing controls always apply. See docs/guardrails.md.
    guardrail_mode: Literal["off", "shadow", "enforce"] = "enforce"


@lru_cache
def settings() -> Settings:
    return Settings()
