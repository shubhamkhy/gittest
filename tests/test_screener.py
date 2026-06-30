from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from minervini_india import DailyBar, load_csv_history, screen_universe, score_stock


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
        passed_rules = {rule.name for rule in result.rules if rule.passed}
        self.assertIn("price_above_50ema", passed_rules)
        self.assertIn("price_above_200ema", passed_rules)
        self.assertIn("price_above_200sma", passed_rules)
        self.assertIn("at_least_40pct_return_3mo", passed_rules)
        self.assertIn("liquid_volume", passed_rules)
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
        volume = 700_000 if liquid else 450_000
        if index >= 270:
            volume = 550_000 if liquid else 220_000
        if index == 299:
            high = close * 1.015
            close = max(high, max(bar.high for bar in bars[-20:]) + 1.0)
            low = close * 0.995
            volume = 1_200_000 if liquid else 850_000
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


if __name__ == "__main__":
    unittest.main()
