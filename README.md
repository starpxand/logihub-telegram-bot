<div align="center">

# 🤖 ЛогиХаб · Telegram-бот

**Автоматизация процесса управления логистикой: заявки, проверка, трекинг, приёмка и KPI в Telegram**

[![CI](https://github.com/starpxand/logihub-telegram-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/starpxand/logihub-telegram-bot/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3-2CA5E0?logo=telegram&logoColor=white)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Открыть бота @logihub_logistics_bot](https://t.me/logihub_logistics_bot) ·
[Wiki продукта](https://starpxand.github.io/logihub-wiki/) ·
[Дашборд](https://github.com/starpxand/logihub-dashboard) ·
[BPMN-модель](https://starpxand.github.io/logihub-wiki/process/)

</div>

## О проекте

Бот – канал взаимодействия с платформой **«ЛогиХаб»** (вариант 15 «Процесс управления
логистикой»). Он автоматизирует этапы BPMN-модели процесса, которые выполняют клиент и
менеджер, и встраивает аналитический дашборд прямо в чат.

| Этапы BPMN | Что автоматизирует бот | Роль |
|---|---|---|
| 1–2, 6 | Оформление заявки пошагово, автоматический расчёт стоимости, транспорта и срока доставки | Клиент |
| 3–5 | Проверка заявки менеджером: «Заявка корректна» или возврат на уточнение с уведомлением клиента | Менеджер |
| 7, 15 | Уведомление о подтверждении и отгрузке | Клиент |
| 16–18 | Фиксация отклонения от графика, перенос даты доставки и уведомление клиента | Менеджер → клиент |
| 19–23 | Доставка, приёмка груза: подписание акта или претензия | Клиент |
| 24–26 | Урегулирование претензии, закрытие заказа | Менеджер |
| KPI | OTIF, выручка, прибыль и график OTIF из модуля данных дашборда | Менеджер |

## Возможности

- **Роли**: клиент (по умолчанию) и менеджер (`/manager <код>`).
- **Заявка за 4 шага**: город → категория груза → вес → дата; расчёт стоимости и ETA по тарифной модели платформы.
- **Статусы заказа** соответствуют потокам BPMN; недопустимые переходы блокируются.
- **Уведомления** клиенту и менеджерам на каждом этапе.
- **История заказа** с временем каждого события.
- **KPI из дашборда**: бот использует пакет [`logihub-dashboard`](https://github.com/starpxand/logihub-dashboard), поэтому показатели в чате и в дашборде совпадают.

## Установка и запуск

1. Создайте бота у [@BotFather](https://t.me/BotFather) и получите токен.
2. Установите зависимости и настройте окружение:

```bash
git clone https://github.com/starpxand/logihub-telegram-bot.git
cd logihub-telegram-bot
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # укажите BOT_TOKEN
python -m logihub_bot
```

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | токен бота от @BotFather | – (обязательно) |
| `MANAGER_CODE` | код для входа в режим менеджера | `logihub-manager` |
| `DB_PATH` | файл базы SQLite | `logihub_bot.sqlite3` |
| `ORDERS_CSV` | выгрузка заказов для KPI | `data/logistics_orders.csv` |
| `DASHBOARD_URL` | адрес веб-дашборда | `http://127.0.0.1:8050` |

## Как пользоваться

**Клиент:** `/start` → «📦 Новая заявка» → выбор города и груза, ввод веса и даты → «✅ Отправить заявку».
Статус – «🔎 Статус заказа» и номер вида `LH-20001`; после доставки – «✅ Приёмка груза».

**Менеджер:** `/manager logihub-manager` → «📋 Заявки на проверку» (подтвердить или вернуть),
«🚚 Заказы в работе» (отгрузка, задержка, доставка), «📊 KPI и дашборд» (месяц / квартал / год).

| Команда | Действие |
|---|---|
| `/start` | главное меню |
| `/new` | новая заявка |
| `/status LH-20001` | статус и история заказа |
| `/kpi` | KPI доставки с графиком |
| `/manager <код>`, `/client` | переключение роли |
| `/cancel` | отменить ввод |

## Тестирование

```bash
pip install pytest
pytest -v
```

Тесты покрывают тарифную модель, переходы статусов по BPMN (основной путь, цикл уточнения,
ветка претензии, запрет недопустимых переходов) и интеграцию с дашбордом. Протокол ручного
тестирования – [`docs/TESTING.md`](docs/TESTING.md).

## Структура

```text
logihub-telegram-bot/
├── logihub_bot/
│   ├── __main__.py     # запуск polling
│   ├── config.py       # настройки из .env
│   ├── pricing.py      # расчёт стоимости и срока (этап BPMN 6)
│   ├── storage.py      # SQLite: пользователи, заказы, история статусов
│   ├── analytics.py    # KPI и графики через logihub-dashboard
│   ├── handlers.py     # сценарии клиента и менеджера
│   ├── keyboards.py    # клавиатуры
│   └── texts.py        # тексты сообщений
├── data/               # выгрузка заказов для KPI
├── tests/              # pytest
└── docs/               # документация и протокол тестирования
```

## Ветки

| Ветка | Назначение |
|---|---|
| `main` | стабильные релизы |
| `development` | интеграция и тестирование |
| `feature/*` | отдельные возможности |

## Автор и контакты

**Попов А.С.**, группа 5ИТб-2, ФГБОУ ВО «КнАГУ»

- GitHub: [@starpxand](https://github.com/starpxand)
- Бот: [@logihub_logistics_bot](https://t.me/logihub_logistics_bot)
- Связанные проекты: [Wiki](https://github.com/starpxand/logihub-wiki) · [Дашборд](https://github.com/starpxand/logihub-dashboard) · [UX/UI-макет](https://github.com/starpxand/logihub-design)

Лицензия – [MIT](LICENSE).
