"""Бот менеджера – рабочее место сотрудников ЛогиХаб.

Роли менеджера, склада и диспетчера из BPMN-модели объединены в одном боте:
3–5 проверка заявки, 7 договор-счёт, 9 контроль оплаты, 10–13 комплектация и ТТН, 14–15 водитель и рейс,
17–19 отклонение от графика и доставка, 23 решение по претензии, 25 сводка и KPI.
Уведомления клиентам уходят через клиентский бот.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove

from . import documents
from . import keyboards as kb
from . import texts
from .analytics import Analytics
from .config import PAYMENT_DAYS, Settings, now
from .notify import edit_or_send, notify, send_file
from .storage import CLAIM_DECISIONS, Order, Storage, TransitionError, parse_number

log = logging.getLogger(__name__)

CSV_COLUMNS = {
    "order": "Заказ", "created": "Создан", "client": "Клиент", "phone": "Телефон", "destination": "Город",
    "region": "Регион", "address": "Адрес", "cargo": "Груз", "weight_kg": "Вес, кг", "places": "Мест",
    "transport": "Транспорт", "driver": "Водитель", "price": "Перевозка, ₽", "insurance": "Страховка, ₽",
    "total": "Итого, ₽", "ship_date": "Отгрузка", "planned_eta": "Доставка по плану", "eta": "Доставка (прогноз)",
    "delivered": "Доставлен", "status": "Статус", "on_time": "On Time", "in_full": "In Full", "rating": "Оценка",
}


class Login(StatesGroup):
    code = State()


class Track(StatesGroup):
    number = State()


class Reason(StatesGroup):
    text = State()


class Decision(StatesGroup):
    amount = State()
    answer = State()


class Reply(StatesGroup):
    text = State()


def export_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(CSV_COLUMNS.values())
    for row in rows:
        writer.writerow([str(row[k]).replace(".", ",") if isinstance(row[k], float) else row[k] for k in CSV_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")  # BOM – чтобы Excel открыл кириллицу


def build_manager_router(storage: Storage, analytics: Analytics, settings: Settings, client_bot: Bot) -> Router:
    r = Router(name="manager")

    def is_manager(user_id: int) -> bool:
        return storage.role(user_id) == "manager"

    def card(o: Order, history: bool = False) -> str:
        return texts.order_card(o, storage.history(o.id) if history else None, client=storage.user(o.client_id),
                                driver=storage.driver(o.driver_id), claim=storage.order_claim(o.id))

    def actions(o: Order):
        return kb.manager_order(o, storage.order_claim(o.id) is not None)

    def backlog() -> str:
        sections = [("new", "заявок на проверку"), ("confirmed", "ожидают оплаты"),
                    (("paid", "picking"), "на складе"), (("ready", "in_transit", "delayed"), "в отгрузке и в пути"),
                    ("claim", "претензий")]
        counts = [(title, len(storage.list(status=s))) for s, title in sections]
        parts = [f"{title} – <b>{n}</b>" for title, n in counts if n]
        return "📋 Сейчас в работе: " + ", ".join(parts) if parts else "✨ Открытых задач нет."

    async def change(c: CallbackQuery, order_id: int, status: str, note: str, **kw) -> Order | None:
        try:
            order = storage.set_status(order_id, status, note, **kw)
        except TransitionError as exc:
            await c.answer(str(exc), show_alert=True)
            return None
        await c.answer("Готово")
        return order

    async def show(m: Message, orders: list[Order], empty: str):
        if not orders:
            await m.answer(empty, reply_markup=kb.manager_menu())
        for o in orders:
            await m.answer(card(o), reply_markup=actions(o))

    # ---------- вход ----------
    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear()
        if is_manager(m.from_user.id):
            await m.answer(texts.WELCOME_MANAGER.format(name=escape(m.from_user.first_name or "")),
                           reply_markup=kb.manager_menu())
            await m.answer(backlog())
            return
        await state.set_state(Login.code)
        await m.answer("🔐 <b>ЛогиХаб – рабочее место сотрудника</b>\n\nВведите код доступа:",
                       reply_markup=ReplyKeyboardRemove())

    @r.message(Command("cancel"))
    async def cancel(m: Message, state: FSMContext):
        await state.clear()
        await m.answer("Действие отменено.",
                       reply_markup=kb.manager_menu() if is_manager(m.from_user.id) else ReplyKeyboardRemove())

    @r.message(Login.code)
    async def login(m: Message, state: FSMContext):
        if (m.text or "").strip() != settings.manager_code:
            await m.answer("⛔ Неверный код. Попробуйте ещё раз или /cancel.")
            return
        await state.clear()
        storage.upsert_user(m.from_user.id, m.from_user.full_name, "manager")
        await m.answer(texts.WELCOME_MANAGER.format(name=escape(m.from_user.first_name or "")),
                       reply_markup=kb.manager_menu())
        await m.answer(backlog())

    @r.message(Command("logout"))
    async def logout(m: Message, state: FSMContext):
        await state.clear()
        storage.upsert_user(m.from_user.id, m.from_user.full_name, "client")
        await m.answer("Вы вышли из рабочего места. Войти снова – /start.", reply_markup=ReplyKeyboardRemove())

    # дальше – только для сотрудников
    @r.message(lambda m: not is_manager(m.from_user.id))
    async def not_logged(m: Message):
        await m.answer("🔐 Войдите: /start и код доступа сотрудника.", reply_markup=ReplyKeyboardRemove())

    @r.callback_query(lambda c: not is_manager(c.from_user.id))
    async def not_logged_button(c: CallbackQuery):
        await c.answer("Сначала войдите: /start и код доступа сотрудника.", show_alert=True)

    # ---------- разделы меню ----------
    @r.message(Command("help"))
    @r.message(F.text == kb.HELP)
    async def help_(m: Message, state: FSMContext):
        await state.clear()
        await m.answer(texts.HELP_MANAGER, reply_markup=kb.manager_menu())

    @r.message(F.text == kb.QUEUE)
    async def queue(m: Message, state: FSMContext):
        await state.clear()
        await show(m, storage.list(status="new"), "✨ Новых заявок нет.")

    @r.message(F.text == kb.PAYMENTS)
    async def payments(m: Message, state: FSMContext):
        await state.clear()
        await show(m, storage.list(status="confirmed"), "Счетов, ожидающих оплаты, нет.")

    @r.message(F.text == kb.WAREHOUSE)
    async def warehouse(m: Message, state: FSMContext):
        await state.clear()
        await show(m, storage.list(status=("paid", "picking")), "На складе нет заказов в работе.")

    @r.message(F.text == kb.SHIPPING)
    async def shipping(m: Message, state: FSMContext):
        await state.clear()
        await show(m, storage.list(status=("ready", "in_transit", "delayed")), "Нет заказов в отгрузке и в пути.")

    @r.message(F.text == kb.CLAIMS)
    async def claims(m: Message, state: FSMContext):
        await state.clear()
        await show(m, storage.list(status="claim"), "Открытых претензий нет 👍")

    @r.message(Command("status"))
    async def status_cmd(m: Message, command: CommandObject, state: FSMContext):
        await state.clear()
        if command.args:
            await show_status(m, command.args)
        else:
            await state.set_state(Track.number)
            await m.answer("Введите номер заказа, например LH-20001:")

    @r.message(F.text == kb.FIND)
    async def find(m: Message, state: FSMContext):
        await state.set_state(Track.number)
        await m.answer("Введите номер заказа, например LH-20001:")

    @r.message(F.text == kb.SUMMARY)
    async def summary(m: Message, state: FSMContext):
        await state.clear()
        await m.answer(texts.summary(storage.stats()), reply_markup=kb.summary())

    @r.message(Command("kpi"))
    @r.message(F.text == kb.KPI)
    async def kpi(m: Message, state: FSMContext):
        await state.clear()
        await send_kpi(m, "M")

    @r.message(Track.number)
    async def track_number(m: Message, state: FSMContext):
        await state.clear()
        await show_status(m, m.text or "")

    async def show_status(m: Message, raw: str):
        order_id = parse_number(raw)
        order = storage.get(order_id) if order_id else None
        if order is None:
            await m.answer("Заказ не найден. Проверьте номер.", reply_markup=kb.manager_menu())
            return
        await m.answer(card(order, history=True), reply_markup=actions(order))

    # ---------- проверка заявки (этапы 3–5, 7) ----------
    @r.callback_query(F.data.startswith("rev:ok:"))
    async def review_ok(c: CallbackQuery):
        order = await change(c, int(c.data.split(":")[2]), "confirmed",
                             "Заявка проверена менеджером, договор-счёт выставлен")
        if not order:
            return
        await edit_or_send(c.message, card(order) + "\n\n✅ Подтверждена, договор-счёт отправлен клиенту.",
                           actions(order))
        pdf, name = await asyncio.to_thread(documents.render, storage, "inv", order)
        await send_file(client_bot, [order.client_id], pdf, name,
                        f"✅ Заявка <b>{order.number}</b> проверена.\n\nДоговор-счёт на <b>{texts.rub(order.total)}</b> "
                        f"во вложении. Оплатите до <b>{order.pay_deadline:%d.%m.%Y %H:%M}</b> и нажмите «💳 Я оплатил». "
                        f"Если оплата не поступит в течение {PAYMENT_DAYS} дней, заказ отменится автоматически.",
                        kb.payment(order))

    @r.callback_query(F.data.startswith(("rev:back:", "rev:decline:")))
    async def review_reason(c: CallbackQuery, state: FSMContext):
        _, action, oid = c.data.split(":")
        order = storage.get(int(oid))
        if order is None or order.status != "new":
            await c.answer("Заявка уже обработана.", show_alert=True)
            return
        await state.set_state(Reason.text)
        await state.update_data(order_id=order.id, action=action)
        await c.answer()
        prompt = ("Что клиенту нужно уточнить? Одним сообщением – его увидит клиент "
                  "(например: «Укажите телефон ответственного на складе получателя»)." if action == "back" else
                  "Причина отказа – её увидит клиент (например: «Нет свободного рефрижератора на эту дату»).")
        await c.message.answer(f"Заявка {order.number}. {prompt}\nОтмена – /cancel.")

    @r.message(Reason.text, F.text)
    async def review_reason_text(m: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        reason = m.text.strip()[:500]
        try:
            if data["action"] == "back":
                order = storage.set_status(data["order_id"], "clarify", f"Возвращена на уточнение: {reason}")
            else:
                order = storage.set_status(data["order_id"], "cancelled", f"Отклонена менеджером: {reason}")
        except TransitionError as exc:
            await m.answer(f"⚠️ {exc}", reply_markup=kb.manager_menu())
            return
        if order.status == "clarify":
            await notify(client_bot, [order.client_id],
                         f"↩️ Заявка <b>{order.number}</b> возвращена на уточнение.\n\nКомментарий менеджера: "
                         f"<i>{escape(reason)}</i>\n\nИсправьте данные и отправьте заявку повторно.",
                         kb.fix_menu(order.id))
            done = "↩️ Заявка возвращена клиенту на уточнение."
        else:
            await notify(client_bot, [order.client_id],
                         f"✖️ Заявка <b>{order.number}</b> отклонена.\nПричина: <i>{escape(reason)}</i>\n\n"
                         "Вопросы – «💬 Написать менеджеру».")
            done = "✖️ Заявка отклонена, клиент уведомлён."
        await m.answer(card(order) + f"\n\n{done}", reply_markup=kb.manager_menu())

    # ---------- оплата (этапы 8–9) ----------
    @r.callback_query(F.data.startswith("pay:ok:"))
    async def pay_ok(c: CallbackQuery):
        order = await change(c, int(c.data.split(":")[2]), "paid", "Оплата поступила, заказ передан на склад")
        if not order:
            return
        await edit_or_send(c.message, card(order) + "\n\n💰 Оплата подтверждена, заказ передан на склад.", actions(order))
        await notify(client_bot, [order.client_id],
                     f"💰 Оплата по заказу <b>{order.number}</b> получена, спасибо!\n"
                     "Заказ передан на склад – сообщим, когда груз будет скомплектован.")

    @r.callback_query(F.data.startswith("pay:remind:"))
    async def pay_remind(c: CallbackQuery):
        order = storage.get(int(c.data.split(":")[2]))
        if order is None or order.status != "confirmed":
            await c.answer("Счёт уже не ожидает оплаты.", show_alert=True)
            return
        storage.log(order.id, "Менеджер напомнил клиенту об оплате")
        await notify(client_bot, [order.client_id], texts.payment_reminder(order), kb.payment(order))
        await c.answer("Напоминание отправлено клиенту", show_alert=True)

    # ---------- склад (этапы 10–13) ----------
    @r.callback_query(F.data.startswith("wh:"))
    async def warehouse_step(c: CallbackQuery):
        _, action, oid = c.data.split(":")
        order_id = int(oid)
        if action == "start":
            order = await change(c, order_id, "picking", "Склад начал комплектацию и маркировку груза")
            if order:
                await notify(client_bot, [order.client_id],
                             f"🏭 Склад начал комплектацию заказа <b>{order.number}</b> (мест: {order.places}).")
        elif action == "short":
            order = await change(c, order_id, "picking", "Сверка по маркировке: не хватает мест, груз докомплектовывается")
        else:
            order = await change(c, order_id, "ready", "Груз укомплектован полностью, ТТН оформлена")
            if order:
                pdf, name = await asyncio.to_thread(documents.render, storage, "ttn", order)
                await c.message.answer_document(BufferedInputFile(pdf, name),
                                                caption=f"📑 ТТН по заказу {order.number}. Назначьте водителя.")
                await notify(client_bot, [order.client_id],
                             f"📑 Груз по заказу <b>{order.number}</b> скомплектован (мест: {order.places}), "
                             f"ТТН оформлена. Отгрузка – {order.ship_date:%d.%m.%Y}.")
        if order:
            await edit_or_send(c.message, card(order, history=action == "short"), actions(order))

    # ---------- водитель и рейс (этапы 14–19) ----------
    @r.callback_query(F.data.startswith("sh:driver:"))
    async def choose_driver(c: CallbackQuery):
        order = storage.get(int(c.data.split(":")[2]))
        if order is None or order.status != "ready":
            await c.answer("Водителя назначают для скомплектованного груза.", show_alert=True)
            return
        await c.answer()
        await edit_or_send(c.message, card(order) + f"\n\n👤 Водители с транспортом «{order.transport}»:",
                           kb.drivers(order.id, storage.drivers(order.transport)))

    @r.callback_query(F.data.startswith("drv:"))
    async def set_driver(c: CallbackQuery):
        _, oid, did = c.data.split(":")
        try:
            order = storage.assign_driver(int(oid), int(did))
        except TransitionError as exc:
            await c.answer(str(exc), show_alert=True)
            return
        await c.answer("Водитель назначен")
        await edit_or_send(c.message, card(order), actions(order))

    @r.callback_query(F.data.startswith("sh:go:"))
    async def trip_start(c: CallbackQuery):
        order = storage.get(int(c.data.split(":")[2]))
        driver = storage.driver(order.driver_id) if order else None
        note = f"Водитель {driver.name} принял груз по ТТН, рейс начат" if driver else "Рейс начат"
        order = await change(c, int(c.data.split(":")[2]), "in_transit", note)
        if not order:
            return
        await edit_or_send(c.message, card(order), actions(order))
        pdf, name = await asyncio.to_thread(documents.render, storage, "ttn", order)
        await send_file(client_bot, [order.client_id], pdf, name,
                        f"🚚 Заказ <b>{order.number}</b> в пути!\n\nВодитель: {escape(driver.name)}\n"
                        f"Транспорт: {escape(driver.vehicle)}, {driver.plate}\n"
                        f"Ожидаемая доставка: <b>{order.eta:%d.%m.%Y}</b>\n\nТТН во вложении. О задержках сообщим сразу.")

    @r.callback_query(F.data.startswith("sh:delay:"))
    async def delay_ask(c: CallbackQuery):
        order = storage.get(int(c.data.split(":")[2]))
        if order is None or order.status not in ("in_transit", "delayed"):
            await c.answer("Заказ не в пути.", show_alert=True)
            return
        await c.answer()
        await edit_or_send(c.message, card(order) + "\n\n⏰ Причина отклонения от графика:", kb.delay_reasons(order.id))

    @r.callback_query(F.data.startswith("dr:"))
    async def delay_reason(c: CallbackQuery):
        _, oid, reason = c.data.split(":")
        order = storage.get(int(oid))
        if order is None or order.status not in ("in_transit", "delayed"):
            await c.answer("Заказ не в пути.", show_alert=True)
            return
        await c.answer()
        await edit_or_send(c.message, card(order) + f"\n\n⏰ Причина: {kb.DELAY_REASONS[reason]}.\n"
                                                    "На сколько сдвигается доставка?", kb.delay_days(order.id, reason))

    @r.callback_query(F.data.startswith("dd:"))
    async def delay_set(c: CallbackQuery):
        _, oid, reason, days = c.data.split(":")
        order = storage.get(int(oid))
        if order is None:
            await c.answer("Заказ не найден.", show_alert=True)
            return
        new_eta = order.eta + timedelta(days=int(days))
        order = await change(c, order.id, "delayed", f"Отклонение от графика: {kb.DELAY_REASONS[reason]}. "
                                                     f"Маршрут перепланирован, доставка {new_eta:%d.%m.%Y}", eta=new_eta)
        if not order:
            return
        await edit_or_send(c.message, card(order), actions(order))
        await notify(client_bot, [order.client_id],
                     f"⏰ По заказу <b>{order.number}</b> отклонение от графика: {kb.DELAY_REASONS[reason]}.\n"
                     f"Маршрут перепланирован, новая дата доставки: <b>{order.eta:%d.%m.%Y}</b>.\n"
                     "Приносим извинения за задержку.")

    @r.callback_query(F.data.startswith("sh:done:"))
    async def delivered(c: CallbackQuery):
        order = await change(c, int(c.data.split(":")[2]), "delivered", "Груз доставлен и выгружен у получателя")
        if not order:
            return
        await edit_or_send(c.message, card(order) + "\n\n📍 Доставлен, ждём приёмку от клиента.", actions(order))
        checks = "количество мест, целостность упаковки" + (" и температурный режим" if order.temperature else "")
        await notify(client_bot, [order.client_id],
                     f"📍 Заказ <b>{order.number}</b> доставлен: {escape(order.destination)}, "
                     f"{escape(order.address or '')}.\n\nПроверьте {checks} и подтвердите приёмку:",
                     kb.acceptance(order.id))

    # ---------- претензии (этап 23) ----------
    @r.callback_query(F.data.startswith("cd:"))
    async def claim_decision(c: CallbackQuery, state: FSMContext):
        _, decision, oid = c.data.split(":")
        order = storage.get(int(oid))
        claim = storage.order_claim(int(oid))
        if order is None or order.status != "claim" or claim is None:
            await c.answer("Претензия уже рассмотрена.", show_alert=True)
            return
        await state.set_state(Decision.amount if decision == "compensation" else Decision.answer)
        await state.update_data(order_id=order.id, claim_id=claim.id, decision=decision)
        await c.answer()
        if decision == "compensation":
            await c.message.answer(f"Претензия № {claim.id}. Сумма компенсации, ₽ (стоимость заказа – "
                                   f"{texts.rub(order.total)}, объявленная стоимость груза – "
                                   f"{texts.rub(order.declared_value)}):")
        else:
            await c.message.answer(f"Претензия № {claim.id} – «{CLAIM_DECISIONS[decision]}». "
                                   "Ответ клиенту с обоснованием решения:")

    @r.message(Decision.amount, F.text)
    async def claim_amount(m: Message, state: FSMContext):
        try:
            amount = float(m.text.replace(" ", "").replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await m.answer("Введите сумму числом, например 12500.")
            return
        await state.update_data(amount=amount)
        await state.set_state(Decision.answer)
        await m.answer("Ответ клиенту с обоснованием решения:")

    @r.message(Decision.answer, F.text)
    async def claim_answer(m: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        order = storage.get(data["order_id"])
        if order is None or order.status != "claim":
            await m.answer("Претензия уже рассмотрена.", reply_markup=kb.manager_menu())
            return
        claim = storage.decide_claim(data["claim_id"], data["decision"], m.text.strip()[:1000], data.get("amount"))
        order = storage.set_status(order.id, "closed", f"Претензия рассмотрена: {CLAIM_DECISIONS[claim.decision].lower()}. "
                                                       "Заказ закрыт, OTIF пересчитан")
        amount = f" – <b>{texts.rub(claim.compensation)}</b>" if claim.compensation else ""
        await notify(client_bot, [order.client_id],
                     f"📨 Решение по претензии № {claim.id} к заказу <b>{order.number}</b>: "
                     f"<b>{CLAIM_DECISIONS[claim.decision]}</b>{amount}.\n\n{escape(claim.answer)}\n\n"
                     "Заказ закрыт. Оцените, пожалуйста, работу с заказом:", kb.rating(order.id))
        await m.answer(card(order) + "\n\n✅ Решение отправлено клиенту, заказ закрыт.", reply_markup=kb.manager_menu())

    # ---------- ответ клиенту ----------
    @r.callback_query(F.data.startswith("rpl:"))
    async def reply_ask(c: CallbackQuery, state: FSMContext):
        client = storage.user(int(c.data[4:]))
        if client is None:
            await c.answer("Клиент не найден.", show_alert=True)
            return
        await state.set_state(Reply.text)
        await state.update_data(client_id=client.tg_id)
        await c.answer()
        await c.message.answer(f"Ответ для {escape(client.company or client.name)} – одним сообщением. Отмена – /cancel.")

    @r.message(Reply.text, F.text)
    async def reply_send(m: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        await notify(client_bot, [data["client_id"]], f"💬 <b>Ответ менеджера ЛогиХаб</b>\n\n{escape(m.text)}")
        await m.answer("✅ Ответ отправлен клиенту.", reply_markup=kb.manager_menu())

    # ---------- документы, сводка, KPI ----------
    @r.callback_query(F.data.startswith("doc:"))
    async def document(c: CallbackQuery):
        _, kind, oid = c.data.split(":")
        order = storage.get(int(oid))
        if order is None or c.data not in {d for _, d in kb.doc_buttons(order, storage.order_claim(order.id) is not None)}:
            await c.answer("Документ пока не сформирован.", show_alert=True)
            return
        await c.answer("Формирую документ…")
        data, name = await asyncio.to_thread(documents.render, storage, kind, order)
        await c.message.answer_document(BufferedInputFile(data, name))

    @r.callback_query(F.data == "sum:csv")
    async def export(c: CallbackQuery):
        await c.answer("Готовлю выгрузку…")
        data = export_csv(storage.export_rows())
        await c.message.answer_document(BufferedInputFile(data, f"logihub_orders_{now():%Y-%m-%d}.csv"),
                                        caption="📤 Выгрузка заказов бота (CSV, разделитель «;» – открывается в Excel)")

    @r.callback_query(F.data.startswith("kpi:"))
    async def kpi_period(c: CallbackQuery):
        await c.answer()
        await send_kpi(c.message, c.data[4:])

    async def send_kpi(m: Message, freq: str):
        png = await asyncio.to_thread(analytics.otif_chart, freq)
        await m.answer_photo(BufferedInputFile(png, filename="otif.png"),
                             caption=analytics.summary(freq) + f"\n\n🖥 Подробная аналитика – в дашборде: "
                                                               f"{settings.dashboard_url}",
                             reply_markup=kb.kpi(settings.dashboard_url))

    # ---------- всё остальное ----------
    @r.callback_query()
    async def stale_button(c: CallbackQuery):
        await c.answer("Кнопка устарела – откройте нужный раздел в меню.", show_alert=True)

    @r.message()
    async def unknown(m: Message):
        await m.answer("Выберите раздел в меню ниже или отправьте /help.", reply_markup=kb.manager_menu())

    return r
