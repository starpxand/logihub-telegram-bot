"""Документы процесса в PDF: договор-счёт (этап 7), ТТН (этап 13), акт приёмки (этап 22)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from io import BytesIO

import matplotlib
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import COMPANY, PAYMENT_DAYS, now
from .pricing import HUB
from .storage import Driver, Order, Storage, User

_FONT_DIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))

NAVY = colors.HexColor("#0b1b3f")
ORANGE = colors.HexColor("#ff8a3d")
GREY = colors.HexColor("#5b6477")

H1 = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=15, leading=19, textColor=NAVY, spaceAfter=4)
SUB = ParagraphStyle("sub", fontName="DejaVu", fontSize=9, leading=12, textColor=GREY)
TXT = ParagraphStyle("txt", fontName="DejaVu", fontSize=9.5, leading=13)
SMALL = ParagraphStyle("small", fontName="DejaVu", fontSize=8, leading=10, textColor=GREY)


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _header(title: str, number: str, issued: datetime) -> list:
    brand = Table([[Paragraph(f"<b>{COMPANY['name']}</b>", ParagraphStyle("b", fontName="DejaVu-Bold",
                                                                             fontSize=11, textColor=colors.white)),
                    Paragraph(COMPANY["slogan"], ParagraphStyle("s", fontName="DejaVu", fontSize=8.5,
                                                                textColor=colors.HexColor("#ffb547"), alignment=2))]],
                  colWidths=[85 * mm, 95 * mm])
    brand.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                               ("LINEBELOW", (0, 0), (-1, -1), 2.5, ORANGE)]))
    return [brand, Spacer(1, 8 * mm), Paragraph(f"{title} № {number}", H1),
            Paragraph(f"от {issued:%d.%m.%Y} · {COMPANY['hub']}", SUB), Spacer(1, 5 * mm)]


def _grid(rows, widths, head=True) -> Table:
    data = [[Paragraph(str(c), TXT) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d1e0")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fb")))
    t.setStyle(TableStyle(style))
    return t


def _parties(order: Order, client: User | None) -> Table:
    who = (client.company or client.name) if client else "—"
    phone = client.phone if client and client.phone else "—"
    return _grid([["Исполнитель", f"{COMPANY['name']}, ИНН {COMPANY['inn']}, КПП {COMPANY['kpp']}"],
                  ["Заказчик", f"{who}, тел. {phone}"],
                  ["Грузополучатель", order.recipient or "—"],
                  ["Адрес доставки", f"{order.destination}, {order.address or '—'}"]], [42, 138], head=False)


def _cargo(order: Order) -> str:
    temp = f", t° {order.temperature}" if order.temperature else ""
    weight = f"{order.weight_kg:,.0f}".replace(",", " ")
    return f"{order.cargo}, {weight} кг, мест: {order.places}{temp}"


def _build(story: list) -> bytes:
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title="ЛогиХаб", author=COMPANY["name"]).build(story)
    return buf.getvalue()


def invoice_pdf(order: Order, client: User | None, issued: datetime | None = None) -> bytes:
    """Договор-счёт на перевозку (этап BPMN 7)."""
    issued = issued or now()
    deadline = order.pay_deadline or (issued + timedelta(days=PAYMENT_DAYS))
    rows = [["№", "Услуга", "Кол-во", "Сумма"],
            ["1", f"Перевозка груза: {HUB} → {order.destination} ({order.distance_km} км), {order.transport}. "
                  f"Груз: {_cargo(order)}", "1", money(order.price)]]
    if order.insurance:
        rows.append(["2", f"Страхование груза, объявленная стоимость {money(order.declared_value)}", "1",
                     money(order.insurance)])
    story = _header("Договор-счёт", order.number, issued) + [
        _parties(order, client), Spacer(1, 5 * mm),
        _grid(rows, [10, 118, 18, 34]), Spacer(1, 3 * mm),
        Paragraph(f"<b>Итого к оплате: {money(order.total)}</b> (НДС не облагается – учебный проект)", TXT),
        Spacer(1, 4 * mm),
        Paragraph(f"Отгрузка: <b>{order.ship_date:%d.%m.%Y}</b>. Плановая доставка: <b>{order.eta:%d.%m.%Y}</b>.", TXT),
        Paragraph(f"Счёт действителен до <b>{deadline:%d.%m.%Y %H:%M}</b> (хабаровское время). "
                  f"Если оплата не поступит в течение {PAYMENT_DAYS} дней, заказ отменяется автоматически.", TXT),
        Spacer(1, 4 * mm),
        Paragraph(f"Реквизиты: р/с {COMPANY['account']} в {COMPANY['bank']}. Назначение платежа: "
                  f"«Оплата по договору-счёту {order.number}».", TXT),
        Spacer(1, 10 * mm),
        Paragraph("Оплата счёта означает согласие Заказчика с условиями перевозки. "
                  "Документ сформирован автоматически в Telegram-боте ЛогиХаб.", SMALL),
    ]
    return _build(story)


def ttn_pdf(order: Order, client: User | None, driver: Driver | None, issued: datetime | None = None) -> bytes:
    """Товарно-транспортная накладная (этап BPMN 13–14)."""
    story = _header("Товарно-транспортная накладная", order.number, issued or now()) + [
        _parties(order, client), Spacer(1, 5 * mm),
        _grid([["Груз", "Мест", "Вес, кг", "Условия перевозки"],
               [order.cargo, str(order.places), f"{order.weight_kg:,.0f}".replace(",", " "),
                order.temperature and f"температурный режим {order.temperature}" or "без температурного режима"]],
              [60, 20, 30, 70]),
        Spacer(1, 5 * mm),
        _grid([["Пункт погрузки", HUB], ["Пункт разгрузки", f"{order.destination}, {order.address or '—'}"],
               ["Транспорт", f"{order.transport}" + (f": {driver.vehicle}, госномер {driver.plate}" if driver else "")],
               ["Водитель", driver.name if driver else "будет назначен"],
               ["Дата отгрузки / плановая доставка", f"{order.ship_date:%d.%m.%Y} / {order.eta:%d.%m.%Y}"]],
              [60, 120], head=False),
        Spacer(1, 12 * mm),
        _grid([["Груз сдал (склад)", "Груз принял (водитель)", "Груз получил (грузополучатель)"],
               ["\n\n________________", "\n\n________________", "\n\n________________"]], [60, 60, 60]),
    ]
    return _build(story)


def act_pdf(order: Order, client: User | None, issued: datetime | None = None) -> bytes:
    """Акт приёмки груза без замечаний (этап BPMN 22)."""
    issued = issued or now()
    story = _header("Акт приёмки груза", order.number, issued) + [
        _parties(order, client), Spacer(1, 5 * mm),
        Paragraph(f"Груз <b>{_cargo(order)}</b> доставлен по маршруту {HUB} → {order.destination} "
                  f"и принят грузополучателем <b>{issued:%d.%m.%Y}</b>.", TXT),
        Spacer(1, 3 * mm),
        Paragraph("Количество мест, целостность упаковки и условия перевозки соответствуют заявке. "
                  "Претензий к качеству перевозки Заказчик не имеет.", TXT),
        Spacer(1, 3 * mm),
        Paragraph(f"Стоимость услуг по договору-счёту {order.number}: <b>{money(order.total)}</b>.", TXT),
        Spacer(1, 12 * mm),
        Paragraph("Акт подписан Заказчиком в Telegram-боте ЛогиХаб (простая электронная подпись).", SMALL),
    ]
    return _build(story)


TITLES = {"inv": "Договор-счёт", "ttn": "ТТН", "act": "Акт приёмки"}
_ISSUED_ON = {"inv": "confirmed", "ttn": "ready", "act": "accepted"}


def render(storage: Storage, kind: str, order: Order) -> tuple[bytes, str]:
    """Документ по заказу; дата документа – момент соответствующего этапа из истории заказа."""
    if kind not in TITLES:
        raise ValueError(f"Неизвестный документ: {kind}")
    stamp = [h["created_at"] for h in storage.history(order.id) if h["status"] == _ISSUED_ON[kind]]
    issued = datetime.fromisoformat(stamp[-1]) if stamp else now()
    client = storage.user(order.client_id)
    if kind == "inv":
        data = invoice_pdf(order, client, issued)
    elif kind == "ttn":
        data = ttn_pdf(order, client, storage.driver(order.driver_id), issued)
    elif kind == "act":
        data = act_pdf(order, client, issued)
    else:
        raise ValueError(kind)
    return data, f"{TITLES[kind]} {order.number}.pdf"
