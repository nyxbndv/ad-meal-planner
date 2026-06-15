from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    tandoor_url: str
    tandoor_api_key: str
    recipes_per_week: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
