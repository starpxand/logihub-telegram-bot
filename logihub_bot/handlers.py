"""Обработчики бота: сценарии клиента и менеджера по BPMN-модели процесса."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from . import keyboards as kb
from . import texts
from .analytics import Analytics
from .config import Settings
from .pricing import PricingError, quote
from .storage import Storage, TransitionError, parse_number

log = logging.getLogger(__name__)


class NewOrder(StatesGroup):
    destination = State()
    cargo = State()
    weight = State()
    ship_date = State()
    confirm = State()


class Track(StatesGroup):
    number = State()


class Claim(StatesGroup):
    text = State()


def build_router(storage: Storage, analytics: Analytics, settings: Settings) -> Router:
    r = Router(name="logihub")

    async def notify(bot: Bot, chat_ids, text: str, markup=None) -> None:
        for chat_id in set(chat_ids):
            try:
                await bot.send_message(chat_id, text, reply_markup=markup)
            except Exception as exc:  # пользователь мог заблокировать бота
                log.warning("notify %s failed: %s", chat_id, exc)

    def menu(user_id: int):
        return kb.manager_menu() if storage.role(user_id) == "manager" else kb.client_menu()

    # ---------- общие ----------
    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear()
        if storage.role(m.from_user.id) is None:
            storage.upsert_user(m.from_user.id, m.from_user.full_name, "client")
        await m.answer(texts.WELCOME.format(name=m.from_user.first_name), reply_markup=menu(m.from_user.id))

    @r.message(Command("help"))
    @r.message(F.text == kb.HELP)
    async def help_(m: Message):
        await m.answer(texts.HELP, reply_markup=menu(m.from_user.id))

    @r.message(Command("cancel"))
    async def cancel(m: Message, state: FSMContext):
        await state.clear()
        await m.answer("Действие отменено.", reply_markup=menu(m.from_user.id))

    @r.message(Command("manager"))
    async def as_manager(m: Message, command: CommandObject):
        if (command.args or "").strip() != settings.manager_code:
            await m.answer("⛔ Неверный код менеджера.")
            return
        storage.upsert_user(m.from_user.id, m.from_user.full_name, "manager")
        await m.answer("🔑 Режим менеджера включён. Новые заявки будут приходить вам автоматически.",
                       reply_markup=kb.manager_menu())

    @r.message(Command("client"))
    async def as_client(m: Message):
        storage.upsert_user(m.from_user.id, m.from_user.full_name, "client")
        await m.answer("Режим клиента включён.", reply_markup=kb.client_menu())

    # ---------- клиент: новая заявка (этапы BPMN 1–2, 6) ----------
    @r.message(Command("new"))
    @r.message(F.text == kb.NEW_ORDER)
    async def new_order(m: Message, state: FSMContext):
        await state.set_state(NewOrder.destination)
        await m.answer("📦 <b>Новая заявка на перевозку</b>\nОтправка со склада в Комсомольске-на-Амуре.\n\n"
                       "Шаг 1 из 4. Выберите город доставки:", reply_markup=kb.destinations())

    @r.callback_query(NewOrder.destination, F.data.startswith("dst:"))
    async def order_destination(c: CallbackQuery, state: FSMContext):
        await state.update_data(destination=c.data[4:])
        await state.set_state(NewOrder.cargo)
        await c.message.edit_text(f"Город доставки: <b>{c.data[4:]}</b>\n\nШаг 2 из 4. Категория груза:",
                                  reply_markup=kb.cargo_types())
        await c.answer()

    @r.callback_query(NewOrder.cargo, F.data.startswith("cargo:"))
    async def order_cargo(c: CallbackQuery, state: FSMContext):
        await state.update_data(cargo=c.data[6:])
        await state.set_state(NewOrder.weight)
        await c.message.edit_text(f"Категория груза: <b>{c.data[6:]}</b>\n\nШаг 3 из 4. Введите вес груза в килограммах "
                                  "(например, 3200):")
        await c.answer()

    @r.message(NewOrder.weight)
    async def order_weight(m: Message, state: FSMContext):
        try:
            weight = float((m.text or "").replace(",", ".").replace(" ", ""))
            if not 0 < weight <= 24000:
                raise ValueError
        except ValueError:
            await m.answer("Введите вес числом от 1 до 24 000 кг.")
            return
        await state.update_data(weight=weight)
        await state.set_state(NewOrder.ship_date)
        tomorrow = date.today() + timedelta(days=1)
        await m.answer(f"Шаг 4 из 4. Дата отгрузки в формате ДД.ММ.ГГГГ (например, {tomorrow:%d.%m.%Y}):")

    @r.message(NewOrder.ship_date)
    async def order_date(m: Message, state: FSMContext):
        try:
            d, mo, y = (m.text or "").strip().split(".")
            ship = date(int(y), int(mo), int(d))
            if ship < date.today():
                raise ValueError
        except ValueError:
            await m.answer("Дата должна быть в формате ДД.ММ.ГГГГ и не раньше сегодняшнего дня.")
            return
        data = await state.get_data()
        try:
            q = quote(data["destination"], data["cargo"], data["weight"], ship)
        except PricingError as exc:
            await state.clear()
            await m.answer(f"⚠️ {exc}", reply_markup=kb.client_menu())
            return
        await state.update_data(ship_date=ship.isoformat())
        await state.set_state(NewOrder.confirm)
        await m.answer(texts.quote_card(q), reply_markup=kb.confirm_order())

    @r.callback_query(NewOrder.confirm, F.data == "order:send")
    async def order_send(c: CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        q = quote(data["destination"], data["cargo"], data["weight"], date.fromisoformat(data["ship_date"]))
        order = storage.create_order(c.from_user.id, q)
        await state.clear()
        await c.message.edit_text(texts.quote_card(q) + f"\n\n✅ Заявка <b>{order.number}</b> отправлена менеджеру на проверку.")
        await c.message.answer("Я пришлю уведомление, когда менеджер проверит заявку.", reply_markup=kb.client_menu())
        await notify(bot, storage.managers(), "🆕 Новая заявка на проверку\n\n" + texts.order_card(order),
                     kb.review(order.id))
        await c.answer("Заявка отправлена")

    @r.callback_query(NewOrder.confirm, F.data == "order:cancel")
    async def order_cancel(c: CallbackQuery, state: FSMContext):
        await state.clear()
        await c.message.edit_text("Заявка отменена.")
        await c.answer()

    # ---------- клиент: заказы, статус, приёмка (этапы 15–22) ----------
    @r.message(F.text == kb.MY_ORDERS)
    async def my_orders(m: Message):
        orders = storage.list(client_id=m.from_user.id)
        if not orders:
            await m.answer("У вас пока нет заказов. Нажмите «📦 Новая заявка».")
            return
        lines = [f"• <b>{o.number}</b> → {o.destination}: {o.status_text}" for o in orders[-10:]]
        await m.answer("🗂 <b>Ваши заказы</b>\n" + "\n".join(lines))

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
        if order is None or (storage.role(m.from_user.id) != "manager" and order.client_id != m.from_user.id):
            await m.answer("Заказ не найден. Проверьте номер.", reply_markup=menu(m.from_user.id))
            return
        await m.answer(texts.order_card(order, storage.history(order.id)), reply_markup=menu(m.from_user.id))

    @r.message(F.text == kb.ACCEPT)
    async def accept_list(m: Message):
        orders = storage.list(status="delivered", client_id=m.from_user.id)
        if not orders:
            await m.answer("Нет доставленных заказов, ожидающих приёмки.")
            return
        for o in orders:
            await m.answer("📍 Груз доставлен. Проверьте количество, целостность и температурный режим.\n\n"
                           + texts.order_card(o), reply_markup=kb.acceptance(o.id))

    @r.callback_query(F.data.startswith("acc:ok:"))
    async def accept_ok(c: CallbackQuery, bot: Bot):
        order = await change(c, int(c.data.split(":")[2]), "accepted", "Акт приёмки подписан клиентом")
        if order:
            await c.message.edit_text(texts.order_card(order) + "\n\n✍️ Акт приёмки подписан. Спасибо!")
            await notify(bot, storage.managers(), f"✍️ Клиент подписал акт по заказу {order.number}. Заказ можно закрыть.",
                         kb.close_claim(order.id))

    @r.callback_query(F.data.startswith("acc:claim:"))
    async def accept_claim(c: CallbackQuery, state: FSMContext):
        await state.set_state(Claim.text)
        await state.update_data(order_id=int(c.data.split(":")[2]))
        await c.message.answer("Опишите замечания: что не так с грузом (недовложение, повреждение, температура)?")
        await c.answer()

    @r.message(Claim.text)
    async def claim_text(m: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        await state.clear()
        try:
            order = storage.set_status(data["order_id"], "claim", f"Претензия: {m.text}")
        except TransitionError as exc:
            await m.answer(f"⚠️ {exc}")
            return
        await m.answer(f"📝 Претензия по заказу {order.number} передана менеджеру.", reply_markup=kb.client_menu())
        await notify(bot, storage.managers(), "⚠️ Новая претензия\n\n" + texts.order_card(order), kb.close_claim(order.id))

    # ---------- менеджер (этапы 3–4, 14–18, 23–26) ----------
    def is_manager(user_id: int) -> bool:
        return storage.role(user_id) == "manager"

    @r.message(F.text == kb.QUEUE)
    async def queue(m: Message):
        if not is_manager(m.from_user.id):
            return
        orders = storage.list(status="new")
        if not orders:
            await m.answer("✨ Новых заявок нет.")
        for o in orders:
            await m.answer(texts.order_card(o), reply_markup=kb.review(o.id))

    @r.callback_query(F.data.startswith("rev:"))
    async def review(c: CallbackQuery, bot: Bot):
        _, action, oid = c.data.split(":")
        if action == "ok":
            order = await change(c, int(oid), "confirmed", "Заявка проверена менеджером, договор-счёт сформирован")
            if order:
                await c.message.edit_text(texts.order_card(order) + "\n\n✅ Подтверждена", reply_markup=kb.work(order.id, "confirmed"))
                await notify(bot, [order.client_id], f"✅ Заявка {order.number} проверена. Договор-счёт на "
                             f"{texts.rub(order.price)} сформирован, ожидаем оплату.")
        else:
            order = await change(c, int(oid), "clarify", "Нужно уточнить контакт получателя")
            if order:
                await c.message.edit_text(texts.order_card(order) + "\n\n↩️ Возвращена на уточнение")
                await notify(bot, [order.client_id], f"↩️ Заявка {order.number} возвращена на уточнение: "
                             "укажите телефон ответственного на складе получателя. Оформите заявку заново.")

    @r.message(F.text == kb.IN_WORK)
    async def in_work(m: Message):
        if not is_manager(m.from_user.id):
            return
        orders = [o for s in ("confirmed", "in_transit", "delayed") for o in storage.list(status=s)]
        if not orders:
            await m.answer("Нет заказов в работе.")
        for o in orders:
            await m.answer(texts.order_card(o), reply_markup=kb.work(o.id, o.status))

    @r.callback_query(F.data.startswith("wrk:"))
    async def work(c: CallbackQuery, bot: Bot):
        _, action, oid = c.data.split(":")
        order = storage.get(int(oid))
        if order is None:
            await c.answer("Заказ не найден", show_alert=True)
            return
        if action == "transit":
            order = await change(c, order.id, "in_transit", "Груз отгружен, рейс начат")
            msg = f"🚚 Заказ {order.number} в пути. Ожидаемая доставка {order.eta:%d.%m.%Y}." if order else None
        elif action == "delay":
            new_eta = order.eta + timedelta(days=1)
            order = await change(c, order.id, "delayed", "Отклонение от графика, маршрут перепланирован", eta=new_eta)
            msg = (f"⏰ По заказу {order.number} отклонение от графика. Маршрут перепланирован, "
                   f"новая дата доставки: <b>{order.eta:%d.%m.%Y}</b>. Приносим извинения.") if order else None
        else:
            order = await change(c, order.id, "delivered", "Груз доставлен получателю")
            msg = (f"📍 Заказ {order.number} доставлен. Откройте «✅ Приёмка груза», чтобы подписать акт "
                   "или оформить претензию.") if order else None
        if order:
            markup = kb.work(order.id, order.status) if order.status in ("in_transit", "delayed") else None
            await c.message.edit_text(texts.order_card(order), reply_markup=markup)
            await notify(bot, [order.client_id], msg)

    @r.callback_query(F.data.startswith("clm:close:"))
    async def close(c: CallbackQuery, bot: Bot):
        order = await change(c, int(c.data.split(":")[2]), "closed", "Заказ закрыт, OTIF пересчитан")
        if order:
            await c.message.edit_text(texts.order_card(order, storage.history(order.id)))
            await notify(bot, [order.client_id], f"🏁 Заказ {order.number} закрыт. Спасибо, что выбрали ЛогиХаб!")

    async def change(c: CallbackQuery, order_id: int, status: str, note: str, eta=None):
        try:
            order = storage.set_status(order_id, status, note, eta=eta)
        except TransitionError as exc:
            await c.answer(str(exc), show_alert=True)
            return None
        await c.answer("Готово")
        return order

    # ---------- KPI из дашборда ----------
    @r.message(Command("kpi"))
    @r.message(F.text == kb.KPI)
    async def kpi(m: Message):
        await send_kpi(m, "M")

    @r.callback_query(F.data.startswith("kpi:"))
    async def kpi_period(c: CallbackQuery):
        await send_kpi(c.message, c.data[4:])
        await c.answer()

    async def send_kpi(m: Message, freq: str):
        chart = BufferedInputFile(analytics.otif_chart(freq), filename="otif.png")
        await m.answer_photo(chart, caption=analytics.summary(freq) +
                             f"\n\n🖥 Подробная аналитика – в дашборде: {settings.dashboard_url}",
                             reply_markup=kb.kpi(settings.dashboard_url))

    return r
