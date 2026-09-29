from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app_user:app_user@localhost:5432/approvals"
    sandbox_url: str = "http://localhost:8001"
    sandbox_api_key: str | None = None
    redis_url: str = "redis://localhost:6379"
    jwt_secret: str | None = None  # HS256 (dev issuer only); production uses jwt_jwks_url

    jwt_issuer: str = "approvals-desk-dev"
    jwt_jwks_url: str | None = None  # set in prod for RS256 OIDC verification
    checkpoint_dsn: str = "postgresql://postgres:postgres@localhost:5432/approvals"
    webhook_url: str | None = None
    slack_signing_secret: str | None = None  # enables POST /integrations/slack/interactions
    console_url: str = "http://localhost:3000"  # base URL used for "Open in console" links
    webhook_secret: str = "dev-webhook-secret"
    async_resume: bool = False  # API enqueues resume to the arq worker instead of running it in-process
    llm_provider: str = "fake"  # fake | anthropic
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_fixture_dir: str = "evals/fixtures"
    llm_fixture_mode: str = "off"  # off | record | replay
    dev_auth: bool = False  # enables POST /dev/token for local demos ONLY
    jaeger_url: str = "http://localhost:16686"

    def validate_for_runtime(self) -> None:
        if self.dev_auth and self.jwt_jwks_url:
            raise ValueError("dev_auth must not be enabled together with a production JWKS issuer")
        if not self.jwt_jwks_url and (not self.jwt_secret or len(self.jwt_secret) < 32):
            raise ValueError("set AD_JWT_JWKS_URL (production) or an AD_JWT_SECRET of at least 32 characters (dev)")

    model_config = {"env_prefix": "AD_"}
