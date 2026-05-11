from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    jira_mock: bool = True

    jira_base_url: str = "https://example.atlassian.net"
    jira_email: str = "you@example.com"
    jira_api_token: str = "changeme"

    jira_project_key: str = Field(default="SSD", min_length=2, max_length=10)
    jira_project_name: str = "Squad Sense Demo"

    log_level: str = "INFO"
    environment: str = "dev"

    mock_state_path: Path = Path("data/mock_jira.json")

    database_url: str = "postgresql+asyncpg://squad:squad@localhost:5434/squad_sense"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    anthropic_api_key: str = ""
    llm_provider: str = ""  # "" = auto, "anthropic" ou "openai"
    llm_model_anthropic: str = "claude-sonnet-4-6"
    llm_model_openai: str = "gpt-4o-mini"

    @field_validator("jira_project_key")
    @classmethod
    def project_key_uppercase(cls, v: str) -> str:
        if not v.isalpha() or not v.isupper():
            raise ValueError("JIRA_PROJECT_KEY deve ter apenas letras maiúsculas")
        return v

    @property
    def jira_credentials_present(self) -> bool:
        return bool(
            self.jira_base_url
            and self.jira_email
            and self.jira_api_token
            and self.jira_api_token != "changeme"
        )


settings = Settings()
