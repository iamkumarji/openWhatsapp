"""Centralized settings loaded from environment (12-factor)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    secret_key: str = "change-me"
    internal_token: str = "change-me"
    public_base_url: str = "https://localhost"

    database_url: str = "postgresql+asyncpg://waint:change-me@postgres:5432/waint"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # OIDC / Keycloak
    oidc_jwks_url: str = ""
    keycloak_realm: str = "waint"
    keycloak_client_id: str = "waint-backend"

    # Ollama
    ollama_url: str = "http://ollama:11434"
    llm_intent_model: str = "qwen2.5:7b-instruct"
    llm_render_model: str = "qwen2.5:7b-instruct"
    llm_embed_model: str = "nomic-embed-text"

    # encryption key for oauth_tokens (base64:...)
    encryption_key: str = ""

    # integrations
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
