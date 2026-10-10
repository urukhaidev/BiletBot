import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_token: str
    travel_token: str
    llm_key: str
    llm_url: str
    llm_model: str
    database: str
    interval: int
    request_interval: float
    timezone: ZoneInfo
    marker: str
    admin_id: int | None
    openrouter_key: str = ""
    openrouter_proxy: str = ""
    telegram_proxy: str = ""

    @classmethod
    def load(cls):
        load_dotenv()
        required = ["TELEGRAM_BOT_TOKEN", "TRAVELPAYOUTS_TOKEN", "LLM_API_KEY"]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise ValueError("Заполните .env: " + ", ".join(missing))
        interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "1800"))
        request_interval = float(os.getenv("API_REQUEST_INTERVAL_SECONDS", "1"))
        if interval < 1 or request_interval < 0:
            raise ValueError("Интервалы должны быть положительными")
        return cls(
            os.environ[required[0]], os.environ[required[1]], os.environ[required[2]],
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            os.getenv("DATABASE_PATH", "data/biletbot.sqlite3"), interval, request_interval,
            ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
            os.getenv("AFFILIATE_MARKER", "89532"),
            int(os.environ["ADMIN_USER_ID"]) if os.getenv("ADMIN_USER_ID") else None,
            os.getenv("OPENROUTER_API_KEY", ""),
            os.getenv("OPENROUTER_PROXY", ""),
            os.getenv("TELEGRAM_PROXY", ""),
        )
