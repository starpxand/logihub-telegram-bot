"""Запуск: python -m logihub_bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .analytics import Analytics
from .config import load_settings
from .handlers import build_router
from .storage import Storage


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    storage = Storage(settings.db_path)
    analytics = Analytics(settings.orders_csv)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(storage, analytics, settings))
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="new", description="Новая заявка на перевозку"),
        BotCommand(command="status", description="Статус заказа"),
        BotCommand(command="kpi", description="KPI доставки"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="cancel", description="Отменить ввод"),
    ])
    me = await bot.get_me()
    logging.info("Бот @%s запущен", me.username)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
