"""Клиентский бот: заявка, оплата, отслеживание, приёмка груза, претензия и связь с менеджером.

Этапы BPMN: 1–2 заявка, 5 уточнение, 6 расчёт, 8 оплата, 15–19 уведомления о рейсе, 20–22 приёмка, 23 претензия.
Уведомления менеджерам уходят через бот менеджера.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from . import documents
from . import keyboards as kb
from . import texts
from .config import PAYMENT_DAYS, Settings, now
from .notify import edit_or_send, notify, send_file, send_photos
from .pricing import MAX_WEIGHT_KG, TEMPERATURE, PricingError, quote
from .storage import CLAIM_KINDS, Order, Storage, TransitionError, parse_number

log = logging.getLogger(__name__)

MAX_PHOTOS = 5
STEPS = 9


class Register(StatesGroup):
    company = State()
    phone = State()


class NewOrder(StatesGroup):
    destination = State()
    cargo = State()
    weight = State()
    places = State()
    address = State()
    recipient = State()
    ship_date = State()
    insurance = State()
    comment = State()
    confirm = State()


class Track(StatesGroup):
    number = State()


class Fix(StatesGroup):
    value = State()


class ClaimForm(StatesGroup):
    kind = State()
    text = State()
    photos = State()


class Support(StatesGroup):
    text = State()


FIX_PROMPTS = {
    "address": "Введите новый адрес доставки (улица, дом, склад или офис):",
    "recipient": "Введите получателя: ФИО и телефон ответственного на месте:",
    "places": "Введите количество грузовых мест:",
    "comment": "Введите комментарий для менеджера и склада:",
}


def _number(text: str | None) -> float | None:
    try:
        return float((text or "").replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _digits(text: str) -> int:
    return len(re.sub(r"\D", "", text))


def _check_recipient(text: str) -> str | None:
    if _digits(text) < 10 or not re.search(r"[A-Za-zА-Яа-яЁё]{2,}", text):
        return "Укажите ФИО и телефон получателя, например: Иванов Иван, +7 914 123-45-67"
    return None


def _check_date(ship: date) -> str | None:
    today = now().date()
    if ship <= today:
        return "Ближайшая дата отгрузки – завтра."
    if ship > today + timedelta(days=60):
        return "Заявки принимаются не более чем за 60 дней до отгрузки."
    if ship.weekday() == 6:
        return "По воскресеньям склад не отгружает – выберите другой день."
    return None


def build_client_router(storage: Storage, settings: Settings, manager_bot: Bot, manager_username: str) -> Router:
    r = Router(name="client")

    def card(o: Order, history: bool = False) -> str:
        return texts.order_card(o, storage.history(o.id) if history else None,
                                driver=storage.driver(o.driver_id), claim=storage.order_claim(o.id))

    def actions(o: Order):
        return kb.client_order(o, storage.order_claim(o.id) is not None)

    def managers() -> list[int]:
        return storage.managers()

    def manager_card(o: Order) -> str:
        return texts.order_card(o, client=storage.user(o.client_id), driver=storage.driver(o.driver_id),
                                claim=storage.order_claim(o.id))

    async def own(c: CallbackQuery, order_id: int, statuses=None) -> Order | None:
        order = storage.get(order_id)
        if order is None or order.client_id != c.from_user.id:
            await c.answer("Заказ не найден.", show_alert=True)
            return None
        if statuses and order.status not in statuses:
            await c.answer(f"Сейчас заказ в статусе «{order.status_text}» – действие недоступно.", show_alert=True)
            return None
        return order

    # ---------- меню и справка ----------
    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear()
        storage.ensure_client(m.from_user.id, m.from_user.full_name)
        await m.answer(texts.WELCOME.format(name=escape(m.from_user.first_name or "")), reply_markup=kb.client_menu())

    @r.message(Command("cancel"))
    async def cancel(m: Message, state: FSMContext):
        await state.clear()
        await m.answer("Действие отменено.", reply_markup=kb.client_menu())

    @r.message(Command("help"))
    async def help_(m: Message, state: FSMContext):
        await state.clear()
        await m.answer(texts.HELP_CLIENT, reply_markup=kb.client_menu())

    @r.message(Command("about"))
    @r.message(F.text == kb.ABOUT)
    async def about(m: Message, state: FSMContext):
        await state.clear()
        await m.answer(texts.ABOUT, reply_markup=kb.client_menu(), disable_web_page_preview=True)

    @r.message(Command("tariffs"))
    @r.message(F.text == kb.TARIFFS)
    async def tariffs(m: Message, state: FSMContext):
        await state.clear()
        await m.answer(texts.tariffs(), reply_markup=kb.calc())

    @r.message(Command("manager", "kpi"))
    async def staff(m: Message):
        await m.answer(f"🔑 Рабочее место сотрудников – отдельный бот @{manager_username}")

    @r.message(Command("new"))
    @r.message(F.text == kb.NEW_ORDER)
    async def new_order(m: Message, state: FSMContext):
        await begin(m, m.from_user, state)

    @r.callback_query(F.data == "calc")
    async def calc(c: CallbackQuery, state: FSMContext):
        await c.answer()
        await begin(c.message, c.from_user, state)

    # ---------- мои заказы и отслеживание ----------
    @r.message(Command("orders"))
    @r.message(F.text == kb.MY_ORDERS)
    async def my_orders(m: Message, state: FSMContext):
        await state.clear()
        orders = storage.list(client_id=m.from_user.id)
        if not orders:
            await m.answer("У вас пока нет заказов. Нажмите «📦 Новая заявка».")
            return
        active = [o for o in reversed(orders) if o.status not in ("closed", "cancelled")]
        done = [o for o in reversed(orders) if o.status in ("closed", "cancelled")]
        await m.answer(f"🗂 <b>Ваши заказы</b>\nВ работе: {len(active)}, завершено: {len(done)}. Выберите заказ:",
                       reply_markup=kb.my_orders((active + done)[:10]))

    @r.callback_query(F.data.startswith("co:open:"))
    async def open_order(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]))
        if order:
            await c.answer()
            await edit_or_send(c.message, card(order), actions(order))

    @r.callback_query(F.data.startswith("co:hist:"))
    async def order_history(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]))
        if order:
            await c.answer()
            await edit_or_send(c.message, card(order, history=True), actions(order))

    @r.message(Command("status"))
    async def status_cmd(m: Message, command: CommandObject, state: FSMContext):
        if command.args:
            await show_status(m, command.args)
        else:
            await state.set_state(Track.number)
            await m.answer("Введите номер заказа, например LH-20001:")

    @r.message(F.text == kb.TRACK)
    async def track(m: Message, state: FSMContext):
        await state.set_state(Track.number)
        await m.answer("Введите номер заказа, например LH-20001:")

    @r.message(Track.number)
    async def track_number(m: Message, state: FSMContext):
        await state.clear()
        await show_status(m, m.text or "")

    async def show_status(m: Message, raw: str):
        order_id = parse_number(raw)
        order = storage.get(order_id) if order_id else None
        if order is None or order.client_id != m.from_user.id:
            await m.answer("Заказ не найден. Проверьте номер – он есть в «🗂 Мои заказы».", reply_markup=kb.client_menu())
            return
        await m.answer(card(order, history=True), reply_markup=actions(order))

    # ---------- связь с менеджером ----------
    @r.message(Command("support"))
    @r.message(F.text == kb.SUPPORT)
    async def support(m: Message, state: FSMContext):
        storage.ensure_client(m.from_user.id, m.from_user.full_name)
        await state.set_state(Support.text)
        await m.answer("Напишите вопрос одним сообщением – менеджер ответит здесь же. "
                       "Если вопрос по заказу, укажите его номер. Прервать – /cancel.")

    @r.message(Support.text, F.text)
    async def support_text(m: Message, state: FSMContext):
        await state.clear()
        user = storage.user(m.from_user.id)
        who = escape(user.company or user.name) + (f", {escape(user.phone)}" if user.phone else "")
        await notify(manager_bot, managers(), f"💬 <b>Вопрос клиента</b> ({who})\n\n{escape(m.text)}",
                     kb.reply(m.from_user.id))
        await m.answer("✅ Сообщение передано менеджеру. Отвечаем пн–пт 9:00–18:00 (хабаровское время).",
                       reply_markup=kb.client_menu())

    # ---------- знакомство с клиентом ----------
    async def begin(m: Message, user, state: FSMContext):
        await state.clear()
        storage.ensure_client(user.id, user.full_name)
        if not storage.user(user.id).phone:
            await state.set_state(Register.company)
            await m.answer("Перед первой заявкой познакомимся 🙂\n\nУкажите организацию, от имени которой "
                           "отправляете груз (например, ООО «Амур-Трейд»), или нажмите кнопку ниже.",
                           reply_markup=kb.private_person())
            return
        await ask_destination(m, state)

    @r.message(Register.company, F.text)
    async def reg_company(m: Message, state: FSMContext):
        if len(m.text.strip()) < 2 or m.text.startswith("/"):
            await m.answer("Введите название организации или нажмите «Я частное лицо».")
            return
        storage.set_contact(m.from_user.id, company=m.text.strip()[:120])
        await ask_phone(m, state)

    @r.callback_query(Register.company, F.data == "reg:private")
    async def reg_private(c: CallbackQuery, state: FSMContext):
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=None)
        await ask_phone(c.message, state)

    async def ask_phone(m: Message, state: FSMContext):
        await state.set_state(Register.phone)
        await m.answer("Телефон для связи по заказам – отправьте кнопкой ниже или введите в формате "
                       "+7 914 123-45-67.", reply_markup=kb.share_phone())

    @r.message(Register.phone)
    async def reg_phone(m: Message, state: FSMContext):
        if m.contact:
            phone = texts.phone(m.contact.phone_number)
        elif m.text and _digits(m.text) >= 10:
            phone = texts.phone(m.text[:30])
        else:
            await m.answer("Не похоже на номер телефона. Нажмите «📱 Отправить мой номер» или введите номер цифрами.")
            return
        storage.set_contact(m.from_user.id, phone=phone)
        await m.answer("✅ Контакты сохранены – менеджер сможет связаться с вами по заказу.",
                       reply_markup=kb.client_menu())
        await ask_destination(m, state)

    # ---------- заявка на перевозку (этапы 2 и 6) ----------
    async def ask_destination(m: Message, state: FSMContext):
        await state.set_state(NewOrder.destination)
        await m.answer("📦 <b>Новая заявка на перевозку</b>\nОтправка со склада в Комсомольске-на-Амуре. "
                       f"Прервать – /cancel.\n\nШаг 1 из {STEPS}. Город доставки:", reply_markup=kb.destinations())

    @r.callback_query(NewOrder.destination, F.data.startswith("dst:"))
    async def order_destination(c: CallbackQuery, state: FSMContext):
        await state.update_data(destination=c.data[4:])
        await state.set_state(NewOrder.cargo)
        await c.message.edit_text(f"Город доставки: <b>{c.data[4:]}</b>\n\nШаг 2 из {STEPS}. Категория груза:",
                                  reply_markup=kb.cargo_types())
        await c.answer()

    @r.callback_query(NewOrder.cargo, F.data.startswith("cargo:"))
    async def order_cargo(c: CallbackQuery, state: FSMContext):
        cargo = c.data[6:]
        await state.update_data(cargo=cargo)
        await state.set_state(NewOrder.weight)
        note = (f"\n🌡 Груз с температурным режимом {TEMPERATURE[cargo]} – поедет в рефрижераторе."
                if cargo in TEMPERATURE else "")
        await c.message.edit_text(f"Категория груза: <b>{cargo}</b>{note}\n\n"
                                  f"Шаг 3 из {STEPS}. Общий вес груза в килограммах (например, 3200):")
        await c.answer()

    @r.message(NewOrder.weight)
    async def order_weight(m: Message, state: FSMContext):
        weight = _number(m.text)
        if weight is None or not 0 < weight <= MAX_WEIGHT_KG:
            await m.answer(f"Введите вес числом от 1 до {texts.num(MAX_WEIGHT_KG)} кг. Больше – оформите "
                           "несколько заявок или напишите менеджеру.")
            return
        await state.update_data(weight=weight)
        await state.set_state(NewOrder.places)
        await m.answer(f"Шаг 4 из {STEPS}. Количество грузовых мест (коробки, паллеты):")

    @r.message(NewOrder.places)
    async def order_places(m: Message, state: FSMContext):
        places = _number(m.text)
        if places is None or places != int(places) or not 1 <= places <= 999:
            await m.answer("Введите количество мест целым числом от 1 до 999.")
            return
        await state.update_data(places=int(places))
        await state.set_state(NewOrder.address)
        city = (await state.get_data())["destination"]
        await m.answer(f"Шаг 5 из {STEPS}. Адрес доставки в г. {city} (улица, дом, склад или офис):")

    @r.message(NewOrder.address, F.text)
    async def order_address(m: Message, state: FSMContext):
        if len(m.text.strip()) < 5:
            await m.answer("Укажите адрес подробнее: улица, дом, склад или офис.")
            return
        await state.update_data(address=m.text.strip()[:200])
        await state.set_state(NewOrder.recipient)
        await m.answer(f"Шаг 6 из {STEPS}. Получатель: ФИО и телефон ответственного на месте "
                       "(например, Иванов Иван, +7 914 123-45-67):")

    @r.message(NewOrder.recipient, F.text)
    async def order_recipient(m: Message, state: FSMContext):
        error = _check_recipient(m.text)
        if error:
            await m.answer(error)
            return
        await state.update_data(recipient=m.text.strip()[:200])
        await state.set_state(NewOrder.ship_date)
        await m.answer(f"Шаг 7 из {STEPS}. Дата отгрузки со склада – выберите или введите ДД.ММ.ГГГГ "
                       "(склад отгружает пн–сб):", reply_markup=kb.ship_dates(now().date()))

    @r.callback_query(NewOrder.ship_date, F.data.startswith("shp:"))
    async def order_date_button(c: CallbackQuery, state: FSMContext):
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=None)
        await set_date(c.message, state, date.fromisoformat(c.data[4:]))

    @r.message(NewOrder.ship_date)
    async def order_date_text(m: Message, state: FSMContext):
        try:
            d, mo, y = (m.text or "").strip().split(".")
            ship = date(int(y), int(mo), int(d))
        except ValueError:
            await m.answer("Введите дату в формате ДД.ММ.ГГГГ или выберите кнопкой.",
                           reply_markup=kb.ship_dates(now().date()))
            return
        await set_date(m, state, ship)

    async def set_date(m: Message, state: FSMContext, ship: date):
        error = _check_date(ship)
        if error:
            await m.answer(error, reply_markup=kb.ship_dates(now().date()))
            return
        await state.update_data(ship_date=ship.isoformat())
        await state.set_state(NewOrder.insurance)
        await m.answer(f"Отгрузка: <b>{ship:%d.%m.%Y}</b>\n\nШаг 8 из {STEPS}. Страхование груза: введите объявленную "
                       "стоимость груза в рублях (страховка – 0,3 %, минимум 300 ₽) или нажмите «Без страховки».",
                       reply_markup=kb.no_insurance())

    @r.callback_query(NewOrder.insurance, F.data == "ins:0")
    async def order_no_insurance(c: CallbackQuery, state: FSMContext):
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=None)
        await set_insurance(c.message, state, 0)

    @r.message(NewOrder.insurance)
    async def order_insurance(m: Message, state: FSMContext):
        value = _number(m.text)
        if value is None or not 0 <= value <= 500_000_000:
            await m.answer("Введите объявленную стоимость числом в рублях или нажмите «Без страховки».",
                           reply_markup=kb.no_insurance())
            return
        await set_insurance(m, state, value)

    async def set_insurance(m: Message, state: FSMContext, value: float):
        await state.update_data(declared_value=value)
        await state.set_state(NewOrder.comment)
        await m.answer(f"Шаг 9 из {STEPS}. Комментарий для склада и водителя: часы приёмки, въезд, "
                       "нужен ли погрузчик – или нажмите «Без комментария».", reply_markup=kb.skip_comment())

    @r.callback_query(NewOrder.comment, F.data == "cmt:skip")
    async def order_no_comment(c: CallbackQuery, state: FSMContext):
        await c.answer()
        await c.message.edit_reply_markup(reply_markup=None)
        await show_quote(c.message, state, None)

    @r.message(NewOrder.comment, F.text)
    async def order_comment(m: Message, state: FSMContext):
        await show_quote(m, state, m.text.strip()[:300])

    def build_quote(data: dict):
        return quote(data["destination"], data["cargo"], data["weight"], date.fromisoformat(data["ship_date"]),
                     declared_value=data.get("declared_value", 0))

    async def show_quote(m: Message, state: FSMContext, comment: str | None):
        await state.update_data(comment=comment)
        data = await state.get_data()
        try:
            q = build_quote(data)
        except PricingError as exc:
            await state.clear()
            await m.answer(f"⚠️ {exc}", reply_markup=kb.client_menu())
            return
        await state.set_state(NewOrder.confirm)
        await m.answer(texts.quote_card(q, data["places"], data["address"], data["recipient"], comment)
                       + "\n\nПроверьте данные и отправьте заявку менеджеру.", reply_markup=kb.confirm_order())

    @r.callback_query(NewOrder.confirm, F.data == "order:send")
    async def order_send(c: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        q = build_quote(data)
        order = storage.create_order(c.from_user.id, q, places=data["places"], address=data["address"],
                                     recipient=data["recipient"], comment=data.get("comment"))
        await state.clear()
        await c.answer("Заявка отправлена")
        await c.message.edit_text(texts.quote_card(q, order.places, order.address, order.recipient, order.comment)
                                  + f"\n\n✅ Заявка <b>{order.number}</b> принята и передана менеджеру на проверку.")
        await c.message.answer("Менеджер проверит заявку и пришлёт договор-счёт – обычно в течение часа "
                               "в рабочее время. Статус – в разделе «🗂 Мои заказы».", reply_markup=kb.client_menu())
        await notify(manager_bot, managers(), "🆕 <b>Новая заявка</b>\n\n" + manager_card(order), kb.review(order.id))

    @r.callback_query(NewOrder.confirm, F.data == "order:cancel")
    async def order_cancel(c: CallbackQuery, state: FSMContext):
        await state.clear()
        await c.message.edit_text("Заявка не отправлена. Оформить новую – «📦 Новая заявка».")
        await c.answer()

    # ---------- документы ----------
    @r.callback_query(F.data.startswith("doc:"))
    async def document(c: CallbackQuery):
        _, kind, oid = c.data.split(":")
        order = await own(c, int(oid))
        if not order:
            return
        if c.data not in {d for _, d in kb.doc_buttons(order, storage.order_claim(order.id) is not None)}:
            await c.answer("Документ пока не сформирован.", show_alert=True)
            return
        await c.answer("Формирую документ…")
        data, name = await asyncio.to_thread(documents.render, storage, kind, order)
        await c.message.answer_document(BufferedInputFile(data, name))

    # ---------- отмена и оплата (этапы 8–9) ----------
    @r.callback_query(F.data.startswith("co:cancel:"))
    async def cancel_ask(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("new", "clarify", "confirmed"))
        if order:
            await c.answer()
            await edit_or_send(c.message, card(order) + "\n\n<b>Отменить заказ?</b>", kb.cancel_confirm(order.id))

    @r.callback_query(F.data.startswith("co:cancelyes:"))
    async def cancel_yes(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("new", "clarify", "confirmed"))
        if not order:
            return
        order = storage.set_status(order.id, "cancelled", "Заказ отменён клиентом")
        await c.answer("Заказ отменён")
        await edit_or_send(c.message, card(order))
        await notify(manager_bot, managers(), f"✖️ Клиент отменил заказ <b>{order.number}</b> "
                                              f"({escape(order.destination)}, {texts.rub(order.total)}).")

    @r.callback_query(F.data.startswith("co:paid:"))
    async def paid(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("confirmed",))
        if not order:
            return
        storage.log(order.id, "Клиент сообщил об оплате")
        await c.answer("Спасибо!")
        await edit_or_send(c.message, card(order) + "\n\n💳 Спасибо! Как только оплата поступит на расчётный счёт, "
                                                    "заказ уйдёт на склад – сообщим.")
        await notify(manager_bot, managers(), f"💳 Клиент сообщил об оплате заказа <b>{order.number}</b> на "
                                              f"<b>{texts.rub(order.total)}</b>. Проверьте поступление на счёт.\n\n"
                                              + manager_card(order), kb.pay_control(order.id))

    # ---------- уточнение заявки (этап 5, цикл) ----------
    @r.callback_query(F.data.startswith("co:fix:"))
    async def fix_open(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("clarify",))
        if order:
            await c.answer()
            await edit_or_send(c.message, card(order, history=True) + "\n\nЧто исправить?", kb.fix_menu(order.id))

    @r.callback_query(F.data.startswith("fix:"))
    async def fix_field(c: CallbackQuery, state: FSMContext):
        _, field, oid = c.data.split(":")
        order = await own(c, int(oid), ("clarify",))
        if not order:
            return
        await c.answer()
        if field == "send":
            await state.clear()
            order = storage.set_status(order.id, "new", "Заявка уточнена клиентом и отправлена на повторную проверку")
            await edit_or_send(c.message, card(order) + "\n\n📨 Заявка снова на проверке у менеджера.")
            await notify(manager_bot, managers(), "🔁 <b>Заявка уточнена клиентом</b>\n\n"
                         + texts.order_card(order, storage.history(order.id)[-3:], client=storage.user(order.client_id)),
                         kb.review(order.id))
            return
        await state.set_state(Fix.value)
        await state.update_data(order_id=order.id, field=field)
        await c.message.answer(FIX_PROMPTS[field])

    @r.message(Fix.value, F.text)
    async def fix_value(m: Message, state: FSMContext):
        data = await state.get_data()
        value: object = m.text.strip()
        if data["field"] == "places":
            places = _number(m.text)
            if places is None or places != int(places) or not 1 <= places <= 999:
                await m.answer("Введите количество мест целым числом от 1 до 999.")
                return
            value = int(places)
        elif data["field"] == "recipient" and _check_recipient(m.text):
            await m.answer(_check_recipient(m.text))
            return
        elif data["field"] == "address" and len(m.text.strip()) < 5:
            await m.answer("Укажите адрес подробнее: улица, дом, склад или офис.")
            return
        await state.clear()
        order = storage.get(data["order_id"])
        if order is None or order.status != "clarify":
            await m.answer("Заявка уже не на уточнении.", reply_markup=kb.client_menu())
            return
        order = storage.update_order(order.id, **{data["field"]: value})
        await m.answer(card(order) + "\n\n✅ Изменено. Когда всё исправите – «📨 Отправить на повторную проверку».",
                       reply_markup=kb.fix_menu(order.id))

    # ---------- приёмка груза (этапы 20–22) ----------
    @r.callback_query(F.data.startswith("acc:ok:"))
    async def accept_ok(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("delivered",))
        if not order:
            return
        try:
            storage.set_status(order.id, "accepted", "Акт приёмки подписан клиентом без замечаний")
            order = storage.set_status(order.id, "closed", "Заказ закрыт, OTIF пересчитан")
        except TransitionError as exc:
            await c.answer(str(exc), show_alert=True)
            return
        await c.answer("Акт подписан")
        await edit_or_send(c.message, card(order))
        act, name = await asyncio.to_thread(documents.render, storage, "act", order)
        await c.message.answer_document(BufferedInputFile(act, name),
                                        caption=f"✍️ Акт приёмки подписан, заказ {order.number} выполнен. "
                                                "Спасибо, что выбрали ЛогиХаб!")
        await c.message.answer("Оцените, пожалуйста, доставку – это займёт секунду:", reply_markup=kb.rating(order.id))
        on_time = "вовремя ✅" if order.on_time else "с опозданием ⚠️"
        await send_file(manager_bot, managers(), act, name,
                        f"✍️ Клиент принял груз без замечаний. Заказ <b>{order.number}</b> закрыт, доставлен {on_time}.")

    @r.callback_query(F.data.startswith("acc:claim:"))
    async def accept_claim(c: CallbackQuery, state: FSMContext):
        order = await own(c, int(c.data.split(":")[2]), ("delivered",))
        if not order:
            return
        await state.set_state(ClaimForm.kind)
        await state.update_data(order_id=order.id, photos=[])
        await c.answer()
        await c.message.answer(f"⚠️ Претензия по заказу {order.number}. Что не так с грузом?",
                               reply_markup=kb.claim_kinds())

    @r.callback_query(ClaimForm.kind, F.data.startswith("ck:"))
    async def claim_kind(c: CallbackQuery, state: FSMContext):
        kind = c.data[3:]
        await state.update_data(kind=kind)
        await state.set_state(ClaimForm.text)
        await c.answer()
        await c.message.edit_text(f"Вид замечания: <b>{CLAIM_KINDS[kind]}</b>\n\nОпишите подробно: какие места или "
                                  "позиции, что повреждено или не хватает, показания термописца.")

    @r.message(ClaimForm.text, F.text)
    async def claim_text(m: Message, state: FSMContext):
        if len(m.text.strip()) < 10:
            await m.answer("Опишите замечание подробнее – менеджеру нужно понять, что произошло.")
            return
        await state.update_data(text=m.text.strip()[:1000])
        await state.set_state(ClaimForm.photos)
        await m.answer(f"Приложите фото (до {MAX_PHOTOS} шт.): повреждения, упаковку, этикетки, термограмму. "
                       "Когда закончите – «📨 Отправить претензию». Можно отправить и без фото.",
                       reply_markup=kb.claim_send())

    @r.message(ClaimForm.photos, F.photo)
    async def claim_photo(m: Message, state: FSMContext):
        photos = (await state.get_data())["photos"]
        if len(photos) >= MAX_PHOTOS:
            await m.answer(f"Можно приложить не больше {MAX_PHOTOS} фото.", reply_markup=kb.claim_send())
            return
        photos.append(m.photo[-1].file_id)
        await state.update_data(photos=photos)
        await m.answer(f"📎 Фото {len(photos)} добавлено.", reply_markup=kb.claim_send())

    @r.message(ClaimForm.photos)
    async def claim_photo_wait(m: Message):
        await m.answer("Отправьте фото или нажмите «📨 Отправить претензию».", reply_markup=kb.claim_send())

    @r.callback_query(ClaimForm.photos, F.data == "cl:send")
    async def claim_send(c: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        await state.clear()
        order = await own(c, data["order_id"], ("delivered",))
        if not order:
            return
        claim = storage.add_claim(order.id, data["kind"], data["text"], data["photos"])
        order = storage.set_status(order.id, "claim", f"Претензия: {claim.kind_text.lower()}")
        await c.answer("Претензия отправлена")
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer(f"📝 Претензия № {claim.id} по заказу {order.number} зарегистрирована. "
                               "Менеджер рассмотрит её в течение 3 рабочих дней и ответит здесь.",
                               reply_markup=kb.client_menu())
        await notify(manager_bot, managers(), "⚠️ <b>Претензия</b>\n\n" + manager_card(order),
                     kb.claim_decision(order.id))
        photos = []
        for file_id in claim.photos:
            try:
                photos.append((await bot.download(file_id)).read())
            except Exception as exc:
                log.warning("download %s failed: %s", file_id, exc)
        if photos:
            await send_photos(manager_bot, managers(), photos, f"📎 Фото к претензии по заказу {order.number}")

    # ---------- оценка ----------
    @r.callback_query(F.data.startswith("co:rate:"))
    async def rate_ask(c: CallbackQuery):
        order = await own(c, int(c.data.split(":")[2]), ("closed",))
        if order:
            await c.answer()
            await c.message.answer(f"Оцените доставку по заказу {order.number}:", reply_markup=kb.rating(order.id))

    @r.callback_query(F.data.startswith("rate:"))
    async def rate(c: CallbackQuery):
        _, oid, value = c.data.split(":")
        order = await own(c, int(oid), ("closed",))
        if not order:
            return
        if order.rating:
            await c.answer("Вы уже оценили этот заказ, спасибо!", show_alert=True)
            return
        storage.set_rating(order.id, int(value))
        await c.answer("Спасибо!")
        answer = "Спасибо за высокую оценку! 🙌" if int(value) >= 4 else \
            "Спасибо за честную оценку. Расскажите, что пошло не так, – «💬 Написать менеджеру»."
        await c.message.edit_text(f"Ваша оценка: {'⭐' * int(value)}\n{answer}")
        await notify(manager_bot, managers(), f"⭐ Клиент оценил заказ <b>{order.number}</b>: {'⭐' * int(value)}")

    # ---------- всё остальное ----------
    @r.callback_query()
    async def stale_button(c: CallbackQuery):
        await c.answer("Кнопка устарела – откройте нужный раздел в меню.", show_alert=True)

    @r.message()
    async def unknown(m: Message):
        await m.answer("Не понял сообщение 🙂 Выберите действие в меню ниже или отправьте /help.",
                       reply_markup=kb.client_menu())

    return r

