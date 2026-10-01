"""Сквозные сценарии двух ботов: обновления идут через Dispatcher, Telegram заменён фейковой сессией."""
from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, GetFile, SendDocument, SendMessage, SendPhoto
from aiogram.types import CallbackQuery, Chat, Contact, File, Message, PhotoSize, Update
from aiogram.types import User as TgUser

from logihub_bot import keyboards as kb
from logihub_bot.analytics import Analytics
from logihub_bot.client import build_client_router
from logihub_bot.config import Settings, now
from logihub_bot.jobs import check_payments
from logihub_bot.manager import build_manager_router
from logihub_bot.storage import Storage

CSV = Path(__file__).resolve().parents[1] / "data" / "logistics_orders.csv"
CLIENT, OTHER, MANAGER = 101, 102, 900
_ids = itertools.count(1)


TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote"}


class TelegramHTML(HTMLParser):
    """Проверка, что текст пройдёт parse_mode=HTML: только разрешённые теги, все закрыты."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.feed(text)
        self.close()
        assert not self.stack, f"не закрыты теги {self.stack}: {text!r}"

    def handle_starttag(self, tag, attrs):
        assert tag in TELEGRAM_TAGS, f"тег <{tag}> Telegram не поддерживает"
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, f"лишний </{tag}>"


def check_limits(method):
    text = getattr(method, "text", None)
    caption = getattr(method, "caption", None)
    if isinstance(text, str):
        assert len(text) <= 4096, f"сообщение длиннее 4096 символов: {len(text)}"
        TelegramHTML(text)
    if isinstance(caption, str):
        assert len(caption) <= 1024, f"подпись длиннее 1024 символов: {len(caption)}"
        TelegramHTML(caption)
    markup = getattr(method, "reply_markup", None)
    for row in getattr(markup, "inline_keyboard", None) or []:
        for button in row:
            assert button.url or len(button.callback_data.encode()) <= 64, button.callback_data


class FakeSession(BaseSession):
    """Вместо HTTP-запросов к Telegram запоминает вызванные методы Bot API."""

    def __init__(self):
        super().__init__()
        self.sent = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, SendDocument, SendPhoto, EditMessageText)):
            check_limits(method)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="photos/p.jpg")
        if method.__returning__ is bool:
            return True
        return Message(message_id=next(_ids), date=datetime.now(),
                       chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"),
                       text=getattr(method, "text", None))

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b"\xff\xd8 fake jpeg"

    async def close(self):
        pass

    def to(self, chat_id, kind=(SendMessage, SendDocument, SendPhoto)):
        return [m for m in self.sent if isinstance(m, kind) and m.chat_id == chat_id]

    def last(self, chat_id) -> str:
        m = self.to(chat_id, (SendMessage, SendDocument))[-1]
        return m.text if isinstance(m, SendMessage) else m.caption

    def buttons(self, chat_id) -> list[str]:
        markup = self.to(chat_id, (SendMessage, SendDocument))[-1].reply_markup
        return [b.callback_data for row in getattr(markup, "inline_keyboard", []) for b in row]


class World:
    def __init__(self):
        self.storage = Storage()
        settings = Settings(bot_token="1:A", manager_bot_token="2:B", manager_code="secret")
        props = DefaultBotProperties(parse_mode="HTML")
        self.cs, self.ms = FakeSession(), FakeSession()
        self.client_bot = Bot("111:CLIENT", session=self.cs, default=props)
        self.manager_bot = Bot("222:MANAGER", session=self.ms, default=props)
        self.client_dp, self.manager_dp = Dispatcher(), Dispatcher()
        self.client_dp.include_router(build_client_router(self.storage, settings, self.manager_bot, "logihub_manager_bot"))
        self.manager_dp.include_router(build_manager_router(self.storage, Analytics(CSV), settings, self.client_bot))

    def _dp(self, who):
        return (self.client_dp, self.client_bot) if who == "client" else (self.manager_dp, self.manager_bot)

    async def say(self, who, user_id, text=None, **extra):
        dp, bot = self._dp(who)
        msg = Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user_id, type="private"),
                      from_user=TgUser(id=user_id, is_bot=False, first_name=f"U{user_id}"), text=text, **extra)
        await dp.feed_update(bot, Update(update_id=next(_ids), message=msg))

    async def press(self, who, user_id, data):
        dp, bot = self._dp(who)
        card = Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user_id, type="private"), text="card")
        cq = CallbackQuery(id=str(next(_ids)), from_user=TgUser(id=user_id, is_bot=False, first_name=f"U{user_id}"),
                           chat_instance="ci", data=data, message=card)
        await dp.feed_update(bot, Update(update_id=next(_ids), callback_query=cq))

    async def login_manager(self):
        await self.say("manager", MANAGER, "/start")
        await self.say("manager", MANAGER, "secret")

    async def new_order(self, user_id=CLIENT, register=True):
        await self.say("client", user_id, kb.NEW_ORDER)
        if register:
            await self.say("client", user_id, "ООО «Амур-Трейд»")
            await self.say("client", user_id, contact=Contact(phone_number="79140001122", first_name="U", user_id=user_id))
        await self.press("client", user_id, "dst:Хабаровск")
        await self.press("client", user_id, "cargo:Продукты питания")
        for text in ("3 200", "12", "ул. Промышленная, 12, склад 3", "Иванов Иван, +7 914 123-45-67"):
            await self.say("client", user_id, text)
        ship = now().date() + timedelta(days=2)
        ship += timedelta(days=1) if ship.weekday() == 6 else timedelta()
        await self.press("client", user_id, f"shp:{ship.isoformat()}")
        await self.say("client", user_id, "900000")
        await self.press("client", user_id, "cmt:skip")
        await self.press("client", user_id, "order:send")
        return self.storage.list(client_id=user_id)[-1]


@pytest.fixture(autouse=True)
def no_delivery_errors(caplog):
    yield
    errors = [r.getMessage() for r in caplog.records if r.name.startswith(("logihub_bot", "aiogram")) and r.levelname in
              ("WARNING", "ERROR")]
    assert not errors, errors


def run(coro):
    return asyncio.run(coro)


def test_full_process_through_both_bots():
    async def scenario():
        w = World()
        await w.login_manager()
        assert w.storage.role(MANAGER) == "manager"
        order = await w.new_order()
        assert order.status == "new" and order.places == 12 and order.insurance == 2700
        assert w.storage.user(CLIENT).phone == "+7 914 000-11-22"
        assert "Новая заявка" in w.ms.last(MANAGER) and f"rev:ok:{order.id}" in w.ms.buttons(MANAGER)

        await w.press("manager", MANAGER, f"rev:ok:{order.id}")                    # этапы 3–7
        invoice = w.cs.to(CLIENT, SendDocument)[-1]
        assert invoice.document.filename == "Договор-счёт LH-20001.pdf"
        assert invoice.document.data.startswith(b"%PDF") and f"co:paid:{order.id}" in w.cs.buttons(CLIENT)

        await w.press("client", CLIENT, f"co:paid:{order.id}")                     # этап 8
        assert "сообщил об оплате" in w.ms.last(MANAGER)
        for step in ("pay:ok", "wh:start", "wh:short", "wh:full"):                # этапы 9–13
            await w.press("manager", MANAGER, f"{step}:{order.id}")
        assert w.ms.to(MANAGER, SendDocument)[-1].document.filename == "ТТН LH-20001.pdf"
        assert w.storage.get(order.id).status == "ready"

        driver = w.storage.drivers("Рефрижератор")[0]
        await w.press("manager", MANAGER, f"sh:driver:{order.id}")                 # этапы 14–15
        await w.press("manager", MANAGER, f"drv:{order.id}:{driver.id}")
        await w.press("manager", MANAGER, f"sh:go:{order.id}")
        assert "в пути" in w.cs.last(CLIENT) and driver.plate in w.cs.last(CLIENT)

        await w.press("manager", MANAGER, f"dd:{order.id}:ferry:2")                # этапы 17–18
        delayed = w.storage.get(order.id)
        assert delayed.status == "delayed" and delayed.eta == delayed.planned_eta + timedelta(days=2)
        assert "парома" in w.cs.last(CLIENT)

        await w.press("manager", MANAGER, f"sh:done:{order.id}")                   # этап 19
        assert f"acc:ok:{order.id}" in w.cs.buttons(CLIENT) and "температурный режим" in w.cs.last(CLIENT)

        await w.press("client", CLIENT, f"acc:ok:{order.id}")                      # этапы 20–22, 24–26
        closed = w.storage.get(order.id)
        assert closed.status == "closed" and closed.in_full == 1 and closed.on_time == 0  # срок переносили
        assert "с опозданием" in w.ms.to(MANAGER, SendDocument)[-1].caption
        assert w.cs.to(CLIENT, SendDocument)[-1].document.filename == "Акт приёмки LH-20001.pdf"
        assert w.ms.to(MANAGER, SendDocument)[-1].document.filename == "Акт приёмки LH-20001.pdf"

        await w.press("client", CLIENT, f"rate:{order.id}:5")
        assert w.storage.get(order.id).rating == 5 and "оценил" in w.ms.last(MANAGER)
        statuses = [h["status"] for h in w.storage.history(order.id)]
        assert statuses[:3] == ["new", "confirmed", "confirmed"] and statuses[-2:] == ["accepted", "closed"]
    run(scenario())


def test_clarification_and_claim_with_photo():
    async def scenario():
        w = World()
        await w.login_manager()
        order = await w.new_order()
        await w.press("manager", MANAGER, f"rev:back:{order.id}")                  # этапы 4–5
        await w.say("manager", MANAGER, "Укажите телефон склада получателя")
        assert "уточнение" in w.cs.last(CLIENT) and f"fix:recipient:{order.id}" in w.cs.buttons(CLIENT)
        await w.press("client", CLIENT, f"fix:recipient:{order.id}")
        await w.say("client", CLIENT, "Петров Пётр, склад, +7 914 000-11-22")
        await w.press("client", CLIENT, f"fix:send:{order.id}")
        assert w.storage.get(order.id).recipient.startswith("Петров")
        assert "уточнена" in w.ms.last(MANAGER)

        s = w.storage
        for status in ("confirmed", "paid", "picking", "ready"):
            s.set_status(order.id, status)
        s.assign_driver(order.id, s.drivers("Рефрижератор")[1].id)
        s.set_status(order.id, "in_transit")
        s.set_status(order.id, "delivered")

        await w.press("client", CLIENT, f"acc:claim:{order.id}")                   # этапы 20–21, 23
        await w.press("client", CLIENT, "ck:damage")
        await w.say("client", CLIENT, "Две коробки смяты при выгрузке, есть подтёки")
        await w.say("client", CLIENT, photo=[PhotoSize(file_id="ph1", file_unique_id="u1", width=10, height=10)])
        await w.press("client", CLIENT, "cl:send")
        assert s.get(order.id).status == "claim"
        assert "Претензия" in w.ms.last(MANAGER) and w.ms.to(MANAGER, SendPhoto)

        await w.press("manager", MANAGER, f"cd:compensation:{order.id}")
        await w.say("manager", MANAGER, "15 000")
        await w.say("manager", MANAGER, "Компенсируем стоимость двух повреждённых мест")
        claim = s.order_claim(order.id)
        assert claim.decision == "compensation" and claim.compensation == 15000 and claim.photos == ["ph1"]
        assert s.get(order.id).status == "closed" and "Компенсация" in w.cs.last(CLIENT)
    run(scenario())


def test_payment_reminder_and_auto_cancel():
    async def scenario():
        w = World()
        await w.login_manager()
        order = await w.new_order()
        await w.press("manager", MANAGER, f"rev:ok:{order.id}")
        reminded, cancelled = await check_payments(w.storage, w.client_bot, w.manager_bot,
                                                   now() + timedelta(days=2, hours=1))
        assert [o.id for o in reminded] == [order.id] and not cancelled and "Напоминаем" in w.cs.last(CLIENT)
        reminded, cancelled = await check_payments(w.storage, w.client_bot, w.manager_bot,
                                                   now() + timedelta(days=3, minutes=5))
        assert not reminded and [o.id for o in cancelled] == [order.id]
        assert w.storage.get(order.id).status == "cancelled"
        assert "отменён" in w.cs.last(CLIENT) and "отменён автоматически" in w.ms.last(MANAGER)
    run(scenario())


def test_access_control_and_menu_during_input():
    async def scenario():
        w = World()
        await w.login_manager()
        order = await w.new_order()
        await w.press("manager", OTHER, f"rev:ok:{order.id}")          # не вошёл в рабочее место
        assert w.storage.get(order.id).status == "new"
        await w.say("manager", OTHER, "wrong")
        assert "Войдите" in w.ms.last(OTHER)
        await w.press("client", OTHER, f"co:open:{order.id}")          # чужой заказ
        await w.press("client", OTHER, f"co:cancelyes:{order.id}")
        assert w.storage.get(order.id).status == "new"

        await w.say("client", CLIENT, kb.NEW_ORDER)                    # кнопка меню посреди ввода
        await w.press("client", CLIENT, "dst:Владивосток")
        await w.press("client", CLIENT, "cargo:Мебель")
        await w.say("client", CLIENT, "500")
        await w.say("client", CLIENT, "3")
        await w.say("client", CLIENT, kb.MY_ORDERS)                   # вместо адреса
        await w.say("client", CLIENT, "ул. Светланская, 1")          # уже не шаг «адрес»
        assert len(w.storage.list(client_id=CLIENT)) == 1
        await w.say("client", CLIENT, kb.SUPPORT)
        await w.say("client", CLIENT, kb.TARIFFS)                     # не уходит менеджеру вопросом
        assert "Тарифы и сроки" in w.cs.last(CLIENT)
        assert not any("Вопрос клиента" in (m.text or "") for m in w.ms.to(MANAGER, SendMessage))
    run(scenario())


def test_support_chat_with_manager():
    async def scenario():
        w = World()
        await w.login_manager()
        await w.new_order()
        await w.say("client", CLIENT, kb.SUPPORT)
        await w.say("client", CLIENT, "Можно ли перенести отгрузку LH-20001 на понедельник?")
        assert "Вопрос клиента" in w.ms.last(MANAGER) and "ООО «Амур-Трейд»" in w.ms.last(MANAGER)
        assert w.ms.buttons(MANAGER) == [f"rpl:{CLIENT}"]
        await w.press("manager", MANAGER, f"rpl:{CLIENT}")
        await w.say("manager", MANAGER, "Да, перенесём на понедельник, счёт остаётся прежним.")
        assert "Ответ менеджера" in w.cs.last(CLIENT) and "понедельник" in w.cs.last(CLIENT)
    run(scenario())


def test_manager_summary_and_csv_export():
    async def scenario():
        w = World()
        await w.login_manager()
        await w.new_order()
        await w.say("manager", MANAGER, kb.SUMMARY)
        assert "Всего заказов: <b>1</b>" in w.ms.last(MANAGER)
        await w.press("manager", MANAGER, "sum:csv")
        csv = w.ms.to(MANAGER, SendDocument)[-1].document.data.decode("utf-8-sig")
        assert csv.splitlines()[0].startswith("Заказ;Создан;Клиент") and "LH-20001" in csv
    run(scenario())
