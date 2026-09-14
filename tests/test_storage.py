from datetime import date

import pytest

from logihub_bot.pricing import quote
from logihub_bot.storage import Storage, TransitionError, parse_number


@pytest.fixture
def db():
    s = Storage()
    s.upsert_user(1, "Клиент", "client")
    s.upsert_user(2, "Менеджер", "manager")
    return s


def new_order(db):
    return db.create_order(1, quote("Хабаровск", "Продукты питания", 3200, date(2026, 9, 18)))


def test_full_bpmn_happy_path(db):
    o = new_order(db)
    assert o.number == "LH-20001" and o.status == "new"
    for status in ("confirmed", "in_transit", "delayed", "delivered", "accepted", "closed"):
        o = db.set_status(o.id, status, eta=date(2026, 9, 20) if status == "delayed" else None)
    assert o.status == "closed"
    assert o.eta == date(2026, 9, 20)
    assert [h["status"] for h in db.history(o.id)] == ["new", "confirmed", "in_transit", "delayed", "delivered",
                                                       "accepted", "closed"]


def test_clarification_loop(db):
    o = new_order(db)
    db.set_status(o.id, "clarify", "нет телефона получателя")
    assert db.set_status(o.id, "new").status == "new"


def test_claim_branch(db):
    o = new_order(db)
    for status in ("confirmed", "in_transit", "delivered", "claim", "closed"):
        o = db.set_status(o.id, status)
    assert o.status == "closed"


def test_invalid_transition_rejected(db):
    o = new_order(db)
    with pytest.raises(TransitionError):
        db.set_status(o.id, "delivered")


def test_roles_and_lists(db):
    new_order(db)
    assert db.managers() == [2]
    assert db.role(1) == "client"
    assert len(db.list(status="new", client_id=1)) == 1


@pytest.mark.parametrize("raw, expected", [("LH-20001", 1), ("lh20015", 15), ("20003", 3), ("abc", None), ("123", None)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected
