"""Клавиатуры бота."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .pricing import CARGO, DESTINATIONS

# Кнопки главного меню
NEW_ORDER = "📦 Новая заявка"
MY_ORDERS = "🗂 Мои заказы"
TRACK = "🔎 Статус заказа"
ACCEPT = "✅ Приёмка груза"
QUEUE = "📋 Заявки на проверку"
IN_WORK = "🚚 Заказы в работе"
KPI = "📊 KPI и дашборд"
HELP = "ℹ️ Помощь"


def _reply(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in rows], resize_keyboard=True)


def client_menu() -> ReplyKeyboardMarkup:
    return _reply([[NEW_ORDER, MY_ORDERS], [TRACK, ACCEPT], [HELP]])


def manager_menu() -> ReplyKeyboardMarkup:
    return _reply([[QUEUE, IN_WORK], [KPI, HELP]])


def _inline(buttons: list[tuple[str, str]], per_row: int = 2) -> InlineKeyboardMarkup:
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r]
                                                 for r in rows])


def destinations() -> InlineKeyboardMarkup:
    return _inline([(city, f"dst:{city}") for city in DESTINATIONS])


def cargo_types() -> InlineKeyboardMarkup:
    return _inline([(c, f"cargo:{c}") for c in CARGO])


def confirm_order() -> InlineKeyboardMarkup:
    return _inline([("✅ Отправить заявку", "order:send"), ("✖️ Отменить", "order:cancel")])


def review(order_id: int) -> InlineKeyboardMarkup:
    return _inline([("✅ Заявка корректна", f"rev:ok:{order_id}"), ("↩️ На уточнение", f"rev:back:{order_id}")])


def work(order_id: int, status: str) -> InlineKeyboardMarkup:
    if status == "confirmed":
        return _inline([("🚚 Отгружен, в пути", f"wrk:transit:{order_id}")], 1)
    return _inline([("⏰ Задержка +1 день", f"wrk:delay:{order_id}"), ("📍 Доставлен", f"wrk:deliver:{order_id}")])


def acceptance(order_id: int) -> InlineKeyboardMarkup:
    return _inline([("✅ Без замечаний – подписать акт", f"acc:ok:{order_id}"),
                    ("⚠️ Есть замечания – претензия", f"acc:claim:{order_id}")], 1)


def close_claim(order_id: int) -> InlineKeyboardMarkup:
    return _inline([("✔️ Урегулировать и закрыть", f"clm:close:{order_id}")], 1)


def kpi(dashboard_url: str) -> InlineKeyboardMarkup:
    kb = _inline([("Месяц", "kpi:M"), ("Квартал", "kpi:Q"), ("Год", "kpi:Y")], 3)
    if dashboard_url.startswith("https://"):
        kb.inline_keyboard.append([InlineKeyboardButton(text="🖥 Открыть дашборд", url=dashboard_url)])
    return kb
