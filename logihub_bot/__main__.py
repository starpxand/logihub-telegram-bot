"""Запуск двух ботов (клиентского и менеджерского): python -m logihub_bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .analytics import Analytics
from .config import load_settings
from .handlers import build_client_router, build_manager_router
from .storage import Storage

CLIENT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="new", description="Новая заявка на перевозку"),
    BotCommand(command="status", description="Статус заказа"),
    BotCommand(command="help", description="Помощь"),
    BotCommand(command="cancel", description="Отменить ввод"),
]
MANAGER_COMMANDS = [
    BotCommand(command="start", description="Меню менеджера / вход"),
    BotCommand(command="status", description="Карточка и история заказа"),
    BotCommand(command="kpi", description="KPI доставки"),
    BotCommand(command="help", description="Помощь"),
    BotCommand(command="logout", description="Выйти из рабочего места"),
    BotCommand(command="cancel", description="Отменить ввод"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    storage = Storage(settings.db_path)
    analytics = Analytics(settings.orders_csv)
    props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    client_bot = Bot(settings.bot_token, default=props)
    manager_bot = Bot(settings.manager_bot_token, default=props)

    client_me, manager_me = await client_bot.get_me(), await manager_bot.get_me()
    client_dp, manager_dp = Dispatcher(), Dispatcher()
    client_dp.include_router(build_client_router(storage, settings, manager_bot, manager_me.username))
    manager_dp.include_router(build_manager_router(storage, analytics, settings, client_bot))
    await client_bot.set_my_commands(CLIENT_COMMANDS)
    await manager_bot.set_my_commands(MANAGER_COMMANDS)
    logging.info("Боты запущены: клиентский @%s, менеджерский @%s", client_me.username, manager_me.username)
    try:
        await asyncio.gather(
            client_dp.start_polling(client_bot, handle_signals=False),
            manager_dp.start_polling(manager_bot, handle_signals=False),
        )
    finally:
        await client_bot.session.close()
        await manager_bot.session.close()
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
