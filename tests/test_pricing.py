from datetime import date

import pytest

from logihub_bot.pricing import PricingError, choose_transport, quote


def test_quote_khabarovsk_food_uses_reefer():
    q = quote("Хабаровск", "Продукты питания", 3200, date(2026, 9, 18))
    assert q.transport == "Рефрижератор"
    assert q.distance_km == 400
    assert q.eta > q.ship_date
    assert 40000 < q.price < 60000


@pytest.mark.parametrize("cargo, weight, expected", [
    ("Электроника", 800, "Газель"), ("Мебель", 5000, "Фура"),
    ("Стройматериалы", 22000, "Контейнер (ж/д)"), ("Медикаменты", 500, "Рефрижератор"),
])
def test_choose_transport(cargo, weight, expected):
    assert choose_transport(cargo, weight) == expected


@pytest.mark.parametrize("args", [("Москва", "Мебель", 100), ("Хабаровск", "Уголь", 100),
                                  ("Хабаровск", "Мебель", 0), ("Хабаровск", "Мебель", 30000)])
def test_quote_rejects_invalid(args):
    with pytest.raises(PricingError):
        quote(*args, date(2026, 9, 18))


def test_longer_route_costs_more():
    d = date(2026, 9, 18)
    assert quote("Владивосток", "Мебель", 2000, d).price > quote("Хабаровск", "Мебель", 2000, d).price


def test_insurance_and_total():
    d = date(2026, 9, 18)
    q = quote("Хабаровск", "Продукты питания", 3200, d, declared_value=900_000)
    assert q.insurance == 2700 and q.total == q.price + 2700
    assert q.temperature == "+2…+6 °C"
    assert quote("Хабаровск", "Мебель", 100, d, declared_value=10_000).insurance == 300  # минимальная премия
    assert quote("Хабаровск", "Мебель", 100, d).insurance == 0


def test_fee_breakdown_adds_up():
    q = quote("Владивосток", "Электроника", 5000, date(2026, 9, 18))
    assert q.weight_fee == 4000 and q.base_fee == 3000
    assert abs(q.distance_fee + q.weight_fee + q.base_fee - q.price) <= 10
