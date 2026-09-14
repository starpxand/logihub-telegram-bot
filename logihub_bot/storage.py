"""Хранилище пользователей, заказов и истории статусов (SQLite)."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .pricing import Quote

# Статусы соответствуют этапам BPMN-модели «Процесс управления логистикой»
STATUSES = {
    "new": "На проверке у менеджера",
    "clarify": "Возвращена на уточнение",
    "confirmed": "Подтверждена, ожидает оплату",
    "in_transit": "В пути",
    "delayed": "В пути, задержка",
    "delivered": "Доставлен, ожидает приёмки",
    "accepted": "Принят без замечаний",
    "claim": "Претензия на рассмотрении",
    "closed": "Заказ закрыт",
}
ROLES = ("client", "manager")

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
"""


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

    @property
    def number(self) -> str:
        return f"LH-{20000 + self.id}"

    @property
    def status_text(self) -> str:
        return STATUSES[self.status]


class TransitionError(ValueError):
    """Недопустимый переход статуса заказа."""


# Допустимые переходы (потоки операций BPMN)
TRANSITIONS = {
    "new": {"confirmed", "clarify"},
    "clarify": {"new"},
    "confirmed": {"in_transit"},
    "in_transit": {"delayed", "delivered"},
    "delayed": {"delayed", "delivered"},
    "delivered": {"accepted", "claim"},
    "accepted": {"closed"},
    "claim": {"closed"},
    "closed": set(),
}


def parse_number(text: str) -> int | None:
    text = text.strip().upper().replace("LH-", "").replace("LH", "")
    return int(text) - 20000 if text.isdigit() and int(text) > 20000 else None


class Storage:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- пользователи ---
    def upsert_user(self, tg_id: int, name: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError(role)
        with self.conn:
            self.conn.execute("INSERT INTO users(tg_id, name, role) VALUES (?, ?, ?) "
                              "ON CONFLICT(tg_id) DO UPDATE SET name = excluded.name, role = excluded.role",
                              (tg_id, name, role))

    def role(self, tg_id: int) -> str | None:
        row = self.conn.execute("SELECT role FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
        return row["role"] if row else None

    def managers(self) -> list[int]:
        return [r["tg_id"] for r in self.conn.execute("SELECT tg_id FROM users WHERE role = 'manager'")]

    # --- заказы ---
    def create_order(self, client_id: int, q: Quote) -> Order:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO orders(client_id, destination, region, cargo, weight_kg, transport, distance_km, price, "
                "ship_date, eta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (client_id, q.destination, q.region, q.cargo, q.weight_kg, q.transport, q.distance_km, q.price,
                 q.ship_date.isoformat(), q.eta.isoformat()))
            self._event(cur.lastrowid, "new", "Заявка создана в Telegram-боте")
        return self.get(cur.lastrowid)

    def get(self, order_id: int) -> Order | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["ship_date"] = date.fromisoformat(data["ship_date"])
        data["eta"] = date.fromisoformat(data["eta"])
        return Order(**data)

    def list(self, status: str | None = None, client_id: int | None = None) -> list[Order]:
        sql, args = "SELECT id FROM orders WHERE 1 = 1", []
        if status:
            sql += " AND status = ?"; args.append(status)
        if client_id:
            sql += " AND client_id = ?"; args.append(client_id)
        return [self.get(r["id"]) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def set_status(self, order_id: int, status: str, note: str | None = None, eta: date | None = None) -> Order:
        order = self.get(order_id)
        if order is None:
            raise TransitionError("Заказ не найден")
        if status not in TRANSITIONS[order.status]:
            raise TransitionError(f"Переход «{order.status_text}» → «{STATUSES[status]}» недопустим")
        with self.conn:
            self.conn.execute("UPDATE orders SET status = ?, comment = COALESCE(?, comment), eta = COALESCE(?, eta) "
                              "WHERE id = ?", (status, note, eta.isoformat() if eta else None, order_id))
            self._event(order_id, status, note)
        return self.get(order_id)

    def history(self, order_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT status, note, created_at FROM events WHERE order_id = ? ORDER BY id",
                                 (order_id,)).fetchall()

    def _event(self, order_id: int, status: str, note: str | None) -> None:
        self.conn.execute("INSERT INTO events(order_id, status, note, created_at) VALUES (?, ?, ?, ?)",
                          (order_id, status, note, datetime.now().isoformat(timespec="minutes")))

    def close(self) -> None:
        with closing(self.conn):
            pass
