"""Хранилище: пользователи, заказы, история статусов, водители, претензии (SQLite)."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta

from .config import PAYMENT_DAYS, REMIND_BEFORE_HOURS, now
from .pricing import Quote

# Статусы соответствуют этапам BPMN-модели «Процесс управления логистикой»
STATUSES = {
    "new": "На проверке у менеджера",           # 2–3
    "clarify": "Требует уточнения",               # 4–5
    "confirmed": "Ожидает оплаты",                # 7–8
    "paid": "Оплачен, передан на склад",          # 9
    "picking": "Комплектуется на складе",         # 10–12
    "ready": "Скомплектован, ТТН оформлена",      # 13
    "in_transit": "В пути",                       # 14–16
    "delayed": "В пути, задержка",                # 17–18
    "delivered": "Доставлен, ожидает приёмки",   # 19–20
    "accepted": "Принят без замечаний",           # 22
    "claim": "Претензия на рассмотрении",         # 23
    "closed": "Выполнен",                         # 25–26
    "cancelled": "Отменён",                       # конечное событие «Заказ отменён»
}
ROLES = ("client", "manager")

# Допустимые переходы (потоки операций BPMN)
TRANSITIONS = {
    # «Заявка корректна?»
    "new": {"confirmed", "clarify", "cancelled"},
    "clarify": {"new", "cancelled"},  # цикл уточнения
    # «Оплата поступила в течение 3 дней?»
    "confirmed": {"paid", "cancelled"},
    "paid": {"picking"},
    # «Груз укомплектован полностью?»
    "picking": {"picking", "ready"},
    "ready": {"in_transit"},  # только с водителем
    # таймер «Отклонение от графика»
    "in_transit": {"delayed", "delivered"},
    "delayed": {"delayed", "delivered"},
    "delivered": {"accepted", "claim"},  # «Есть замечания?»
    "accepted": {"closed"},
    "claim": {"closed"},
    "closed": set(),
    "cancelled": set(),
}
EDITABLE = {"address", "recipient", "places", "comment"}
ACTIVE = ("confirmed", "paid", "picking", "ready", "in_transit", "delayed", "delivered")

CLAIM_KINDS = {
    "shortage": "Недовложение",
    "damage": "Повреждение груза",
    "temperature": "Нарушение температурного режима",
    "other": "Другое",
}
CLAIM_DECISIONS = {
    "compensation": "Компенсация",
    "redelivery": "Довоз недостающего груза",
    "rejected": "Претензия отклонена",
}

DRIVERS = [  # (имя, тип транспорта, машина, госномер)
    ("Сергей Никитин", "Рефрижератор", "Isuzu Forward, рефрижератор", "А452КМ 27"),
    ("Андрей Ковалёв", "Фура", "КАМАЗ-65207 с полуприцепом", "В318ТР 27"),
    ("Игорь Белов", "Газель", "ГАЗель Next", "Е907НО 27"),
    ("Дмитрий Сорокин", "Контейнер (ж/д)", "КАМАЗ-контейнеровоз", "К225АУ 27"),
    ("Олег Лысенко", "Фура", "MAN TGX с полуприцепом", "М640ХС 27"),
    ("Павел Гришин", "Рефрижератор", "Hino 500, рефрижератор", "О771ЕР 27"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('client', 'manager'))
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES users(tg_id),
    destination TEXT NOT NULL, region TEXT NOT NULL, cargo TEXT NOT NULL,
    weight_kg REAL NOT NULL, transport TEXT NOT NULL, distance_km INTEGER NOT NULL,
    price REAL NOT NULL, ship_date TEXT NOT NULL, eta TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new', comment TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    status TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, transport TEXT NOT NULL, vehicle TEXT NOT NULL, plate TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    kind TEXT NOT NULL, text TEXT NOT NULL, photos TEXT NOT NULL DEFAULT '[]',
    decision TEXT, compensation REAL, answer TEXT,
    created_at TEXT NOT NULL, decided_at TEXT
);
"""

# Колонки, добавленные после первой версии, – для переноса существующей базы
MIGRATIONS = {
    "users": {"phone": "TEXT", "company": "TEXT", "created_at": "TEXT"},
    "orders": {
        "places": "INTEGER NOT NULL DEFAULT 1", "address": "TEXT", "recipient": "TEXT",
        "temperature": "TEXT", "declared_value": "REAL NOT NULL DEFAULT 0", "insurance": "REAL NOT NULL DEFAULT 0",
        "planned_eta": "TEXT", "pay_deadline": "TEXT", "reminded": "INTEGER NOT NULL DEFAULT 0",
        "driver_id": "INTEGER", "delivered_at": "TEXT", "on_time": "INTEGER", "in_full": "INTEGER",
        "rating": "INTEGER", "created_at": "TEXT",
    },
}


@dataclass
class User:
    tg_id: int
    name: str
    role: str
    phone: str | None = None
    company: str | None = None
    created_at: str | None = None


@dataclass
class Driver:
    id: int
    name: str
    transport: str
    vehicle: str
    plate: str


@dataclass
class Claim:
    id: int
    order_id: int
    kind: str
    text: str
    photos: list
    decision: str | None
    compensation: float | None
    answer: str | None
    created_at: str
    decided_at: str | None

    @property
    def kind_text(self) -> str:
        return CLAIM_KINDS.get(self.kind, self.kind)


@dataclass
class Order:
    id: int
    client_id: int
    destination: str
    region: str
    cargo: str
    weight_kg: float
    transport: str
    distance_km: int
    price: float
    ship_date: date
    eta: date
    status: str
    comment: str | None
    places: int = 1
    address: str | None = None
    recipient: str | None = None
    temperature: str | None = None
    declared_value: float = 0
    insurance: float = 0
    planned_eta: date | None = None
    pay_deadline: datetime | None = None
    reminded: int = 0
    driver_id: int | None = None
    delivered_at: date | None = None
    on_time: int | None = None
    in_full: int | None = None
    rating: int | None = None
    created_at: str | None = None

    @property
    def number(self) -> str:
        return f"LH-{20000 + self.id}"

    @property
    def status_text(self) -> str:
        return STATUSES[self.status]

    @property
    def total(self) -> float:
        return self.price + (self.insurance or 0)


class TransitionError(ValueError):
    """Недопустимый переход статуса заказа."""


def parse_number(text: str) -> int | None:
    digits = re.sub(r"\D", "", text.upper().replace("LH", ""))
    return int(digits) - 20000 if digits and int(digits) > 20000 else None


def _d(value):
    return date.fromisoformat(value) if value else None


def _dt(value):
    return datetime.fromisoformat(value) if value else None


class Storage:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        if not self.conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]:
            with self.conn:
                self.conn.executemany("INSERT INTO drivers(name, transport, vehicle, plate) VALUES (?, ?, ?, ?)", DRIVERS)

    def _migrate(self) -> None:
        with self.conn:
            for table, columns in MIGRATIONS.items():
                have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                for name, ddl in columns.items():
                    if name not in have:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            self.conn.execute("UPDATE orders SET planned_eta = eta WHERE planned_eta IS NULL")

    # --- пользователи ---
    def upsert_user(self, tg_id: int, name: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError(role)
        with self.conn:
            self.conn.execute("INSERT INTO users(tg_id, name, role, created_at) VALUES (?, ?, ?, ?) "
                              "ON CONFLICT(tg_id) DO UPDATE SET name = excluded.name, role = excluded.role",
                              (tg_id, name, role, now().isoformat()))

    def ensure_client(self, tg_id: int, name: str) -> None:
        if self.role(tg_id) is None:
            self.upsert_user(tg_id, name, "client")

    def set_contact(self, tg_id: int, company: str | None = None, phone: str | None = None) -> None:
        with self.conn:
            self.conn.execute("UPDATE users SET company = COALESCE(?, company), phone = COALESCE(?, phone) "
                              "WHERE tg_id = ?", (company, phone, tg_id))

    def user(self, tg_id: int) -> User | None:
        row = self.conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
        return User(**dict(row)) if row else None

    def role(self, tg_id: int) -> str | None:
        row = self.conn.execute("SELECT role FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
        return row["role"] if row else None

    def managers(self) -> list[int]:
        return [r["tg_id"] for r in self.conn.execute("SELECT tg_id FROM users WHERE role = 'manager'")]

    # --- водители ---
    def drivers(self, transport: str | None = None) -> list[Driver]:
        sql, args = "SELECT * FROM drivers", []
        if transport:
            sql += " WHERE transport = ?"; args.append(transport)
        return [Driver(**dict(r)) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def driver(self, driver_id: int | None) -> Driver | None:
        row = self.conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone() if driver_id else None
        return Driver(**dict(row)) if row else None

    # --- заказы ---
    def create_order(self, client_id: int, q: Quote, places: int = 1, address: str | None = None,
                     recipient: str | None = None, comment: str | None = None) -> Order:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO orders(client_id, destination, region, cargo, weight_kg, transport, distance_km, price, "
                "ship_date, eta, planned_eta, places, address, recipient, temperature, declared_value, insurance, "
                "comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (client_id, q.destination, q.region, q.cargo, q.weight_kg, q.transport, q.distance_km, q.price,
                 q.ship_date.isoformat(), q.eta.isoformat(), q.eta.isoformat(), places, address, recipient,
                 q.temperature, q.declared_value, q.insurance, comment, now().isoformat()))
            self._event(cur.lastrowid, "new", "Заявка создана в Telegram-боте")
        return self.get(cur.lastrowid)

    def get(self, order_id: int) -> Order | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return None
        data = {k: row[k] for k in row.keys() if k in {f.name for f in fields(Order)}}
        for key in ("ship_date", "eta", "planned_eta", "delivered_at"):
            data[key] = _d(data.get(key))
        data["pay_deadline"] = _dt(data.get("pay_deadline"))
        return Order(**data)

    def list(self, status=None, client_id: int | None = None) -> list[Order]:
        sql, args = "SELECT id FROM orders WHERE 1 = 1", []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            sql += f" AND status IN ({','.join('?' * len(statuses))})"; args += statuses
        if client_id:
            sql += " AND client_id = ?"; args.append(client_id)
        return [self.get(r["id"]) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def set_status(self, order_id: int, status: str, note: str | None = None, eta: date | None = None) -> Order:
        order = self.get(order_id)
        if order is None:
            raise TransitionError("Заказ не найден")
        if status not in TRANSITIONS[order.status]:
            raise TransitionError(f"Переход «{order.status_text}» → «{STATUSES[status]}» недопустим")
        extra = {}
        if status == "confirmed":
            extra["pay_deadline"] = (now() + timedelta(days=PAYMENT_DAYS)).isoformat()
            extra["reminded"] = 0
        if status == "in_transit" and not order.driver_id:
            raise TransitionError("Сначала назначьте водителя")
        if status == "delivered":
            extra["delivered_at"] = now().date().isoformat()
        if status == "closed":
            # On Time: доставлен не позже плановой даты и срок не переносили из-за отклонения от графика
            delivered, planned = order.delivered_at or now().date(), order.planned_eta or order.eta
            extra["on_time"] = int(delivered <= planned and order.eta <= planned)
            shortage = self.conn.execute("SELECT 1 FROM claims WHERE order_id = ? AND kind = 'shortage' "
                                         "AND decision IS NOT NULL AND decision != 'rejected'", (order_id,)).fetchone()
            extra["in_full"] = int(shortage is None)
        if eta:
            extra["eta"] = eta.isoformat()
        sets = "".join(f", {k} = ?" for k in extra)
        with self.conn:
            self.conn.execute(f"UPDATE orders SET status = ?{sets} WHERE id = ?", (status, *extra.values(), order_id))
            self._event(order_id, status, note)
        return self.get(order_id)

    def update_order(self, order_id: int, **values) -> Order:
        """Правка заявки клиентом на этапе уточнения (этап 5)."""
        unknown = set(values) - EDITABLE
        if unknown:
            raise ValueError(f"Поля нельзя изменить: {', '.join(sorted(unknown))}")
        if values:
            sets = ", ".join(f"{k} = ?" for k in values)
            with self.conn:
                self.conn.execute(f"UPDATE orders SET {sets} WHERE id = ?", (*values.values(), order_id))
        return self.get(order_id)

    def log(self, order_id: int, note: str) -> None:
        """Событие без смены статуса: назначен водитель, клиент сообщил об оплате и т. п."""
        order = self.get(order_id)
        with self.conn:
            self._event(order_id, order.status, note)

    def assign_driver(self, order_id: int, driver_id: int) -> Order:
        """Этап 14: диспетчер назначает водителя под тип транспорта заказа."""
        order, driver = self.get(order_id), self.driver(driver_id)
        if order is None or driver is None:
            raise TransitionError("Заказ или водитель не найден")
        if order.status != "ready":
            raise TransitionError("Водителя назначают, когда груз скомплектован и ТТН оформлена")
        if driver.transport != order.transport:
            raise TransitionError(f"Нужен водитель с транспортом «{order.transport}»")
        with self.conn:
            self.conn.execute("UPDATE orders SET driver_id = ? WHERE id = ?", (driver_id, order_id))
            self._event(order_id, order.status, f"Назначен водитель {driver.name}, {driver.vehicle}, {driver.plate}")
        return self.get(order_id)

    def set_rating(self, order_id: int, rating: int) -> None:
        if not 1 <= rating <= 5:
            raise ValueError(rating)
        with self.conn:
            self.conn.execute("UPDATE orders SET rating = ? WHERE id = ?", (rating, order_id))

    def history(self, order_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT status, note, created_at FROM events WHERE order_id = ? ORDER BY id",
                                 (order_id,)).fetchall()

    def _event(self, order_id: int, status: str, note: str | None) -> None:
        self.conn.execute("INSERT INTO events(order_id, status, note, created_at) VALUES (?, ?, ?, ?)",
                          (order_id, status, note, now().isoformat(timespec="minutes")))

    # --- контроль оплаты (этап 9) ---
    def overdue_payments(self, moment: datetime | None = None) -> list[Order]:
        moment = moment or now()
        rows = self.conn.execute("SELECT id FROM orders WHERE status = 'confirmed' AND pay_deadline <= ?",
                                 (moment.isoformat(),))
        return [self.get(r["id"]) for r in rows]

    def payments_to_remind(self, moment: datetime | None = None) -> list[Order]:
        moment = moment or now()
        edge = (moment + timedelta(hours=REMIND_BEFORE_HOURS)).isoformat()
        rows = self.conn.execute("SELECT id FROM orders WHERE status = 'confirmed' AND reminded = 0 "
                                 "AND pay_deadline <= ? AND pay_deadline > ?", (edge, moment.isoformat()))
        return [self.get(r["id"]) for r in rows]

    def mark_reminded(self, order_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE orders SET reminded = 1 WHERE id = ?", (order_id,))

    # --- претензии (этапы 20–23) ---
    def add_claim(self, order_id: int, kind: str, text: str, photos: list[str] | None = None) -> Claim:
        if kind not in CLAIM_KINDS:
            raise ValueError(kind)
        with self.conn:
            cur = self.conn.execute("INSERT INTO claims(order_id, kind, text, photos, created_at) VALUES (?, ?, ?, ?, ?)",
                                    (order_id, kind, text, json.dumps(photos or []), now().isoformat()))
        return self.claim(cur.lastrowid)

    def claim(self, claim_id: int) -> Claim | None:
        row = self.conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["photos"] = json.loads(data["photos"])
        return Claim(**data)

    def order_claim(self, order_id: int) -> Claim | None:
        row = self.conn.execute("SELECT id FROM claims WHERE order_id = ? ORDER BY id DESC", (order_id,)).fetchone()
        return self.claim(row["id"]) if row else None

    def decide_claim(self, claim_id: int, decision: str, answer: str, compensation: float | None = None) -> Claim:
        if decision not in CLAIM_DECISIONS:
            raise ValueError(decision)
        with self.conn:
            self.conn.execute("UPDATE claims SET decision = ?, answer = ?, compensation = ?, decided_at = ? WHERE id = ?",
                              (decision, answer, compensation, now().isoformat(), claim_id))
        return self.claim(claim_id)

    # --- сводка для менеджера ---
    def stats(self) -> dict:
        by_status = dict(self.conn.execute("SELECT status, COUNT(*) FROM orders GROUP BY status").fetchall())
        closed = self.conn.execute("SELECT COUNT(*), SUM(on_time), SUM(on_time * in_full) FROM orders "
                                   "WHERE status = 'closed'").fetchone()
        rating = self.conn.execute("SELECT AVG(rating), COUNT(rating) FROM orders WHERE rating IS NOT NULL").fetchone()
        revenue = self.conn.execute("SELECT COALESCE(SUM(price + insurance), 0) FROM orders "
                                    "WHERE status NOT IN ('new', 'clarify', 'confirmed', 'cancelled')").fetchone()[0]
        total_closed = closed[0] or 0
        return {
            "by_status": by_status,
            "total": sum(by_status.values()),
            "closed": total_closed,
            "on_time": (closed[1] or 0) / total_closed * 100 if total_closed else None,
            "otif": (closed[2] or 0) / total_closed * 100 if total_closed else None,
            "rating": rating[0], "ratings": rating[1],
            "revenue": revenue,
            "open_claims": by_status.get("claim", 0),
        }

    def export_rows(self) -> list[dict]:
        out = []
        for o in self.list():
            u = self.user(o.client_id)
            d = self.driver(o.driver_id)
            out.append({
                "order": o.number, "created": (o.created_at or "")[:16].replace("T", " "),
                "client": (u.company or u.name) if u else "", "phone": (u.phone or "") if u else "",
                "destination": o.destination, "region": o.region, "address": o.address or "",
                "cargo": o.cargo, "weight_kg": o.weight_kg, "places": o.places, "transport": o.transport,
                "driver": d.name if d else "", "price": o.price, "insurance": o.insurance, "total": o.total,
                "ship_date": o.ship_date.isoformat(), "planned_eta": (o.planned_eta or o.eta).isoformat(),
                "eta": o.eta.isoformat(), "delivered": o.delivered_at.isoformat() if o.delivered_at else "",
                "status": o.status_text, "on_time": "" if o.on_time is None else o.on_time,
                "in_full": "" if o.in_full is None else o.in_full, "rating": o.rating or "",
            })
        return out

    def close(self) -> None:
        with closing(self.conn):
            pass
