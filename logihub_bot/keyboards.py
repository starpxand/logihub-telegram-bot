"""Клавиатуры ботов."""
from __future__ import annotations

from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .pricing import CARGO, DESTINATIONS
from .storage import CLAIM_KINDS, Driver, Order

# --- главное меню клиента ---
NEW_ORDER = "📦 Новая заявка"
MY_ORDERS = "🗂 Мои заказы"
TRACK = "🔎 Отследить"
TARIFFS = "💰 Тарифы и сроки"
SUPPORT = "💬 Написать менеджеру"
ABOUT = "ℹ️ О компании"

# --- главное меню менеджера ---
QUEUE = "📋 Новые заявки"
PAYMENTS = "💳 Оплаты"
WAREHOUSE = "🏭 Склад"
SHIPPING = "🚚 Рейсы"
CLAIMS = "⚠️ Претензии"
FIND = "🔎 Найти заказ"
SUMMARY = "📈 Сводка"
KPI = "📊 KPI дашборда"
HELP = "ℹ️ Помощь"

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

DELAY_REASONS = {
    "road": "пробка или ДТП на трассе",
    "weather": "неблагоприятные погодные условия",
    "repair": "техническая неисправность транспорта",
    "ferry": "ожидание парома Ванино – Холмск",
    "load": "задержка на погрузке у получателя предыдущего рейса",
}


def _reply(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in rows], resize_keyboard=True)


def client_menu() -> ReplyKeyboardMarkup:
    return _reply([[NEW_ORDER, MY_ORDERS], [TRACK, TARIFFS], [SUPPORT, ABOUT]])


def manager_menu() -> ReplyKeyboardMarkup:
    return _reply([[QUEUE, PAYMENTS], [WAREHOUSE, SHIPPING], [CLAIMS, FIND], [SUMMARY, KPI], [HELP]])


def share_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


def _inline(buttons: list[tuple[str, str]], per_row: int = 2) -> InlineKeyboardMarkup:
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r]
                                                 for r in rows])


def _rows(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r]
                                                 for r in rows if r])


# --- регистрация и оформление заявки (этап 2) ---
def private_person() -> InlineKeyboardMarkup:
    return _inline([("👤 Я частное лицо", "reg:private")], 1)


def destinations() -> InlineKeyboardMarkup:
    return _inline([(city, f"dst:{city}") for city in DESTINATIONS])


def cargo_types() -> InlineKeyboardMarkup:
    return _inline([(c, f"cargo:{c}") for c in CARGO])


def ship_dates(today: date) -> InlineKeyboardMarkup:
    days, day = [], today + timedelta(days=1)
    while len(days) < 6:
        if day.weekday() != 6:  # склад по воскресеньям не отгружает
            days.append((f"{WEEKDAYS[day.weekday()]} {day:%d.%m}", f"shp:{day.isoformat()}"))
        day += timedelta(days=1)
    return _inline(days, 3)


def no_insurance() -> InlineKeyboardMarkup:
    return _inline([("Без страховки", "ins:0")], 1)


def skip_comment() -> InlineKeyboardMarkup:
    return _inline([("Без комментария", "cmt:skip")], 1)


def confirm_order() -> InlineKeyboardMarkup:
    return _inline([("✅ Отправить заявку", "order:send"), ("✖️ Отменить", "order:cancel")])


def calc() -> InlineKeyboardMarkup:
    return _inline([("🧮 Рассчитать мою перевозку", "calc")], 1)


# --- заказы клиента ---
def my_orders(orders: list[Order]) -> InlineKeyboardMarkup:
    from .texts import order_line
    return _inline([(order_line(o), f"co:open:{o.id}") for o in orders], 1)


def doc_buttons(o: Order, has_claim: bool = False) -> list[tuple[str, str]]:
    docs = []
    if o.status not in ("new", "clarify", "cancelled"):
        docs.append(("📄 Счёт", f"doc:inv:{o.id}"))
    if o.status in ("ready", "in_transit", "delayed", "delivered", "accepted", "claim", "closed"):
        docs.append(("📄 ТТН", f"doc:ttn:{o.id}"))
    if o.status == "accepted" or (o.status == "closed" and not has_claim):
        docs.append(("📄 Акт", f"doc:act:{o.id}"))
    return docs


def client_order(o: Order, has_claim: bool = False) -> InlineKeyboardMarkup:
    docs = doc_buttons(o, has_claim)
    actions: list[tuple[str, str]] = []
    if o.status == "clarify":
        actions.append(("✏️ Уточнить заявку", f"co:fix:{o.id}"))
    if o.status == "confirmed":
        actions.append(("💳 Я оплатил", f"co:paid:{o.id}"))
    if o.status == "delivered":
        return _rows([("✅ Принять без замечаний", f"acc:ok:{o.id}")],
                     [("⚠️ Есть замечания – претензия", f"acc:claim:{o.id}")], docs)
    if o.status == "closed" and not o.rating:
        actions.append(("⭐ Оценить доставку", f"co:rate:{o.id}"))
    cancel = [("✖️ Отменить заказ", f"co:cancel:{o.id}")] if o.status in ("new", "clarify", "confirmed") else []
    return _rows(actions, docs, [("🕓 История", f"co:hist:{o.id}")] + cancel)


def payment(o: Order) -> InlineKeyboardMarkup:
    return _rows([("💳 Я оплатил", f"co:paid:{o.id}")], [("✖️ Отменить заказ", f"co:cancel:{o.id}")])


def cancel_confirm(order_id: int) -> InlineKeyboardMarkup:
    return _inline([("Да, отменить", f"co:cancelyes:{order_id}"), ("Нет", f"co:open:{order_id}")])


def fix_menu(order_id: int) -> InlineKeyboardMarkup:
    return _rows([("✏️ Адрес", f"fix:address:{order_id}"), ("✏️ Получатель", f"fix:recipient:{order_id}")],
                 [("✏️ Кол-во мест", f"fix:places:{order_id}"), ("💬 Комментарий", f"fix:comment:{order_id}")],
                 [("📨 Отправить на повторную проверку", f"fix:send:{order_id}")])


def acceptance(order_id: int) -> InlineKeyboardMarkup:
    return _rows([("✅ Принять без замечаний", f"acc:ok:{order_id}")],
                 [("⚠️ Есть замечания – претензия", f"acc:claim:{order_id}")])


def claim_kinds() -> InlineKeyboardMarkup:
    return _inline([(title, f"ck:{kind}") for kind, title in CLAIM_KINDS.items()])


def claim_send() -> InlineKeyboardMarkup:
    return _inline([("📨 Отправить претензию", "cl:send")], 1)


def rating(order_id: int) -> InlineKeyboardMarkup:
    return _inline([(f"{n}⭐", f"rate:{order_id}:{n}") for n in range(1, 6)], 5)


# --- рабочее место менеджера ---
def review(order_id: int) -> InlineKeyboardMarkup:
    return _rows([("✅ Подтвердить и выставить счёт", f"rev:ok:{order_id}")],
                 [("↩️ На уточнение", f"rev:back:{order_id}"), ("✖️ Отклонить", f"rev:decline:{order_id}")])


def pay_control(order_id: int) -> InlineKeyboardMarkup:
    return _rows([("✅ Оплата поступила", f"pay:ok:{order_id}")],
                 [("🔔 Напомнить клиенту", f"pay:remind:{order_id}"), ("📄 Счёт", f"doc:inv:{order_id}")])


def warehouse(o: Order) -> InlineKeyboardMarkup:
    if o.status == "paid":
        return _rows([("🏭 Начать комплектацию", f"wh:start:{o.id}")])
    return _rows([("✅ Укомплектован полностью – оформить ТТН", f"wh:full:{o.id}")],
                 [("➕ Не хватает мест – докомплектовать", f"wh:short:{o.id}")])


def shipping(o: Order) -> InlineKeyboardMarkup:
    docs = [("📄 ТТН", f"doc:ttn:{o.id}")]
    if o.status == "ready" and not o.driver_id:
        return _rows([("👤 Назначить водителя", f"sh:driver:{o.id}")], docs)
    if o.status == "ready":
        return _rows([("🚚 Водитель принял груз – рейс начат", f"sh:go:{o.id}")],
                     [("👤 Сменить водителя", f"sh:driver:{o.id}")] + docs)
    return _rows([("⏰ Отклонение от графика", f"sh:delay:{o.id}")], [("📍 Груз доставлен", f"sh:done:{o.id}")], docs)


def drivers(order_id: int, items: list[Driver]) -> InlineKeyboardMarkup:
    return _inline([(f"{d.name} · {d.plate}", f"drv:{order_id}:{d.id}") for d in items], 1)


def delay_reasons(order_id: int) -> InlineKeyboardMarkup:
    return _inline([(text.capitalize(), f"dr:{order_id}:{code}") for code, text in DELAY_REASONS.items()], 1)


def delay_days(order_id: int, reason: str) -> InlineKeyboardMarkup:
    return _inline([(f"+{d} {'день' if d == 1 else 'дня'}", f"dd:{order_id}:{reason}:{d}") for d in (1, 2, 3)], 3)


def claim_decision(order_id: int) -> InlineKeyboardMarkup:
    return _rows([("💰 Компенсация", f"cd:compensation:{order_id}"), ("🚚 Довоз", f"cd:redelivery:{order_id}")],
                 [("✖️ Отклонить претензию", f"cd:rejected:{order_id}")])


def manager_order(o: Order, has_claim: bool = False) -> InlineKeyboardMarkup | None:
    if o.status == "new":
        return review(o.id)
    if o.status == "confirmed":
        return pay_control(o.id)
    if o.status in ("paid", "picking"):
        return warehouse(o)
    if o.status in ("ready", "in_transit", "delayed"):
        return shipping(o)
    if o.status == "claim":
        return claim_decision(o.id)
    docs = doc_buttons(o, has_claim)
    return _rows(docs) if docs else None


def reply(client_id: int) -> InlineKeyboardMarkup:
    return _inline([("↩️ Ответить клиенту", f"rpl:{client_id}")], 1)


def summary() -> InlineKeyboardMarkup:
    return _inline([("📤 Выгрузить заказы (CSV)", "sum:csv")], 1)


def kpi(dashboard_url: str) -> InlineKeyboardMarkup:
    kb = _inline([("Месяц", "kpi:M"), ("Квартал", "kpi:Q"), ("Год", "kpi:Y")], 3)
    if dashboard_url.startswith("https://"):
        kb.inline_keyboard.append([InlineKeyboardButton(text="🖥 Открыть дашборд", url=dashboard_url)])
    return kb
