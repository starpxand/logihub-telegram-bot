"""Настройки бота из переменных окружения (файл .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    bot_token: str
    manager_code: str = "logihub-manager"
    db_path: str = "logihub_bot.sqlite3"
    orders_csv: str = "data/logistics_orders.csv"
    dashboard_url: str = "http://127.0.0.1:8050"


def load_settings(env_file: str = ".env") -> Settings:
    _load_dotenv(Path(env_file))
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN – получите токен у @BotFather и укажите его в файле .env")
    return Settings(
        bot_token=token,
        manager_code=os.getenv("MANAGER_CODE", "logihub-manager"),
        db_path=os.getenv("DB_PATH", "logihub_bot.sqlite3"),
        orders_csv=os.getenv("ORDERS_CSV", "data/logistics_orders.csv"),
        dashboard_url=os.getenv("DASHBOARD_URL", "http://127.0.0.1:8050"),
    )
