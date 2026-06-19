from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    tandoor_url: str = ""
    tandoor_api_key: str = ""
    recipes_per_week: int = 7

    mealie_url: str = ""
    mealie_api_key: str = ""
    public_base_url: str = ""
    recipe_pages_dir: str = "app/static_recipes"

    class Config:
        env_file = ".env"


settings = Settings()
