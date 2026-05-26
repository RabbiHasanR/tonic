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

    # JWT auth
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Redis — APQ hash store
    REDIS_URL: str = "redis://redis:6379/0"

    # GraphQL query-shape limits (defense-in-depth against DoS)
    MAX_QUERY_DEPTH: int = 10
    MAX_QUERY_ALIASES: int = 15
    MAX_QUERY_TOKENS: int = 1500
    MAX_PAGE_SIZE: int = 50
    MAX_REQUEST_BYTES: int = 100_000

    # Rate limiting (token bucket, cost = query complexity score)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CAPACITY: int = 1000           # bucket size C (max burst)
    RATE_LIMIT_REFILL_PER_SECOND: float = 50.0  # refill rate R (sustained cost/sec)
    MAX_QUERY_COMPLEXITY: int = 1000          # per-request hard cap
    MUTATION_FLAT_COST: int = 10              # cost per mutation field

    # OpenTelemetry — traces only in Phase 1 (metrics/logs come later)
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "tonic-api"
    OTEL_SERVICE_VERSION: str = "0.1.0"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    OTEL_TRACES_SAMPLER_ARG: float = 1.0      # 1.0 = sample everything (local dev)

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
