"""Интеграция с аналитическим дашбордом: KPI и графики из выгрузки заказов.

Используется модуль данных пакета logihub-dashboard, поэтому бот и дашборд считают
показатели одинаково.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from logihub_dashboard.data import OTIF_TARGET, PERIODS, by_period, kpis, prepare  # noqa: E402

NAVY, BLUE, ORANGE = "#0b1b3f", "#2f5bea", "#ff8a3d"


class Analytics:
    def __init__(self, csv_path: str | Path):
        self.df = prepare(pd.read_csv(csv_path))

    def last_period(self, freq: str) -> pd.DataFrame:
        """Заказы за текущий (последний в выгрузке) месяц, квартал или год."""
        end = self.df["order_date"].max()
        start = end.to_period(freq).start_time
        return self.df[self.df["order_date"] >= start]

    def summary(self, freq: str = "M") -> str:
        view = self.last_period(freq)
        k = kpis(view)
        start, end = view["order_date"].min(), view["order_date"].max()
        mark = "✅" if k["otif"] >= OTIF_TARGET else "⚠️"
        return (f"📊 <b>KPI за {PERIODS[freq].lower()}</b> ({start:%d.%m.%Y}–{end:%d.%m.%Y})\n\n"
                f"{mark} OTIF: <b>{k['otif']:.1f} %</b> (цель {OTIF_TARGET:.0f} %)\n"
                f"⏱ В срок: {k['on_time']:.1f} %   📦 В полном объёме: {k['in_full']:.1f} %\n"
                f"🚚 Заказов: {k['orders']}   ❌ Отмены: {k['cancel_rate']:.1f} %\n"
                f"💰 Выручка: {k['revenue'] / 1e6:.2f} млн ₽\n"
                f"📈 Прибыль: {k['profit'] / 1e6:.2f} млн ₽ (рентабельность {k['margin']:.1f} %)")

    def otif_chart(self, freq: str = "M", last: int = 12) -> bytes:
        data = by_period(self.df, freq).tail(last)
        fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
        ax.plot(data["label"], data["otif"], color=NAVY, marker="o", lw=2.5)
        ax.fill_between(data["label"], data["otif"], 50, color=BLUE, alpha=0.08)
        ax.axhline(OTIF_TARGET, color=ORANGE, ls="--", lw=1.5)
        ax.text(0, OTIF_TARGET + 0.6, f"цель {OTIF_TARGET:.0f} %", color=ORANGE, fontsize=9)
        ax.set_ylim(60, 100)
        ax.set_title(f"OTIF по периодам ({PERIODS[freq].lower()})", loc="left", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.3)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()
