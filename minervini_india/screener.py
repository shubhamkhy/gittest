"""Minervini-inspired screening logic for Indian equities.

The implementation is intentionally transparent: every score is backed by a
small set of explainable rules so the output can be audited before any trade is
considered.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence


REQUIRED_FILTER_RULES = frozenset(
    {
        "price_above_50ema",
        "price_above_200ema",
        "at_least_40pct_return_3mo",
        "liquid_volume",
        "price_above_minimum",
    }
)


@dataclass(frozen=True)
class DailyBar:
    """One daily OHLCV record."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ScreenConfig:
    """Thresholds for the Minervini-style screen."""

    min_history_days: int = 260
    sma_short: int = 50
    sma_mid: int = 150
    sma_long: int = 200
    sma_long_slope_days: int = 20
    ema_short: int = 50
    ema_long: int = 200
    high_low_window: int = 252
    min_above_52w_low_pct: float = 0.30
    max_below_52w_high_pct: float = 0.25
    return_lookback_days: int = 63
    min_return_3mo_pct: float = 0.40
    vcp_lookback_days: int = 80
    vcp_pocket_days: int = 20
    volume_dry_up_ratio: float = 0.75
    tight_close_max_pct: float = 0.035
    near_pivot_pct: float = 0.05
    breakout_volume_multiplier: float = 1.40
    rs_lookback_days: int = 126
    min_avg_volume_50d: float = 100_000
    min_price: float = 60.0
    max_stop_loss_pct: float = 0.08


@dataclass(frozen=True)
class RuleEvaluation:
    """Result of one explainable screening rule."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ScreenResult:
    """Recommendation-style output for one symbol."""

    symbol: str
    as_of: date | None
    close: float | None
    score: float
    label: str
    trend_score: float
    vcp_score: float
    relative_strength_score: float
    relative_strength_pct: float | None
    pivot: float | None
    suggested_stop: float | None
    required_filters_passed: bool = False
    inside_candle_formed: bool = False
    rules: tuple[RuleEvaluation, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Return a serialization-friendly representation."""

        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "close": self.close,
            "score": round(self.score, 2),
            "label": self.label,
            "trend_score": round(self.trend_score, 2),
            "vcp_score": round(self.vcp_score, 2),
            "relative_strength_score": round(self.relative_strength_score, 2),
            "relative_strength_pct": (
                round(self.relative_strength_pct, 2)
                if self.relative_strength_pct is not None
                else None
            ),
            "pivot": round(self.pivot, 2) if self.pivot is not None else None,
            "suggested_stop": (
                round(self.suggested_stop, 2)
                if self.suggested_stop is not None
                else None
            ),
            "required_filters_passed": self.required_filters_passed,
            "inside_candle_formed": self.inside_candle_formed,
            "passed_rules": [rule.name for rule in self.rules if rule.passed],
            "failed_rules": [rule.name for rule in self.rules if not rule.passed],
            "notes": list(self.notes),
        }


def load_csv_history(path: str | Path) -> list[DailyBar]:
    """Load daily OHLCV history from a CSV file.

    Required columns are date, open, high, low, close, and volume. Column names
    are matched case-insensitively and may contain spaces or underscores.
    """

    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path} has no header row")

        normalized_fields = {
            _normalize_column(field): field for field in reader.fieldnames
        }
        required = ("date", "open", "high", "low", "close", "volume")
        missing = [field for field in required if field not in normalized_fields]
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {', '.join(missing)}")

        bars = [
            DailyBar(
                date=_parse_date(row[normalized_fields["date"]]),
                open=_parse_float(row[normalized_fields["open"]], "open", csv_path),
                high=_parse_float(row[normalized_fields["high"]], "high", csv_path),
                low=_parse_float(row[normalized_fields["low"]], "low", csv_path),
                close=_parse_float(row[normalized_fields["close"]], "close", csv_path),
                volume=_parse_float(
                    row[normalized_fields["volume"]], "volume", csv_path
                ),
            )
            for row in reader
            if any(value.strip() for value in row.values() if value is not None)
        ]

    return sorted(bars, key=lambda bar: bar.date)


def load_yahoo_history(symbol: str, period: str = "18mo") -> list[DailyBar]:
    """Load history from Yahoo Finance using yfinance.

    NSE symbols usually end in ``.NS`` and BSE symbols in ``.BO``. For example:
    ``RELIANCE.NS`` or ``TCS.NS``.
    """

    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Live data requires yfinance. Install with: "
            "python3 -m pip install 'indian-minervini-screener[live]'"
        ) from exc

    frame = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    if frame.empty:
        return []

    bars: list[DailyBar] = []
    for index, row in frame.iterrows():
        open_price = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = float(row["Volume"])
        if not all(math.isfinite(value) for value in (open_price, high, low, close, volume)):
            continue

        bars.append(
            DailyBar(
                date=index.date(),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return bars


def screen_universe(
    histories: Mapping[str, Sequence[DailyBar]],
    benchmark: Sequence[DailyBar] | None = None,
    config: ScreenConfig | None = None,
) -> list[ScreenResult]:
    """Score and rank a collection of symbols."""

    active_config = config or ScreenConfig()
    results = [
        score_stock(symbol, bars, benchmark=benchmark, config=active_config)
        for symbol, bars in histories.items()
    ]
    return sorted(results, key=lambda result: result.score, reverse=True)


def score_stock(
    symbol: str,
    bars: Sequence[DailyBar],
    benchmark: Sequence[DailyBar] | None = None,
    config: ScreenConfig | None = None,
) -> ScreenResult:
    """Score one stock using trend-template, VCP, and relative-strength rules."""

    active_config = config or ScreenConfig()
    ordered_bars = tuple(sorted(bars, key=lambda bar: bar.date))
    if len(ordered_bars) < active_config.min_history_days:
        return ScreenResult(
            symbol=symbol,
            as_of=ordered_bars[-1].date if ordered_bars else None,
            close=ordered_bars[-1].close if ordered_bars else None,
            score=0.0,
            label="insufficient_data",
            trend_score=0.0,
            vcp_score=0.0,
            relative_strength_score=0.0,
            relative_strength_pct=None,
            pivot=None,
            suggested_stop=None,
            required_filters_passed=False,
            notes=(
                f"Needs at least {active_config.min_history_days} daily bars; "
                f"found {len(ordered_bars)}.",
            ),
        )

    closes = [bar.close for bar in ordered_bars]
    highs = [bar.high for bar in ordered_bars]
    lows = [bar.low for bar in ordered_bars]
    volumes = [bar.volume for bar in ordered_bars]
    latest = ordered_bars[-1]

    trend_score, trend_rules = _score_trend_template(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        config=active_config,
    )
    vcp_score, vcp_rules, pivot = _score_vcp_setup(
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        config=active_config,
    )
    rs_score, rs_pct, rs_rules = _score_relative_strength(
        stock_bars=ordered_bars,
        benchmark_bars=benchmark,
        config=active_config,
    )

    maximum_score = 100.0 if benchmark else 80.0
    raw_score = trend_score + vcp_score + rs_score
    normalized_score = min(100.0, raw_score / maximum_score * 100.0)
    breakout = any(rule.name == "breakout_volume" and rule.passed for rule in vcp_rules)
    required_filters_passed = _required_filters_passed(trend_rules)
    if not required_filters_passed:
        normalized_score = 0.0
    label = _label_for_score(normalized_score, breakout=breakout)
    suggested_stop = latest.close * (1.0 - active_config.max_stop_loss_pct)
    notes = [
        "Educational screen only; validate fundamentals, news, liquidity, and risk.",
        "Use a predefined stop and position sizing before any live trade.",
    ]
    if benchmark is None:
        notes.append("Relative strength was not scored because no benchmark was supplied.")
    inside_candle_formed = _inside_candle_formed(ordered_bars)

    return ScreenResult(
        symbol=symbol,
        as_of=latest.date,
        close=latest.close,
        score=normalized_score,
        label=label,
        trend_score=trend_score,
        vcp_score=vcp_score,
        relative_strength_score=rs_score,
        relative_strength_pct=rs_pct,
        pivot=pivot,
        suggested_stop=suggested_stop,
        required_filters_passed=required_filters_passed,
        inside_candle_formed=inside_candle_formed,
        rules=tuple([*trend_rules, *vcp_rules, *rs_rules]),
        notes=tuple(notes),
    )


def _score_trend_template(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    config: ScreenConfig,
) -> tuple[float, list[RuleEvaluation]]:
    sma50 = _simple_moving_average(closes, config.sma_short)
    sma150 = _simple_moving_average(closes, config.sma_mid)
    sma200 = _simple_moving_average(closes, config.sma_long)
    ema50 = _exponential_moving_average(closes, config.ema_short)
    ema200 = _exponential_moving_average(closes, config.ema_long)
    sma200_prior = _moving_average_ending_at(
        closes,
        config.sma_long,
        len(closes) - config.sma_long_slope_days,
    )
    three_month_return = _trailing_return_from_values(
        closes,
        config.return_lookback_days,
    )
    three_month_return_detail = (
        f"{config.return_lookback_days}d return {three_month_return:.2%} "
        f"vs required {config.min_return_3mo_pct:.2%}"
        if three_month_return is not None
        else f"needs {config.return_lookback_days} bars for 3-month return"
    )
    close = closes[-1]
    high_52w = max(highs[-config.high_low_window :])
    low_52w = min(lows[-config.high_low_window :])
    avg_volume_50 = _mean(volumes[-50:])

    rules = [
        RuleEvaluation(
            "price_above_minimum",
            close > config.min_price,
            f"close {close:.2f} vs required > {config.min_price:.2f}",
        ),
        RuleEvaluation(
            "price_above_50sma",
            close > sma50,
            f"close {close:.2f} vs 50SMA {sma50:.2f}",
        ),
        RuleEvaluation(
            "price_above_50ema",
            close > ema50,
            f"close {close:.2f} vs 50EMA {ema50:.2f}",
        ),
        RuleEvaluation(
            "price_above_150sma",
            close > sma150,
            f"close {close:.2f} vs 150SMA {sma150:.2f}",
        ),
        RuleEvaluation(
            "price_above_200sma",
            close > sma200,
            f"close {close:.2f} vs 200SMA {sma200:.2f}",
        ),
        RuleEvaluation(
            "price_above_200ema",
            close > ema200,
            f"close {close:.2f} vs 200EMA {ema200:.2f}",
        ),
        RuleEvaluation(
            "moving_average_stack",
            sma50 > sma150 > sma200,
            f"50SMA {sma50:.2f}, 150SMA {sma150:.2f}, 200SMA {sma200:.2f}",
        ),
        RuleEvaluation(
            "rising_200sma",
            sma200 > sma200_prior,
            f"200SMA {sma200:.2f} vs {config.sma_long_slope_days} days ago {sma200_prior:.2f}",
        ),
        RuleEvaluation(
            "within_25pct_of_52w_high",
            close >= high_52w * (1.0 - config.max_below_52w_high_pct),
            f"close {close:.2f}, 52w high {high_52w:.2f}",
        ),
        RuleEvaluation(
            "at_least_30pct_above_52w_low",
            close >= low_52w * (1.0 + config.min_above_52w_low_pct),
            f"close {close:.2f}, 52w low {low_52w:.2f}",
        ),
        RuleEvaluation(
            "at_least_40pct_return_3mo",
            three_month_return is not None
            and three_month_return >= config.min_return_3mo_pct,
            three_month_return_detail,
        ),
        RuleEvaluation(
            "liquid_volume",
            avg_volume_50 > config.min_avg_volume_50d,
            (
                f"50d avg volume {avg_volume_50:.0f} "
                f"vs required > {config.min_avg_volume_50d:.0f}"
            ),
        ),
    ]
    return _points_from_rules(rules, maximum=50.0), rules


def _score_vcp_setup(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    config: ScreenConfig,
) -> tuple[float, list[RuleEvaluation], float | None]:
    lookback = config.vcp_lookback_days
    pocket = config.vcp_pocket_days
    if len(closes) < lookback + 21:
        return 0.0, [RuleEvaluation("vcp_history", False, "not enough bars")], None

    ranges = []
    for start in range(len(closes) - lookback, len(closes), pocket):
        pocket_high = max(highs[start : start + pocket])
        pocket_low = min(lows[start : start + pocket])
        ranges.append((pocket_high - pocket_low) / pocket_high)

    recent_range = ranges[-1]
    first_range = ranges[0]
    range_contraction = recent_range < ranges[-2] and recent_range <= first_range * 0.75
    avg_volume_10 = _mean(volumes[-10:])
    avg_volume_30 = _mean(volumes[-30:])
    avg_volume_50 = _mean(volumes[-50:])
    tight_close = _coefficient_of_variation(closes[-10:]) <= config.tight_close_max_pct
    pivot = max(highs[-21:-1])
    close = closes[-1]
    near_pivot = close >= pivot * (1.0 - config.near_pivot_pct)
    breakout_volume = close > pivot and volumes[-1] >= avg_volume_50 * config.breakout_volume_multiplier

    rules = [
        RuleEvaluation(
            "vcp_range_contraction",
            range_contraction,
            "range pockets: " + ", ".join(f"{value:.1%}" for value in ranges),
        ),
        RuleEvaluation(
            "volume_dry_up",
            avg_volume_10 <= avg_volume_30 * config.volume_dry_up_ratio,
            f"10d avg {avg_volume_10:.0f} vs 30d avg {avg_volume_30:.0f}",
        ),
        RuleEvaluation(
            "tight_recent_closes",
            tight_close,
            f"10d close variation {_coefficient_of_variation(closes[-10:]):.2%}",
        ),
        RuleEvaluation(
            "near_pivot",
            near_pivot,
            f"close {close:.2f} vs pivot {pivot:.2f}",
        ),
        RuleEvaluation(
            "breakout_volume",
            breakout_volume,
            (
                f"close {close:.2f}, pivot {pivot:.2f}, volume {volumes[-1]:.0f}, "
                f"50d avg volume {avg_volume_50:.0f}"
            ),
        ),
    ]

    score = 0.0
    if rules[0].passed:
        score += 8.0
    if rules[1].passed:
        score += 7.0
    if rules[2].passed:
        score += 7.0
    if rules[3].passed:
        score += 5.0
    if rules[4].passed:
        score += 3.0
    return score, rules, pivot


def _score_relative_strength(
    stock_bars: Sequence[DailyBar],
    benchmark_bars: Sequence[DailyBar] | None,
    config: ScreenConfig,
) -> tuple[float, float | None, list[RuleEvaluation]]:
    if benchmark_bars is None:
        return 0.0, None, []

    stock_return = _trailing_return(stock_bars, config.rs_lookback_days)
    benchmark_return = _trailing_return(benchmark_bars, config.rs_lookback_days)
    if stock_return is None or benchmark_return is None:
        return (
            0.0,
            None,
            [
                RuleEvaluation(
                    "relative_strength_history",
                    False,
                    f"needs {config.rs_lookback_days} bars for stock and benchmark",
                )
            ],
        )

    relative_strength_pct = (stock_return - benchmark_return) * 100.0
    if relative_strength_pct >= 15.0:
        score = 20.0
    elif relative_strength_pct >= 5.0:
        score = 15.0
    elif relative_strength_pct >= 0.0:
        score = 10.0
    elif relative_strength_pct >= -5.0:
        score = 5.0
    else:
        score = 0.0

    return (
        score,
        relative_strength_pct,
        [
            RuleEvaluation(
                "benchmark_relative_strength",
                relative_strength_pct >= 0.0,
                f"stock return minus benchmark return {relative_strength_pct:.2f}%",
            )
        ],
    )


def _trailing_return(bars: Sequence[DailyBar], lookback_days: int) -> float | None:
    ordered = tuple(sorted(bars, key=lambda bar: bar.date))
    if len(ordered) <= lookback_days:
        return None
    return _trailing_return_from_values(
        [bar.close for bar in ordered],
        lookback_days,
    )


def _trailing_return_from_values(
    values: Sequence[float],
    lookback_days: int,
) -> float | None:
    if len(values) <= lookback_days:
        return None
    start = values[-lookback_days - 1]
    end = values[-1]
    if start <= 0:
        return None
    return (end - start) / start


def _label_for_score(score: float, breakout: bool) -> str:
    if score >= 85.0 and breakout:
        return "breakout_candidate"
    if score >= 75.0:
        return "watchlist"
    if score >= 60.0:
        return "building_setup"
    return "avoid_for_now"


def _required_filters_passed(rules: Sequence[RuleEvaluation]) -> bool:
    passed_rule_names = {rule.name for rule in rules if rule.passed}
    return REQUIRED_FILTER_RULES.issubset(passed_rule_names)


def _inside_candle_formed(bars: Sequence[DailyBar]) -> bool:
    if len(bars) < 2:
        return False

    previous = bars[-2]
    latest = bars[-1]
    return latest.high <= previous.high and latest.low >= previous.low


def _points_from_rules(rules: Iterable[RuleEvaluation], maximum: float) -> float:
    rule_list = list(rules)
    if not rule_list:
        return 0.0
    return sum(1 for rule in rule_list if rule.passed) / len(rule_list) * maximum


def _simple_moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"need {window} values, got {len(values)}")
    return _mean(values[-window:])


def _exponential_moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"need {window} values, got {len(values)}")

    smoothing = 2.0 / (window + 1)
    ema = _mean(values[:window])
    for value in values[window:]:
        ema = (value - ema) * smoothing + ema
    return ema


def _moving_average_ending_at(
    values: Sequence[float], window: int, end_index: int
) -> float:
    if end_index < window:
        raise ValueError(f"need at least {window} values before end_index")
    return _mean(values[end_index - window : end_index])


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return sum(values) / len(values)


def _coefficient_of_variation(values: Sequence[float]) -> float:
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance**0.5 / mean if mean else 0.0


def _normalize_column(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_date(value: str) -> date:
    cleaned = value.strip()
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return datetime.strptime(cleaned, "%d-%m-%Y").date()


def _parse_float(value: str, column: str, path: Path) -> float:
    cleaned = value.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{path}: could not parse {column} value {value!r}") from exc
