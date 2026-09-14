"""Тексты сообщений."""
from __future__ import annotations

from html import escape

from .pricing import Quote
from .storage import STATUSES, Order

WELCOME = (
    "👋 Здравствуйте, {name}!\n\n"
    "Я бот платформы <b>ЛогиХаб</b> – каждая поставка под контролем, в одном окне.\n\n"
    "Клиентам: оформление заявки на перевозку с расчётом стоимости, статус и трекинг заказа, "
    "уведомления о задержках, приёмка груза.\n"
    "Менеджерам: проверка заявок, управление заказами, KPI из аналитического дашборда.\n\n"
    "Вы вошли как <b>клиент</b>. Менеджер может переключиться командой /manager &lt;код&gt;."
)

HELP = (
    "<b>Команды</b>\n"
    "/start – главное меню\n/new – новая заявка\n/status &lt;номер&gt; – статус заказа\n"
    "/manager &lt;код&gt; – режим менеджера\n/client – режим клиента\n/kpi – KPI доставки\n/cancel – отменить ввод"
)


def rub(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def quote_card(q: Quote) -> str:
    return (f"🧾 <b>Предварительный расчёт</b>\n\n"
            f"Маршрут: Комсомольск-на-Амуре → {escape(q.destination)} ({q.distance_km} км)\n"
            f"Груз: {escape(q.cargo)}, {q.weight_kg:,.0f} кг\n".replace(",", " ") +
            f"Транспорт: {q.transport}\n"
            f"Отгрузка: {q.ship_date:%d.%m.%Y}, доставка: <b>{q.eta:%d.%m.%Y}</b>\n"
            f"Стоимость: <b>{rub(q.price)}</b>")


def order_card(o: Order, history=None) -> str:
    text = (f"📦 <b>Заказ {o.number}</b>\n"
            f"Статус: <b>{STATUSES[o.status]}</b>\n"
            f"Маршрут: → {escape(o.destination)}, {o.distance_km} км\n"
            f"Груз: {escape(o.cargo)}, {o.weight_kg:,.0f} кг, {o.transport}\n".replace(",", " ") +
            f"Доставка: {o.eta:%d.%m.%Y} · {rub(o.price)}")
    if o.comment:
        text += f"\n💬 {escape(o.comment)}"
    if history:
        text += "\n\n<b>История</b>\n" + "\n".join(
            f"• {h['created_at'][11:16]} {STATUSES[h['status']]}" + (f" – {escape(h['note'])}" if h["note"] else "")
            for h in history)
    return text
