"""Тексты сообщений ботов."""
from __future__ import annotations

import re
from html import escape

from .config import COMPANY, PAYMENT_DAYS
from .pricing import (BASE_FEE, CARGO, DESTINATIONS, HUB, INSURANCE_MIN, INSURANCE_RATE, KG_RATE, TEMPERATURE,
                      TRANSPORT, Quote)
from .storage import CLAIM_DECISIONS, STATUSES, Claim, Driver, Order, User

ICONS = {
    "new": "🕓", "clarify": "✏️", "confirmed": "💳", "paid": "💰", "picking": "🏭", "ready": "📑",
    "in_transit": "🚚", "delayed": "⏰", "delivered": "📍", "accepted": "✍️", "claim": "⚠️",
    "closed": "🏁", "cancelled": "✖️",
}

WELCOME = (
    "👋 Здравствуйте, {name}!\n\n"
    "Это бот транспортно-логистической компании <b>ЛогиХаб</b>. Везём грузы со склада в Комсомольске-на-Амуре "
    "по Дальнему Востоку: Хабаровск, Биробиджан, Владивосток, Благовещенск, Южно-Сахалинск.\n\n"
    "Здесь можно:\n"
    "📦 оформить заявку и сразу увидеть стоимость и срок;\n"
    "💳 получить договор-счёт и сообщить об оплате;\n"
    "🔎 следить за заказом – от склада до получателя;\n"
    "✅ принять груз или оформить претензию;\n"
    "💬 написать менеджеру.\n\n"
    "Заявки принимаем круглосуточно, менеджеры отвечают пн–пт 9:00–18:00 (хабаровское время)."
)

HELP_CLIENT = (
    "<b>Как это работает</b>\n"
    "1. Оформляете заявку – бот считает стоимость и срок.\n"
    "2. Менеджер проверяет заявку и присылает договор-счёт.\n"
    f"3. Оплачиваете счёт в течение {PAYMENT_DAYS} дней и нажимаете «💳 Я оплатил».\n"
    "4. Склад комплектует груз и оформляет ТТН, диспетчер назначает водителя.\n"
    "5. Бот сообщает о выезде, задержках и доставке.\n"
    "6. Принимаете груз: подписываете акт или оформляете претензию.\n\n"
    "<b>Команды</b>\n"
    "/start – главное меню\n/new – новая заявка\n/orders – мои заказы\n"
    "/status LH-20001 – статус заказа\n/tariffs – тарифы и сроки\n/support – написать менеджеру\n"
    "/cancel – прервать ввод"
)

WELCOME_MANAGER = (
    "👔 {name}, добро пожаловать в рабочее место <b>ЛогиХаб</b>.\n\n"
    "Сюда приходят заявки, сообщения об оплате, претензии и вопросы клиентов. Разделы меню повторяют "
    "процесс: заявки → оплаты → склад → рейсы → претензии."
)

HELP_MANAGER = (
    "<b>Разделы</b>\n"
    "📋 Новые заявки – проверка: подтвердить и выставить счёт, вернуть на уточнение, отклонить\n"
    f"💳 Оплаты – счета, ожидающие оплаты (срок {PAYMENT_DAYS} дня, потом автоотмена)\n"
    "🏭 Склад – комплектация, контроль In Full, ТТН\n"
    "🚚 Рейсы – водитель, выезд, отклонение от графика, доставка\n"
    "⚠️ Претензии – решение: компенсация, довоз или отказ\n"
    "📈 Сводка – заказы, OTIF, оценки, выгрузка CSV\n"
    "📊 KPI дашборда – аналитика по выгрузке заказов\n\n"
    "<b>Команды</b>\n"
    "/start – меню\n/status LH-20001 – карточка заказа\n/kpi – KPI доставки\n"
    "/logout – выйти\n/cancel – прервать ввод"
)


def _comma(text: str) -> str:
    return text.replace(".", ",")


ABOUT = (
    f"ℹ️ <b>{COMPANY['name']}</b>\n<i>{COMPANY['slogan']}</i>\n\n"
    f"🏭 Склад и хаб: {HUB}\n"
    f"🕘 {COMPANY['hours'][0].upper()}{COMPANY['hours'][1:]}\n"
    "🚚 Парк: газели, фуры, рефрижераторы, контейнерные перевозки по ж/д\n"
    "🌡 Продукты и медикаменты – только в рефрижераторах с контролем температуры\n"
    f"🛡 Страхование груза – {_comma(f'{INSURANCE_RATE * 100:.1f}')} % объявленной стоимости\n"
    f"📖 Как мы работаем: {COMPANY['wiki']}\n\n"
    "<i>Реквизиты в документах условные – учебный проект КнАГУ.</i>"
)


def phone(raw: str) -> str:
    """+7 914 123-45-67 для российских номеров, иначе как ввёл пользователь."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:]}"
    return raw.strip()


def num(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def rub(value: float) -> str:
    return f"{num(value)} ₽"


def transit_days(distance: int) -> tuple[int, int]:
    days = [max(1, round(distance / (speed * 10)) + 1) for _, speed, _ in TRANSPORT.values()]
    return min(days), max(days)


def tariffs() -> str:
    lines = ["💰 <b>Тарифы и сроки</b>\n", "<b>Направления</b> (отправка со склада в Комсомольске-на-Амуре):"]
    for city, (_, km) in DESTINATIONS.items():
        lo, hi = transit_days(km)
        lines.append(f"• {city} – {km} км, в пути {lo}–{hi} дн." if lo != hi else f"• {city} – {km} км, {lo} дн.")
    lines.append("\n<b>Транспорт</b> (подбирается автоматически):")
    for name, (capacity, _, rate) in TRANSPORT.items():
        lines.append(f"• {name} – до {_comma(f'{capacity / 1000:g}')} т, {rate} ₽/км")
    lines.append("\n<b>Коэффициент груза:</b> " + ", ".join(f"{c.lower()} ×{_comma(f'{k:g}')}" for c, k in CARGO.items()))
    lines.append(f"\n<b>Стоимость</b> = км × ставка транспорта × коэффициент груза + {_comma(f'{KG_RATE:g}')} ₽/кг "
                 f"+ {rub(BASE_FEE)} (погрузка, документы)")
    lines.append(f"<b>Страховка</b> – {_comma(f'{INSURANCE_RATE * 100:.1f}')} % объявленной стоимости, "
                 f"не менее {rub(INSURANCE_MIN)}")
    lines.append("🌡 Рефрижератор: " + ", ".join(f"{c.lower()} {t}" for c, t in TEMPERATURE.items()))
    lines.append(f"\nОплата – в течение {PAYMENT_DAYS} дней после выставления счёта. Склад отгружает пн–сб.")
    return "\n".join(lines)


def quote_card(q: Quote, places: int, address: str, recipient: str, comment: str | None) -> str:
    carriage = q.price - q.weight_fee - q.base_fee
    text = (f"🧾 <b>Расчёт стоимости</b>\n\n"
            f"Маршрут: {HUB} → {escape(q.destination)}, {q.distance_km} км\n"
            f"Адрес: {escape(address)}\n"
            f"Получатель: {escape(recipient)}\n"
            f"Груз: {escape(q.cargo)}, {num(q.weight_kg)} кг, мест: {places}\n")
    if q.temperature:
        text += f"🌡 Температурный режим {q.temperature}\n"
    text += (f"Транспорт: {q.transport}\n\n"
             f"Перевозка по тарифу: {rub(carriage)}\n"
             f"За вес ({_comma(f'{KG_RATE:g}')} ₽/кг): {rub(q.weight_fee)}\n"
             f"Погрузка и оформление: {rub(q.base_fee)}\n")
    if q.insurance:
        text += f"Страховка ({rub(q.declared_value)} × 0,3 %): {rub(q.insurance)}\n"
    text += (f"<b>Итого: {rub(q.total)}</b>\n\n"
             f"Отгрузка: {q.ship_date:%d.%m.%Y} · доставка: <b>{q.eta:%d.%m.%Y}</b>")
    if comment:
        text += f"\n💬 {escape(comment)}"
    return text


def order_card(o: Order, history=None, client: User | None = None, driver: Driver | None = None,
               claim: Claim | None = None) -> str:
    lines = [f"📦 <b>Заказ {o.number}</b>", f"{ICONS[o.status]} <b>{o.status_text}</b>"]
    if client:
        lines.append(f"👤 {escape(client.company or client.name)} · {escape(client.phone or 'телефон не указан')}")
    lines.append(f"Маршрут: → {escape(o.destination)}, {o.distance_km} км")
    if o.address:
        lines.append(f"Адрес: {escape(o.address)}")
    if o.recipient:
        lines.append(f"Получатель: {escape(o.recipient)}")
    cargo = f"Груз: {escape(o.cargo)}, {num(o.weight_kg)} кг, мест: {o.places}"
    lines.append(cargo + (f", t° {o.temperature}" if o.temperature else ""))
    lines.append(f"Транспорт: {o.transport}" + (f" – {escape(driver.name)}, {escape(driver.vehicle)}, "
                                                f"{driver.plate}" if driver else ""))
    eta = f"Отгрузка: {o.ship_date:%d.%m.%Y} · доставка: <b>{o.eta:%d.%m.%Y}</b>"
    if o.planned_eta and o.planned_eta != o.eta:
        eta += f" (план {o.planned_eta:%d.%m})"
    lines.append(eta)
    lines.append(f"Стоимость: <b>{rub(o.total)}</b>" + (f", вкл. страховку {rub(o.insurance)}" if o.insurance else ""))
    if o.status == "confirmed" and o.pay_deadline:
        lines.append(f"⏳ Оплатить до {o.pay_deadline:%d.%m.%Y %H:%M}")
    if o.comment:
        lines.append(f"💬 {escape(o.comment)}")
    if claim:
        lines.append(f"⚠️ Претензия: {claim.kind_text} – {escape(claim.text)}"
                     + (f" (фото: {len(claim.photos)})" if claim.photos else ""))
        if claim.decision:
            lines.append(f"Решение: {CLAIM_DECISIONS[claim.decision]}"
                         + (f", {rub(claim.compensation)}" if claim.compensation else "")
                         + (f" – {escape(claim.answer)}" if claim.answer else ""))
    if o.rating:
        lines.append("Оценка: " + "⭐" * o.rating)
    text = "\n".join(lines)
    if history:
        text += "\n\n<b>История</b>\n" + "\n".join(
            f"{h['created_at'][8:10]}.{h['created_at'][5:7]} {h['created_at'][11:16]} · "
            + (escape(h["note"]) if h["note"] else STATUSES[h["status"]])
            for h in history)
    return text


def order_line(o: Order) -> str:
    return f"{ICONS[o.status]} {o.number} · {o.destination} · {o.status_text}"


def summary(stats: dict) -> str:
    lines = ["📈 <b>Сводка по заказам</b>\n", f"Всего заказов: <b>{stats['total']}</b>"]
    for status, title in STATUSES.items():
        if stats["by_status"].get(status):
            lines.append(f"{ICONS[status]} {title}: {stats['by_status'][status]}")
    lines.append("")
    if stats["closed"]:
        lines.append(f"Выполнено: <b>{stats['closed']}</b> · вовремя {stats['on_time']:.0f} % · "
                     f"OTIF <b>{stats['otif']:.0f} %</b>")
    else:
        lines.append("Выполненных заказов пока нет – OTIF появится после закрытия первого заказа.")
    if stats["ratings"]:
        rating = _comma(f"{stats['rating']:.1f}")
        lines.append(f"Оценка клиентов: <b>{rating}</b> из 5 (оценок: {stats['ratings']})")
    lines.append(f"Оплачено заказов на сумму: <b>{rub(stats['revenue'])}</b>")
    if stats["open_claims"]:
        lines.append(f"⚠️ Открытых претензий: {stats['open_claims']}")
    return "\n".join(lines)


def payment_reminder(order: Order) -> str:
    return (f"🔔 Напоминаем: договор-счёт по заказу <b>{order.number}</b> на <b>{rub(order.total)}</b> "
            f"нужно оплатить до <b>{order.pay_deadline:%d.%m.%Y %H:%M}</b>. Если оплата не поступит в течение "
            f"{PAYMENT_DAYS} дней с выставления счёта, заказ отменится автоматически.\n\n"
            "Уже оплатили – нажмите «💳 Я оплатил».")
