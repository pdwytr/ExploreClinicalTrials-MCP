"""Configuration from environment variables, or a .env file in the project root for local dev.

Copy .env.example to .env and fill it in. Secrets never go in code or git.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    openai_api_key: SecretStr
    # e.g. "openai:gpt-5.4". CHEIRON_PLANNER_MODEL is the name from before the rename.
    exploreclinicaltrials_planner_model: str = Field(
        validation_alias=AliasChoices("EXPLORECLINICALTRIALS_PLANNER_MODEL", "CHEIRON_PLANNER_MODEL")
    )


@lru_cache
def get_settings() -> Settings:
    """Read once per process; raises a validation error naming any missing variable."""
    return Settings()
