from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_character_chat"
    redis_url: str = "redis://localhost:6379/0"

    session_cookie_name: str = "session_id"
    session_ttl_seconds: int = 60 * 60 * 24 * 7
    # Secure requires HTTPS; browsers drop the cookie on local http dev servers, so
    # this defaults to False and must be overridden to True in any deployed env.
    session_cookie_secure: bool = False

    cors_allow_origins: list[str] = ["http://localhost:5173", "http://localhost:5174"]

    aws_region: str = "ap-northeast-2"
    s3_bucket_name: str = "ai-character-chat-assets-dev"
    s3_presigned_url_expires_seconds: int = 900
    # Overridden for local dev/tests to point at a non-AWS S3-compatible endpoint
    # (e.g. `uv run moto_server`); left unset in real AWS environments.
    s3_endpoint_url: str | None = None


settings = Settings()
