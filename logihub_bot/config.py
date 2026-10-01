"""Настройки ботов из переменных окружения (файл .env) и сведения о компании."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Все сроки считаются по хабаровскому времени (UTC+10), как на складе в Комсомольске-на-Амуре
TZ = timezone(timedelta(hours=10), "ХБ")

COMPANY = {
    "name": "ООО «ЛогиХаб»",
    "brand": "ЛогиХаб",
    "slogan": "Каждая поставка – под контролем, в одном окне",
    "hub": "Комсомольск-на-Амуре, логистический хаб",
    "hours": "офис – пн–пт 9:00–18:00 (хабаровское время), приём заявок в боте – круглосуточно",
    "wiki": "https://starpxand.github.io/logihub-wiki/",
    # реквизиты учебного проекта – условные
    "inn": "0000000000",
    "kpp": "000000000",
    "account": "00000000000000000000",
    "bank": "учебный банк",
}

PAYMENT_DAYS = 3          # этап BPMN 9: оплата в течение 3 дней, иначе заказ отменяется
REMIND_BEFORE_HOURS = 24  # напоминание об оплате за сутки до срока


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


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
    manager_bot_token: str
    manager_code: str = "logihub-manager"
    db_path: str = "logihub_bot.sqlite3"
    orders_csv: str = "data/logistics_orders.csv"
    dashboard_url: str = "http://127.0.0.1:8050"


def load_settings(env_file: str = ".env") -> Settings:
    _load_dotenv(Path(env_file))
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN – получите токен у @BotFather и укажите его в файле .env")
    manager_token = os.getenv("MANAGER_BOT_TOKEN", "")
    if not manager_token:
        raise RuntimeError("Не задан MANAGER_BOT_TOKEN – создайте у @BotFather второго бота для менеджеров "
                           "и укажите его токен в файле .env")
    return Settings(
        bot_token=token,
        manager_bot_token=manager_token,
        manager_code=os.getenv("MANAGER_CODE", "logihub-manager"),
        db_path=os.getenv("DB_PATH", "logihub_bot.sqlite3"),
        orders_csv=os.getenv("ORDERS_CSV", "data/logistics_orders.csv"),
        dashboard_url=os.getenv("DASHBOARD_URL", "http://127.0.0.1:8050"),
    )
