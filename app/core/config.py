from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Tonic API"
    ENVIRONMENT: str = "local"  # "local" | "production"
    DEBUG: bool = True

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = []

    # Security
    ALLOWED_HOSTS: list[str] = ["*"]

    # Database
    DB_SERVER: str = ""
    DB_PORT: int = 5432
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = ""

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_SERVER}:{self.DB_PORT}/{self.DB_NAME}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
