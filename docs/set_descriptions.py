"""Описания ботов в Telegram (показываются до первого /start). Запуск: python docs/set_descriptions.py"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

env = dict(l.split("=", 1) for l in Path(".env").read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
DATA = {
    env["BOT_TOKEN"].strip(): {
        "setMyDescription": {"description": "ЛогиХаб – грузоперевозки со склада в Комсомольске-на-Амуре по Дальнему "
                                            "Востоку. Оформите заявку и сразу узнайте стоимость и срок, получите "
                                            "договор-счёт, следите за грузом от склада до получателя, примите груз "
                                            "или оформите претензию. Заявки – круглосуточно."},
        "setMyShortDescription": {"short_description": "ЛогиХаб: перевозки по ДВ – заявка, счёт, трекинг груза, приёмка"},
    },
    env["MANAGER_BOT_TOKEN"].strip(): {
        "setMyDescription": {"description": "Рабочее место сотрудников ЛогиХаб: проверка заявок и договор-счёт, "
                                            "контроль оплаты, комплектация и ТТН, водители и рейсы, отклонения от "
                                            "графика, претензии, сводка OTIF и KPI дашборда. Вход по коду доступа."},
        "setMyShortDescription": {"short_description": "ЛогиХаб · сотрудники: заявки, оплаты, склад, рейсы, претензии"},
    },
}
for token, calls in DATA.items():
    for method, params in calls.items():
        body = urllib.parse.urlencode(params).encode("utf-8")
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=body, timeout=30) as r:
            print(token.split(":")[0], method, json.load(r)["ok"])
