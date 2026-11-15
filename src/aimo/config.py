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
    # The interactive docs and the OpenAPI document are for local development only (Q-72).
    api_docs_enabled: bool = False
    # `auto` is a legacy live alias; `fixture` is accepted only by the test harness.
    upstream_mode: Literal["auto", "fixture", "live"] = "live"
    valio_aimo_base_url: str = "https://junction26.valioaimo.fi"
    valio_aimo_api_key: str = ""
    # SUP-007: ids per price/availability request; the supplier accepts 1 to 1000.
    supplier_lookup_batch_size: int = Field(default=100, ge=1, le=1000)
    embedding_model: str = EMBEDDING_MODEL
    embedding_model_revision: str = ""
    embedding_backend: Literal["google", "sentence_transformers", "fixture", "openrouter"] = (
        "google"
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
    # Scheduled (standing) orders: runs start from this Helsinki hour on the scheduled date.
    scheduler_run_after_hour: int = Field(default=6, ge=0, le=23)
    scheduler_max_active_schedules: int = Field(default=20, ge=1, le=20)
    scheduler_max_attempts: int = Field(default=5, ge=1, le=10)
    scheduler_pass_interval_seconds: float = Field(default=30, ge=1, le=3600)
    scheduler_max_runs_per_pass: int = Field(default=50, ge=1, le=500)
    # CNF-039: a date missed by a short outage still runs, late, while `now` is at most this many hours
    # after its run time; later than that it is a RUN_MISSED disruption.
    scheduler_grace_hours: float = Field(default=6, ge=0, le=72)
    # CNF-038: a demo switch (off by default). On: a first run date may be today and the customer
    # can trigger the next run at once (POST /api/schedules/{id}/run-now). Every check still applies.
    scheduler_demo_mode: bool = False
    # New chat messages one account may send per rolling hour (CHAT_RATE_LIMIT, 429, beyond it).
    # Retries of an accepted message and confirmation turns never count. Raise it for testing.
    chat_messages_per_hour: int = Field(default=60, ge=1, le=2000)
    # Queued or running chat turns one account may have at once, across its conversations
    # (CHAT_BUSY, 429, beyond it). Raise it for testing with several parallel conversations.
    chat_active_turns_per_buyer: int = Field(default=3, ge=1, le=12)
    # Demo clock (owner Q-115): a per-buyer simulated time that moves only the derived fulfilment
    # status and the scheduler. Off by default; refused at startup with the live supplier.
    demo_clock_enabled: bool = False
    # CNF-021: days after a proposal's current revision expired before an unfinished (never ordered)
    # proposal and its approvals may be removed by `aimo purge-proposals` (an operator command run
    # with the schema owner's DATABASE_URL; the runtime role cannot delete history).
    unfinished_proposal_retention_days: int = Field(default=30, ge=1, le=3650)
    # Native Google credentials shared by chat, decisions, embeddings and images.
    gemini_api_key: str = Field(default="", repr=False)
    voice_enabled: bool = True
    voice_model: str = "gemini-3.8-live"
    cloudinary_url: str = Field(default="", repr=False)
    recipe_images_enabled: bool = True
    recipe_image_model: str = "gemini-nano-banana-2.1"
    recipe_image_timeout_seconds: float = Field(default=45, gt=0, le=60)
    recipe_image_hourly_limit: int = Field(default=5, ge=1, le=60)
    llm_provider: Literal["google", "openrouter"] = "google"
    guardrail_provider: Literal["google", "openrouter"] = "google"
    # Legacy OpenAI-compatible credentials are used only with an explicit provider selection.
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "gemini-4-carbon"
    llm_timeout_seconds: float = Field(default=45, gt=0, le=60)
    # Leave at least a minute for final persistence before the 240-second worker lease.
    llm_turn_timeout_seconds: float = Field(default=180, gt=0, le=180)
    llm_reasoning_effort: Literal["", "low", "medium", "high"] = "low"
    llm_max_completion_tokens: int = Field(default=8192, ge=1024, le=32768)
    llm_max_tool_rounds: int = Field(default=20, ge=1, le=24)
    # Semantic guardrails (Gemini Decision 1 with GEMINI_API_KEY): enforce, shadow
    # (record only) or off. Deterministic purchasing controls always apply. See docs/guardrails.md.
    guardrail_mode: Literal["off", "shadow", "enforce"] = "enforce"
    # After a chat turn that changed the cart, prepare the basket from it (see docs/cart-purchase.md).
    cart_auto_prepare: bool = True
    # Server-owned stop control for the agent loop (docs/agent-stop-control.md): completion
    # guidance, optional-tool discipline after a basket, one bounded continuation, end reasons.
    agent_stop_control: bool = True
    # Server-owned phases (understand, recipe, match, prepare, finish; docs/agent-phases.md): each round's
    # phase is derived and decides the visible tools and the guidance. Needs agent_stop_control.
    agent_phases: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
