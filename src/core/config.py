from pathlib import Path
from typing import Any, Dict
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    GEMINI_API_KEY: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")
    OPENAI_API_KEY: str = Field(default="")

    LANGSMITH_TRACING: bool = Field(default=False)
    LANGSMITH_API_KEY: str = Field(default="")
    LANGSMITH_PROJECT: str = Field(default="multi-agent-mobile-dev")

    DATABASE_URL: str = Field(default="postgresql://postgres:postgres@localhost:5432/multi_agent_db")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    GITHUB_TOKEN: str = Field(default="")
    DOCKER_HOST: str = Field(default="npipe:////./pipe/docker_engine")

    # Configuration base paths
    BASE_DIR: Path = Path(__file__).parent.parent.parent

    @property
    def guardrails(self) -> Dict[str, Any]:
        """Loads guardrails from guardrails.yaml config file."""
        path = self.BASE_DIR / "config" / "guardrails.yaml"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}

    @property
    def litellm_config(self) -> Dict[str, Any]:
        """Loads LiteLLM configuration from litellm_config.yaml."""
        path = self.BASE_DIR / "config" / "litellm_config.yaml"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}

settings = Settings()
