from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_env: str = Field(alias='APP_ENV', default='local')
    app_name: str = Field(alias='APP_NAME', default='hastlefam')
    log_level: str = Field(alias='LOG_LEVEL', default='INFO')

    database_url: str = Field(alias='DATABASE_URL')
    alembic_database_url: str = Field(alias='ALEMBIC_DATABASE_URL')

    telegram_bot_token: str | None = Field(alias='TELEGRAM_BOT_TOKEN', default=None)
    openai_api_key: str = Field(alias='OPENAI_API_KEY')
    openai_model: str = Field(alias='OPENAI_MODEL', default='gpt-4.1-mini')
    redis_url: str = Field(alias='REDIS_URL', default='redis://localhost:6379/0')
    insights_enabled: bool = Field(alias='INSIGHTS_ENABLED', default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
