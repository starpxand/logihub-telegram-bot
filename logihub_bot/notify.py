"""Отправка сообщений и документов между ботами.

Уведомления одной роли уходят через «её» бот: клиенту пишет клиентский бот, менеджеру – бот менеджера.
Пользователь мог не запускать бота или заблокировать его, поэтому ошибки отправки только логируются.
"""
from __future__ import annotations

import logging
from typing import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


async def notify(bot: Bot, chat_ids: Iterable[int], text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    for chat_id in dict.fromkeys(chat_ids):
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
        except Exception as exc:
            log.warning("notify %s failed: %s", chat_id, exc)


async def send_file(bot: Bot, chat_ids: Iterable[int], data: bytes, filename: str, caption: str | None = None,
                    markup: InlineKeyboardMarkup | None = None) -> None:
    for chat_id in dict.fromkeys(chat_ids):
        try:
            await bot.send_document(chat_id, BufferedInputFile(data, filename), caption=caption, reply_markup=markup)
        except Exception as exc:
            log.warning("send_file %s failed: %s", chat_id, exc)


async def send_photos(bot: Bot, chat_ids: Iterable[int], photos: list[bytes], caption: str) -> None:
    for chat_id in dict.fromkeys(chat_ids):
        for n, data in enumerate(photos, 1):
            try:
                await bot.send_photo(chat_id, BufferedInputFile(data, f"photo{n}.jpg"),
                                     caption=caption if n == 1 else None)
            except Exception as exc:
                log.warning("send_photo %s failed: %s", chat_id, exc)


async def edit_or_send(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Обновить карточку на месте; сообщение с документом или устаревшее – ответить новым."""
    if message.text is not None:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    else:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=markup)
