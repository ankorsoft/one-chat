"""
Application configuration using Pydantic Settings.
Supports hot-reload of secrets via Docker Secrets strategy.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    
    database_url: str
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    
    model_config = SettingsConfigDict(env_prefix="DATABASE_")


class RedisSettings(BaseSettings):
    """Redis configuration."""
    
    redis_url: str
    redis_password: Optional[str] = None
    
    model_config = SettingsConfigDict(env_prefix="REDIS_")


class MinIOSettings(BaseSettings):
    """MinIO/S3 configuration."""
    
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str = "onechat-media"
    use_ssl: bool = False
    
    model_config = SettingsConfigDict(env_prefix="MINIO_")


class ClamAVSettings(BaseSettings):
    """ClamAV configuration."""
    
    host: str = "clamav"
    port: int = 3310
    timeout: int = 30
    
    model_config = SettingsConfigDict(env_prefix="CLAMAV_")


class JWTSettings(BaseSettings):
    """JWT authentication configuration."""
    
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    pepper: str
    
    model_config = SettingsConfigDict(env_prefix="JWT_")


class CSRFSettings(BaseSettings):
    """CSRF protection configuration."""
    
    secret_key: str
    cookie_name: str = "csrf_token"
    header_name: str = "X-CSRF-Token"
    
    model_config = SettingsConfigDict(env_prefix="CSRF_")


class ChannelSettings(BaseSettings):
    """External channel API configuration."""
    
    # Telegram
    telegram_bot_token: Optional[str] = None
    
    # VK
    vk_group_token: Optional[str] = None
    vk_group_id: Optional[int] = None
    vk_confirmation_code: str = "confirm123"  # Set in VK Callback API settings
    
    # WhatsApp (Meta Cloud)
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    whatsapp_webhook_verify_token: Optional[str] = None
    whatsapp_app_secret: Optional[str] = None
    
    # MAX (MasterBot)
    max_api_token: Optional[str] = None
    max_bot_id: Optional[str] = None
    max_webhook_secret: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
    )


class MonitoringSettings(BaseSettings):
    """Monitoring and observability configuration."""
    
    sentry_dsn: Optional[str] = None
    sentry_environment: str = "development"
    prometheus_enabled: bool = True
    
    model_config = SettingsConfigDict(env_prefix="SENTRY_")


class AppSettings(BaseSettings):
    """Main application settings."""
    
    app_name: str = "onechat"
    app_env: str = "development"
    debug: bool = False
    
    # Rate limiting
    rate_limit_default: int = 100
    rate_limit_window: int = 60
    
    # WebSocket
    ws_heartbeat_interval: int = 30
    
    # Feature flags
    feature_telegram: bool = True
    feature_vk: bool = True
    feature_whatsapp: bool = True
    feature_max: bool = True
    
    # Nested settings
    database: DatabaseSettings
    redis: RedisSettings
    minio: MinIOSettings
    clamav: ClamAVSettings
    jwt: JWTSettings
    csrf: CSRFSettings
    channels: ChannelSettings
    monitoring: MonitoringSettings
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    @classmethod
    @lru_cache
    def get(cls) -> "AppSettings":
        """Get cached settings instance."""
        return cls()


def get_settings() -> AppSettings:
    """Get application settings singleton."""
    return AppSettings.get()
