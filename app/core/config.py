from functools import lru_cache
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    project_name: str = "Imagio Voice Bot"
    api_v1_prefix: str = "/api"
    environment: str = "development"
    log_level: str = "INFO"
    telegram_request_timeout: int = 120

    telegram_bot_token: str
    voice_api_base_url: AnyHttpUrl = "https://voiceapi.csv666.ru/api"
    voice_api_key: str = ""
    voice_api_keys_raw: str = ""
    voice_api_generation_mode: str = "quality"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    admin_ids: List[int] = []
    proxy_url: Optional[str] = None
    use_proxy: bool = False
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    proxy_list: Optional[str] = None

    # --- WayForPay Payments ---
    wayforpay_merchant_login: Optional[str] = None
    wayforpay_merchant_secret: Optional[str] = None
    wayforpay_merchant_password: Optional[str] = None
    wayforpay_merchant_domain: str = "imagio.bot"
    webhook_base_url: Optional[AnyHttpUrl] = None
    subscription_currency: str = "USD"

    bot_default_language: str = "uk"

    # --- OpenAI (story-to-images) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def split_admin_ids(cls, value) -> List[int]:
        if not value:
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [int(x) for x in value]
        if isinstance(value, str):
            # Strip brackets: "[123,456]" -> "123,456"
            value = value.strip().strip("[]")
            ids: List[int] = []
            for item in value.split(","):
                item = item.strip()
                if not item:
                    continue
                try:
                    ids.append(int(item))
                except ValueError:
                    continue
            return ids
        return []

    @property
    def voice_api_keys(self) -> List[str]:
        """Parse comma-separated keys from raw string, fall back to single key."""
        keys: List[str] = []
        if self.voice_api_keys_raw:
            keys = [k.strip() for k in self.voice_api_keys_raw.split(",") if k.strip()]
        if not keys and self.voice_api_key:
            keys = [self.voice_api_key]
        return keys

    @field_validator("bot_default_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        allowed = {"uk", "en", "es"}
        return value if value in allowed else "uk"

    @property
    def resolved_proxy_url(self) -> Optional[str]:
        if self.proxy_url:
            return self.proxy_url
        if not self.use_proxy or not self.proxy_host or not self.proxy_port:
            return None

        credentials = ""
        if self.proxy_username and self.proxy_password:
            credentials = f"{self.proxy_username}:{self.proxy_password}@"

        return f"http://{credentials}{self.proxy_host}:{self.proxy_port}"

    @property
    def payments_enabled(self) -> bool:
        """True only when WayForPay credentials are configured."""
        return bool(self.wayforpay_merchant_login and self.wayforpay_merchant_secret)

    @property
    def payment_service_url(self) -> Optional[str]:
        """Webhook URL for WayForPay serviceUrl parameter."""
        if self.webhook_base_url:
            base = str(self.webhook_base_url).rstrip("/")
            return f"{base}/api/payments/wayforpay/webhook"
        return None

    @property
    def payment_form_url(self) -> Optional[str]:
        """Base URL for /api/payments/pay form endpoint."""
        if self.webhook_base_url:
            base = str(self.webhook_base_url).rstrip("/")
            return f"{base}/api/payments/pay"
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
