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
    upstream_mode: Literal["fixture", "live"] = "fixture"
    valio_aimo_base_url: str = "https://junction26.valioaimo.fi"
    valio_aimo_api_key: str = ""
    embedding_model: str = EMBEDDING_MODEL
    embedding_model_revision: str = ""
    embedding_backend: Literal["sentence_transformers", "fixture"] = "sentence_transformers"
    catalog_generations_to_keep: int = Field(default=2, ge=1, le=10)
    proposal_ttl_seconds: int = 900
    # Conversational provider configuration is independent of local embeddings.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = Field(default=20, gt=0, le=30)
    llm_max_tool_rounds: int = Field(default=20, ge=1, le=24)


@lru_cache
def settings() -> Settings:
    return Settings()
