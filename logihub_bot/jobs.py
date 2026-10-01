"""Фоновые задачи: контроль срока оплаты (шлюз BPMN 9 «Оплата поступила в течение 3 дней?»)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from . import keyboards as kb
from . import texts
from .config import PAYMENT_DAYS
from .notify import notify
from .storage import Order, Storage, TransitionError

log = logging.getLogger(__name__)


async def check_payments(storage: Storage, client_bot: Bot, manager_bot: Bot,
                         moment: datetime | None = None) -> tuple[list[Order], list[Order]]:
    """Напомнить об оплате за сутки до срока и отменить неоплаченные заказы после срока."""
    reminded, cancelled = [], []
    for order in storage.payments_to_remind(moment):
        storage.mark_reminded(order.id)
        await notify(client_bot, [order.client_id], texts.payment_reminder(order), kb.payment(order))
        reminded.append(order)
    for order in storage.overdue_payments(moment):
        try:
            order = storage.set_status(order.id, "cancelled", f"Оплата не поступила в течение {PAYMENT_DAYS} дней – "
                                                              "заказ отменён автоматически")
        except TransitionError:
            continue
        await notify(client_bot, [order.client_id],
                     f"✖️ Заказ <b>{order.number}</b> отменён: оплата не поступила в течение {PAYMENT_DAYS} дней.\n"
                     "Если груз всё ещё нужно отправить – оформите новую заявку.")
        await notify(manager_bot, storage.managers(),
                     f"✖️ Заказ <b>{order.number}</b> отменён автоматически – оплата не поступила в срок "
                     f"({texts.rub(order.total)}).")
        cancelled.append(order)
    return reminded, cancelled


async def payment_watcher(storage: Storage, client_bot: Bot, manager_bot: Bot, interval: int = 600) -> None:
    while True:
        try:
            reminded, cancelled = await check_payments(storage, client_bot, manager_bot)
            if reminded or cancelled:
                log.info("Контроль оплаты: напоминаний %d, отмен %d", len(reminded), len(cancelled))
        except Exception:
            log.exception("Ошибка контроля оплаты")
        await asyncio.sleep(interval)
