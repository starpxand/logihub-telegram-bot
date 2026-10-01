"""Расчёт стоимости и срока доставки (этап BPMN 6 «Рассчитать стоимость и срок доставки»).

Тарифная модель совпадает с моделью, по которой сформирована выгрузка заказов дашборда.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

HUB = "Комсомольск-на-Амуре"

DESTINATIONS = {  # город: (регион, расстояние от хаба, км)
    "Хабаровск": ("Хабаровский край", 400),
    "Биробиджан": ("Еврейская АО", 560),
    "Владивосток": ("Приморский край", 1050),
    "Благовещенск": ("Амурская область", 1350),
    "Южно-Сахалинск": ("Сахалинская область", 1600),
}

CARGO = {  # категория: коэффициент тарифа
    "Электроника": 1.25,
    "Продукты питания": 1.10,
    "Стройматериалы": 0.95,
    "Одежда и обувь": 1.05,
    "Мебель": 1.10,
    "Медикаменты": 1.30,
}

TEMPERATURE = {  # грузы с температурным режимом
    "Продукты питания": "+2…+6 °C",
    "Медикаменты": "+2…+8 °C",
}

TRANSPORT = {  # тип: (грузоподъёмность, кг; скорость, км/ч; тариф, руб/км)
    "Газель": (1500, 60, 32),
    "Фура": (20000, 55, 75),
    "Рефрижератор": (12000, 52, 88),
    "Контейнер (ж/д)": (24000, 40, 55),
}

MAX_WEIGHT_KG = 24000
KG_RATE = 0.8            # руб. за кг
BASE_FEE = 3000          # погрузка, оформление документов
INSURANCE_RATE = 0.003   # 0,3 % объявленной стоимости
INSURANCE_MIN = 300


class PricingError(ValueError):
    """Заявка не может быть рассчитана."""


@dataclass(frozen=True)
class Quote:
    destination: str
    region: str
    cargo: str
    weight_kg: float
    transport: str
    distance_km: int
    price: float           # перевозка: тариф за расстояние + вес + оформление
    ship_date: date
    eta: date
    distance_fee: float = 0
    weight_fee: float = 0
    base_fee: float = BASE_FEE
    declared_value: float = 0
    insurance: float = 0
    temperature: str | None = None

    @property
    def total(self) -> float:
        return self.price + self.insurance


def choose_transport(cargo: str, weight_kg: float) -> str:
    if weight_kg > MAX_WEIGHT_KG:
        raise PricingError(f"Вес превышает максимальную грузоподъёмность {MAX_WEIGHT_KG} кг")
    if cargo in TEMPERATURE and weight_kg <= TRANSPORT["Рефрижератор"][0]:
        return "Рефрижератор"
    if weight_kg <= TRANSPORT["Газель"][0]:
        return "Газель"
    if weight_kg > TRANSPORT["Фура"][0]:
        return "Контейнер (ж/д)"
    return "Фура"


def insurance_for(declared_value: float) -> float:
    if declared_value <= 0:
        return 0
    return float(max(INSURANCE_MIN, round(declared_value * INSURANCE_RATE, -1)))


def quote(destination: str, cargo: str, weight_kg: float, ship_date: date, declared_value: float = 0) -> Quote:
    if destination not in DESTINATIONS:
        raise PricingError(f"Направление «{destination}» не обслуживается")
    if cargo not in CARGO:
        raise PricingError(f"Неизвестная категория груза «{cargo}»")
    if weight_kg <= 0:
        raise PricingError("Вес груза должен быть больше нуля")
    if declared_value < 0:
        raise PricingError("Объявленная стоимость не может быть отрицательной")
    region, distance = DESTINATIONS[destination]
    transport = choose_transport(cargo, weight_kg)
    _, speed, rate = TRANSPORT[transport]
    distance_fee = round(distance * rate * CARGO[cargo], -1)
    weight_fee = round(weight_kg * KG_RATE, -1)
    price = round(distance * rate * CARGO[cargo] + weight_kg * KG_RATE + BASE_FEE, -1)
    days = max(1, round(distance / (speed * 10)) + 1)
    return Quote(destination, region, cargo, weight_kg, transport, distance, price, ship_date,
                 ship_date + timedelta(days=days), distance_fee=distance_fee, weight_fee=weight_fee,
                 declared_value=declared_value, insurance=insurance_for(declared_value),
                 temperature=TEMPERATURE.get(cargo))
