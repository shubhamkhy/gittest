from __future__ import annotations

import csv
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from minervini_india import (
    DailyBar,
    load_csv_history,
    load_yahoo_history,
    screen_universe,
    score_stock,
)


class ScreenerTests(unittest.TestCase):
    def test_scores_breakout_candidate_with_trend_vcp_and_relative_strength(self) -> None:
        stock_bars = _make_stock_history()
        benchmark_bars = _make_benchmark_history()

        result = score_stock("EXAMPLE.NS", stock_bars, benchmark=benchmark_bars)

        self.assertEqual(result.label, "breakout_candidate")
        self.assertGreaterEqual(result.score, 85.0)
        self.assertIsNotNone(result.relative_strength_pct)
        self.assertGreater(result.relative_strength_pct or 0.0, 0.0)
        self.assertIsNotNone(result.pivot)
        self.assertIsNotNone(result.suggested_stop)
        self.assertTrue(result.required_filters_passed)
        self.assertFalse(result.inside_candle_formed)
        passed_rules = {rule.name for rule in result.rules if rule.passed}
        self.assertIn("price_above_minimum", passed_rules)
        self.assertIn("price_above_50ema", passed_rules)
        self.assertIn("price_above_200ema", passed_rules)
        self.assertIn("price_above_200sma", passed_rules)
        self.assertIn("at_least_40pct_return_3mo", passed_rules)
        self.assertIn("liquid_volume", passed_rules)
        self.assertIn("within_10pct_of_nearest_high", passed_rules)
        self.assertIn("bullish_daily_candle", passed_rules)
        self.assertIn("breakout_volume", passed_rules)

    def test_requires_ema_position_return_and_average_volume(self) -> None:
        low_return_result = score_stock(
            "LOWRETURN.NS",
            _make_low_return_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(low_return_result.required_filters_passed)
        self.assertEqual(low_return_result.score, 0.0)
        self.assertEqual(low_return_result.label, "avoid_for_now")
        failed_low_return_rules = {
            rule.name for rule in low_return_result.rules if not rule.passed
        }
        self.assertIn("at_least_40pct_return_3mo", failed_low_return_rules)

        below_ema_result = score_stock(
            "BELOWEMA.NS",
            _make_below_ema_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(below_ema_result.required_filters_passed)
        self.assertEqual(below_ema_result.score, 0.0)
        failed_ema_rules = {
            rule.name for rule in below_ema_result.rules if not rule.passed
        }
        self.assertIn("price_above_50ema", failed_ema_rules)
        self.assertIn("price_above_200ema", failed_ema_rules)

        low_volume_result = score_stock(
            "LOWVOLUME.NS",
            _make_low_volume_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(low_volume_result.required_filters_passed)
        self.assertEqual(low_volume_result.score, 0.0)
        failed_volume_rules = {
            rule.name for rule in low_volume_result.rules if not rule.passed
        }
        self.assertIn("liquid_volume", failed_volume_rules)

        low_price_result = score_stock(
            "LOWPRICE.NS",
            _make_low_price_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(low_price_result.required_filters_passed)
        self.assertEqual(low_price_result.score, 0.0)
        failed_price_rules = {
            rule.name for rule in low_price_result.rules if not rule.passed
        }
        self.assertIn("price_above_minimum", failed_price_rules)

        far_from_high_result = score_stock(
            "FARHIGH.NS",
            _make_far_from_nearest_high_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(far_from_high_result.required_filters_passed)
        self.assertEqual(far_from_high_result.score, 0.0)
        failed_high_rules = {
            rule.name for rule in far_from_high_result.rules if not rule.passed
        }
        self.assertIn("within_10pct_of_nearest_high", failed_high_rules)

        red_candle_result = score_stock(
            "REDCANDLE.NS",
            _make_red_candle_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(red_candle_result.required_filters_passed)
        self.assertEqual(red_candle_result.score, 0.0)
        failed_candle_rules = {
            rule.name for rule in red_candle_result.rules if not rule.passed
        }
        self.assertIn("bullish_daily_candle", failed_candle_rules)

    def test_marks_inside_candle_when_latest_range_is_inside_previous_day(self) -> None:
        result = score_stock(
            "INSIDE.NS",
            _make_inside_candle_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertTrue(result.inside_candle_formed)
        self.assertTrue(result.to_dict()["inside_candle_formed"])

        equal_boundary_result = score_stock(
            "EQUAL.NS",
            _make_equal_boundary_history(),
            benchmark=_make_benchmark_history(),
        )

        self.assertFalse(equal_boundary_result.inside_candle_formed)

    def test_csv_loader_accepts_common_ohlcv_header_variants(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "TEST.NS.csv"
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

        self.assertEqual(
            bars,
            [
                DailyBar(
                    date=date(2026, 1, 1),
                    open=100.0,
                    high=105.0,
                    low=99.0,
                    close=104.0,
                    volume=150000.0,
                )
            ],
        )

    def test_yahoo_loader_skips_incomplete_live_rows(self) -> None:
        sentinel = object()
        previous_yfinance = sys.modules.get("yfinance", sentinel)
        sys.modules["yfinance"] = types.SimpleNamespace(Ticker=_FakeTicker)
        try:
            bars = load_yahoo_history("TEST.NS")
        finally:
            if previous_yfinance is sentinel:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = previous_yfinance

        self.assertEqual(
            [bar.date for bar in bars],
            [date(2026, 1, 1), date(2026, 1, 3)],
        )
        self.assertEqual([bar.close for bar in bars], [104.0, 108.0])

    def test_screen_universe_ranks_highest_score_first(self) -> None:
        strong = _make_stock_history()
        weak = _make_benchmark_history(start_price=100.0, daily_step=0.02)

        results = screen_universe(
            {"STRONG.NS": strong, "WEAK.NS": weak},
            benchmark=_make_benchmark_history(),
        )

        self.assertEqual(
            [result.symbol for result in results][:2],
            ["STRONG.NS", "WEAK.NS"],
        )


def _make_stock_history() -> list[DailyBar]:
    return _make_history(pre_breakout_step=0.20, post_breakout_step=1.00)


def _make_low_return_history() -> list[DailyBar]:
    return _make_history(pre_breakout_step=0.45, post_breakout_step=0.45)


def _make_low_volume_history() -> list[DailyBar]:
    return _make_history(
        pre_breakout_step=0.20,
        post_breakout_step=1.00,
        liquid=False,
    )


def _make_low_price_history() -> list[DailyBar]:
    return _scale_prices(_make_stock_history(), multiplier=0.20)


def _make_inside_candle_history() -> list[DailyBar]:
    bars = _make_stock_history()
    previous = bars[-2]
    inside_high = previous.high - 0.10
    inside_low = previous.low + 0.10
    inside_close = (inside_high + inside_low) / 2
    latest = bars[-1]
    return [
        *bars[:-1],
        DailyBar(
            date=latest.date,
            open=inside_close,
            high=inside_high,
            low=inside_low,
            close=inside_close,
            volume=latest.volume,
        ),
    ]


def _make_equal_boundary_history() -> list[DailyBar]:
    bars = _make_stock_history()
    previous = bars[-2]
    latest = bars[-1]
    equal_close = (previous.high + previous.low) / 2
    return [
        *bars[:-1],
        DailyBar(
            date=latest.date,
            open=equal_close,
            high=previous.high,
            low=previous.low,
            close=equal_close,
            volume=latest.volume,
        ),
    ]


def _make_far_from_nearest_high_history() -> list[DailyBar]:
    bars = _make_stock_history()
    previous = bars[-2]
    latest = bars[-1]
    return [
        *bars[:-2],
        DailyBar(
            date=previous.date,
            open=previous.open,
            high=latest.close * 1.25,
            low=previous.low,
            close=previous.close,
            volume=previous.volume,
        ),
        latest,
    ]


def _make_red_candle_history() -> list[DailyBar]:
    bars = _make_stock_history()
    latest = bars[-1]
    red_open = latest.close * 1.01
    return [
        *bars[:-1],
        DailyBar(
            date=latest.date,
            open=red_open,
            high=red_open * 1.001,
            low=latest.close * 0.995,
            close=latest.close,
            volume=latest.volume,
        ),
    ]


def _make_below_ema_history() -> list[DailyBar]:
    bars = _make_stock_history()
    latest = bars[-1]
    return [
        *bars[:-1],
        DailyBar(
            date=latest.date,
            open=90.0,
            high=92.0,
            low=88.0,
            close=90.0,
            volume=latest.volume,
        ),
    ]


def _make_history(
    pre_breakout_step: float,
    post_breakout_step: float,
    liquid: bool = True,
) -> list[DailyBar]:
    bars: list[DailyBar] = []
    start = date(2025, 1, 1)
    close = 100.0
    for index in range(300):
        close += post_breakout_step if index >= 236 else pre_breakout_step
        spread_pct = _spread_for_index(index)
        high = close * (1 + spread_pct / 2)
        low = close * (1 - spread_pct / 2)
        volume = 700_000 if liquid else 80_000
        if index >= 270:
            volume = 550_000 if liquid else 60_000
        if index == 299:
            high = close * 1.015
            close = max(high, max(bar.high for bar in bars[-20:]) + 1.0)
            low = close * 0.995
            volume = 1_200_000 if liquid else 90_000
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


def _scale_prices(bars: list[DailyBar], multiplier: float) -> list[DailyBar]:
    return [
        DailyBar(
            date=bar.date,
            open=bar.open * multiplier,
            high=bar.high * multiplier,
            low=bar.low * multiplier,
            close=bar.close * multiplier,
            volume=bar.volume,
        )
        for bar in bars
    ]


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


class _FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, period: str, auto_adjust: bool) -> "_FakeYahooFrame":
        return _FakeYahooFrame(
            [
                (
                    datetime(2026, 1, 1),
                    {
                        "Open": 100,
                        "High": 105,
                        "Low": 99,
                        "Close": 104,
                        "Volume": 600_000,
                    },
                ),
                (
                    datetime(2026, 1, 2),
                    {
                        "Open": 104,
                        "High": 106,
                        "Low": 103,
                        "Close": float("nan"),
                        "Volume": 650_000,
                    },
                ),
                (
                    datetime(2026, 1, 3),
                    {
                        "Open": 105,
                        "High": 109,
                        "Low": 104,
                        "Close": 108,
                        "Volume": 700_000,
                    },
                ),
            ]
        )


class _FakeYahooFrame:
    def __init__(self, rows: list[tuple[datetime, dict[str, float]]]) -> None:
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self._rows)


if __name__ == "__main__":
    unittest.main()
