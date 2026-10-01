from datetime import date, timedelta

import pytest

from logihub_bot.config import now
from logihub_bot.pricing import quote
from logihub_bot.storage import Storage, TransitionError, parse_number

SHIP = date(2026, 10, 5)


@pytest.fixture
def db():
    s = Storage()
    s.upsert_user(1, "Клиент", "client")
    s.upsert_user(2, "Менеджер", "manager")
    return s


def new_order(db, declared_value=0):
    return db.create_order(1, quote("Хабаровск", "Продукты питания", 3200, SHIP, declared_value=declared_value),
                           places=12, address="ул. Промышленная, 12", recipient="Иванов И., +7 914 000-00-00")


def to_delivered(db, order, delay_days=0):
    for status in ("confirmed", "paid", "picking", "ready"):
        order = db.set_status(order.id, status)
    order = db.assign_driver(order.id, db.drivers("Рефрижератор")[0].id)
    order = db.set_status(order.id, "in_transit")
    if delay_days:
        order = db.set_status(order.id, "delayed", "пробка", eta=order.eta + timedelta(days=delay_days))
    return db.set_status(order.id, "delivered")


def test_full_bpmn_happy_path(db):
    o = new_order(db)
    assert o.number == "LH-20001" and o.status == "new" and o.places == 12 and o.temperature == "+2…+6 °C"
    o = to_delivered(db, o)
    o = db.set_status(o.id, "accepted")
    o = db.set_status(o.id, "closed")
    assert o.status == "closed" and o.on_time == 1 and o.in_full == 1
    statuses = [h["status"] for h in db.history(o.id)]
    assert statuses == ["new", "confirmed", "paid", "picking", "ready", "ready", "in_transit", "delivered",
                        "accepted", "closed"]


def test_confirm_sets_payment_deadline(db):
    o = db.set_status(new_order(db).id, "confirmed")
    assert timedelta(days=2, hours=23) < o.pay_deadline - now() <= timedelta(days=3)


def test_clarification_loop_and_edit(db):
    o = new_order(db)
    db.set_status(o.id, "clarify", "нет телефона получателя")
    o = db.update_order(o.id, recipient="Петров П., +7 914 111-11-11", places=14)
    assert o.recipient.startswith("Петров") and o.places == 14
    with pytest.raises(ValueError):
        db.update_order(o.id, price=1)
    assert db.set_status(o.id, "new").status == "new"


def test_picking_loop_in_full(db):
    o = db.set_status(db.set_status(new_order(db).id, "confirmed").id, "paid")
    for _ in range(3):  # «Докомплектовать груз» – цикл
        o = db.set_status(o.id, "picking")
    assert db.set_status(o.id, "ready").status == "ready"


def test_trip_requires_driver_of_right_transport(db):
    o = new_order(db)
    for status in ("confirmed", "paid", "picking", "ready"):
        o = db.set_status(o.id, status)
    with pytest.raises(TransitionError):
        db.set_status(o.id, "in_transit")
    with pytest.raises(TransitionError):
        db.assign_driver(o.id, db.drivers("Газель")[0].id)
    o = db.assign_driver(o.id, db.drivers("Рефрижератор")[0].id)
    assert db.set_status(o.id, "in_transit").driver_id == o.driver_id


def test_delay_moves_eta_and_breaks_on_time(db):
    o = to_delivered(db, new_order(db), delay_days=2)
    assert o.eta == o.planned_eta + timedelta(days=2)
    o = db.set_status(db.set_status(o.id, "accepted").id, "closed")
    assert o.on_time == 0 and o.in_full == 1
    assert db.stats()["on_time"] == 0 and db.stats()["otif"] == 0


def test_shortage_claim_breaks_in_full(db):
    o = to_delivered(db, new_order(db))
    claim = db.add_claim(o.id, "shortage", "Не хватает двух паллет", ["file1"])
    db.set_status(o.id, "claim")
    claim = db.decide_claim(claim.id, "redelivery", "Довезём 07.10", None)
    o = db.set_status(o.id, "closed")
    assert claim.photos == ["file1"] and claim.decision == "redelivery"
    assert o.in_full == 0


def test_rejected_claim_keeps_in_full(db):
    o = to_delivered(db, new_order(db))
    claim = db.add_claim(o.id, "shortage", "Кажется, не хватает места")
    db.set_status(o.id, "claim")
    db.decide_claim(claim.id, "rejected", "Пересчёт по ТТН – все 12 мест на месте")
    assert db.set_status(o.id, "closed").in_full == 1


def test_payment_timeout_queries(db):
    o = db.set_status(new_order(db).id, "confirmed")
    assert db.payments_to_remind(now()) == []
    assert [x.id for x in db.payments_to_remind(now() + timedelta(days=2, hours=1))] == [o.id]
    db.mark_reminded(o.id)
    assert db.payments_to_remind(now() + timedelta(days=2, hours=1)) == []
    assert [x.id for x in db.overdue_payments(now() + timedelta(days=3, minutes=1))] == [o.id]


def test_cancel_only_before_payment(db):
    o = db.set_status(new_order(db).id, "confirmed")
    assert db.set_status(o.id, "cancelled").status == "cancelled"
    o = db.set_status(db.set_status(new_order(db).id, "confirmed").id, "paid")
    with pytest.raises(TransitionError):
        db.set_status(o.id, "cancelled")


def test_invalid_transition_rejected(db):
    o = new_order(db)
    with pytest.raises(TransitionError):
        db.set_status(o.id, "delivered")


def test_stats_otif_rating_revenue(db):
    o = to_delivered(db, new_order(db, declared_value=900_000))
    db.set_status(db.set_status(o.id, "accepted").id, "closed")
    db.set_rating(o.id, 5)
    new_order(db)
    s = db.stats()
    assert s["total"] == 2 and s["closed"] == 1 and s["otif"] == 100 and s["rating"] == 5
    assert s["revenue"] == o.price + 2700
    assert db.export_rows()[0]["driver"] == "Сергей Никитин"


def test_contacts_and_roles(db):
    db.set_contact(1, company="ООО «Амур-Трейд»", phone="+79140000000")
    u = db.user(1)
    assert u.company == "ООО «Амур-Трейд»" and u.phone == "+79140000000"
    assert db.managers() == [2] and db.role(1) == "client"


def test_migration_from_old_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (tg_id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL, destination TEXT NOT NULL,
            region TEXT NOT NULL, cargo TEXT NOT NULL, weight_kg REAL NOT NULL, transport TEXT NOT NULL,
            distance_km INTEGER NOT NULL, price REAL NOT NULL, ship_date TEXT NOT NULL, eta TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new', comment TEXT);
        INSERT INTO users VALUES (1, 'Клиент', 'client');
        INSERT INTO orders (client_id, destination, region, cargo, weight_kg, transport, distance_km, price, ship_date, eta)
            VALUES (1, 'Хабаровск', 'Хабаровский край', 'Мебель', 500, 'Газель', 400, 20000, '2026-10-05', '2026-10-06');
    """)
    old.close()
    o = Storage(path).get(1)
    assert o.places == 1 and o.planned_eta == date(2026, 10, 6) and o.insurance == 0


@pytest.mark.parametrize("raw, expected", [("LH-20001", 1), ("lh20015", 15), ("20003", 3), ("abc", None), ("123", None)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected
