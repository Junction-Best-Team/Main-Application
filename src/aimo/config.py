from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://aimo:aimo@localhost:55432/aimo"
    public_base_url: str = "http://localhost:8000"
    approval_session_secret: str = ""
    secure_cookies: bool = True
    upstream_mode: Literal["fixture", "live"] = "fixture"
    valio_aimo_base_url: str = "https://junction26.valioaimo.fi"
    valio_aimo_api_key: str = ""
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_model_revision: str = ""
    embedding_backend: Literal["sentence_transformers", "fixture"] = "sentence_transformers"
    frontend_dist: str = "frontend/dist"
    proposal_ttl_seconds: int = 900


@lru_cache
def settings() -> Settings:
    return Settings()
