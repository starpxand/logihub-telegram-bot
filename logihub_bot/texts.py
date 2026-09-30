"""Тексты сообщений."""
from __future__ import annotations

from html import escape

from .pricing import Quote
from .storage import STATUSES, Order

WELCOME = (
    "👋 Здравствуйте, {name}!\n\n"
    "Я бот платформы <b>ЛогиХаб</b> – каждая поставка под контролем, в одном окне.\n\n"
    "Здесь можно оформить заявку на перевозку с расчётом стоимости и срока, следить за статусом заказа, "
    "получать уведомления о задержках и принять груз – подписать акт или оформить претензию.\n\n"
    "Менеджеры работают в отдельном боте: @{manager_bot}"
)

HELP_CLIENT = (
    "<b>Команды</b>\n"
    "/start – главное меню\n/new – новая заявка\n/status &lt;номер&gt; – статус заказа\n/cancel – отменить ввод\n\n"
    "Бот для менеджеров: @{manager_bot}"
)

WELCOME_MANAGER = (
    "👔 {name}, добро пожаловать в рабочее место менеджера <b>ЛогиХаб</b>.\n\n"
    "Сюда приходят новые заявки клиентов и претензии. В меню – проверка заявок, заказы в работе "
    "(отгрузка, задержка, доставка), поиск заказа и KPI из аналитического дашборда."
)

HELP_MANAGER = (
    "<b>Команды менеджера</b>\n"
    "/start – меню\n/status &lt;номер&gt; – карточка и история заказа\n/kpi – KPI доставки с графиком\n"
    "/logout – выйти из рабочего места\n/cancel – отменить ввод"
)


def num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def rub(value: float) -> str:
    return f"{num(value)} ₽"


def quote_card(q: Quote) -> str:
    return (f"🧾 <b>Предварительный расчёт</b>\n\n"
            f"Маршрут: Комсомольск-на-Амуре → {escape(q.destination)} ({q.distance_km} км)\n"
            f"Груз: {escape(q.cargo)}, {num(q.weight_kg)} кг\n"
            f"Транспорт: {q.transport}\n"
            f"Отгрузка: {q.ship_date:%d.%m.%Y}, доставка: <b>{q.eta:%d.%m.%Y}</b>\n"
            f"Стоимость: <b>{rub(q.price)}</b>")


def order_card(o: Order, history=None) -> str:
    text = (f"📦 <b>Заказ {o.number}</b>\n"
            f"Статус: <b>{STATUSES[o.status]}</b>\n"
            f"Маршрут: → {escape(o.destination)}, {o.distance_km} км\n"
            f"Груз: {escape(o.cargo)}, {num(o.weight_kg)} кг, {o.transport}\n"
            f"Доставка: {o.eta:%d.%m.%Y} · {rub(o.price)}")
    if o.comment:
        text += f"\n💬 {escape(o.comment)}"
    if history:
        text += "\n\n<b>История</b>\n" + "\n".join(
            f"• {h['created_at'][8:10]}.{h['created_at'][5:7]} {h['created_at'][11:16]} {STATUSES[h['status']]}"
            + (f" – {escape(h['note'])}" if h["note"] else "")
            for h in history)
    return text
