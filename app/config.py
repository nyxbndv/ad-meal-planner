from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    mealie_url: str
    mealie_api_key: str
    recipes_per_week: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
