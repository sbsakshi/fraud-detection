from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or backend/.env).

    The defaults are for local development only; docker-compose passes real
    values through from the repo-root .env (see .env.example).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://finsight:finsight@localhost:5432/finsight"
    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173"
    # Replay persisted transactions into the in-memory graph at startup, so a
    # restart doesn't silently wipe every account's graph history.
    rebuild_graph_on_startup: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
