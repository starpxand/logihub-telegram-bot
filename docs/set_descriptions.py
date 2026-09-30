"""Описания ботов в Telegram (показываются до первого /start). Запуск: python docs/set_descriptions.py"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

env = dict(l.split("=", 1) for l in Path(".env").read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
DATA = {
    env["BOT_TOKEN"].strip(): {
        "setMyDescription": {"description": "Бот платформы ЛогиХаб: оформите заявку на перевозку с расчётом стоимости "
                                            "и срока, следите за статусом заказа, получайте уведомления о задержках "
                                            "и примите груз – подпишите акт или оформите претензию."},
        "setMyShortDescription": {"short_description": "ЛогиХаб: заявка на перевозку, статус заказа и приёмка груза"},
    },
    env["MANAGER_BOT_TOKEN"].strip(): {
        "setMyDescription": {"description": "Рабочее место менеджера платформы ЛогиХаб: сюда приходят новые заявки "
                                            "клиентов и претензии. Проверка заявок, отгрузка, задержки, доставка, "
                                            "закрытие заказов и KPI из аналитического дашборда. Вход по коду доступа."},
        "setMyShortDescription": {"short_description": "ЛогиХаб · бот менеджера: заявки, заказы в работе, KPI"},
    },
}
for token, calls in DATA.items():
    for method, params in calls.items():
        body = urllib.parse.urlencode(params).encode("utf-8")
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=body, timeout=30) as r:
            print(token.split(":")[0], method, json.load(r)["ok"])
