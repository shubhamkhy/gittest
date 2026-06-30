from __future__ import annotations

import csv
from datetime import date, timedelta

from minervini_india import DailyBar, load_csv_history, screen_universe, score_stock


def test_scores_breakout_candidate_with_trend_vcp_and_relative_strength() -> None:
    stock_bars = _make_stock_history()
    benchmark_bars = _make_benchmark_history()

    result = score_stock("EXAMPLE.NS", stock_bars, benchmark=benchmark_bars)

    assert result.label == "breakout_candidate"
    assert result.score >= 85.0
    assert result.relative_strength_pct is not None
    assert result.relative_strength_pct > 0
    assert result.pivot is not None
    assert result.suggested_stop is not None
    assert "price_above_200sma" in {rule.name for rule in result.rules if rule.passed}
    assert "breakout_volume" in {rule.name for rule in result.rules if rule.passed}


def test_csv_loader_accepts_common_ohlcv_header_variants(tmp_path) -> None:
    csv_path = tmp_path / "TEST.NS.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Date", "Open", "High", "Low", "Close", "Volume"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Date": "2026-01-01",
                "Open": "100",
                "High": "105",
                "Low": "99",
                "Close": "104",
                "Volume": "150000",
            }
        )

    bars = load_csv_history(csv_path)

    assert bars == [
        DailyBar(
            date=date(2026, 1, 1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            volume=150000.0,
        )
    ]


def test_screen_universe_ranks_highest_score_first() -> None:
    strong = _make_stock_history()
    weak = _make_benchmark_history(start_price=100.0, daily_step=0.02)

    results = screen_universe(
        {"STRONG.NS": strong, "WEAK.NS": weak},
        benchmark=_make_benchmark_history(),
    )

    assert [result.symbol for result in results][:2] == ["STRONG.NS", "WEAK.NS"]


def _make_stock_history() -> list[DailyBar]:
    bars: list[DailyBar] = []
    start = date(2025, 1, 1)
    close = 100.0
    for index in range(300):
        close += 0.45
        spread_pct = _spread_for_index(index)
        high = close * (1 + spread_pct / 2)
        low = close * (1 - spread_pct / 2)
        volume = 450_000
        if index >= 270:
            volume = 220_000
        if index == 299:
            high = close * 1.015
            close = max(high, max(bar.high for bar in bars[-20:]) + 1.0)
            low = close * 0.995
            volume = 850_000
        bars.append(
            DailyBar(
                date=start + timedelta(days=index),
                open=close * 0.995,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return bars


def _make_benchmark_history(
    start_price: float = 100.0,
    daily_step: float = 0.10,
) -> list[DailyBar]:
    bars: list[DailyBar] = []
    start = date(2025, 1, 1)
    close = start_price
    for index in range(300):
        close += daily_step
        bars.append(
            DailyBar(
                date=start + timedelta(days=index),
                open=close,
                high=close * 1.005,
                low=close * 0.995,
                close=close,
                volume=500_000,
            )
        )
    return bars


def _spread_for_index(index: int) -> float:
    if index < 220:
        return 0.07
    if index < 240:
        return 0.12
    if index < 260:
        return 0.08
    if index < 280:
        return 0.05
    return 0.025
