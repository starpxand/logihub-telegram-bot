from datetime import date

import pytest

from logihub_bot import documents
from logihub_bot.pricing import quote
from logihub_bot.storage import Storage


@pytest.fixture
def order_db():
    s = Storage()
    s.upsert_user(1, "Андрей", "client")
    s.set_contact(1, "ООО «Амур-Трейд»", "+79140000000")
    o = s.create_order(1, quote("Хабаровск", "Продукты питания", 3200, date(2026, 10, 5), declared_value=900_000),
                       places=12, address="ул. Промышленная, 12", recipient="Иванов И., +7 914 000-00-00")
    for status in ("confirmed", "paid", "picking", "ready"):
        o = s.set_status(o.id, status)
    s.assign_driver(o.id, s.drivers("Рефрижератор")[0].id)
    for status in ("in_transit", "delivered", "accepted"):
        o = s.set_status(o.id, status)
    return s, o


@pytest.mark.parametrize("kind, name", [("inv", "Договор-счёт LH-20001.pdf"), ("ttn", "ТТН LH-20001.pdf"),
                                        ("act", "Акт приёмки LH-20001.pdf")])
def test_render_pdf(order_db, kind, name):
    storage, order = order_db
    data, filename = documents.render(storage, kind, order)
    assert data.startswith(b"%PDF") and len(data) > 5000
    assert filename == name


def test_unknown_document(order_db):
    storage, order = order_db
    with pytest.raises(ValueError):
        documents.render(storage, "xxx", order)
