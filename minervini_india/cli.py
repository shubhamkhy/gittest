"""Command-line interface for the Indian Minervini screener."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

from .screener import (
    DailyBar,
    ScreenResult,
    load_csv_history,
    load_yahoo_history,
    screen_universe,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        symbols = _resolve_symbols(args.symbols, args.symbols_file)
        histories = _load_histories(
            symbols=symbols,
            data_dir=args.data_dir,
            live=args.live,
            period=args.period,
        )
        benchmark = _load_benchmark(args)
        sector_map = _load_sector_map(args.sector_file)
        results = screen_universe(
            histories,
            benchmark=benchmark,
            sector_map=sector_map,
        )
        filtered = [
            result
            for result in results
            if result.score >= args.min_score
            and result.label != "insufficient_data"
            and result.required_filters_passed
        ][: args.top]
        _write_results(filtered, args.output)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should convert failures to stderr.
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="indian-minervini",
        description=(
            "Screen Indian stocks with Minervini-inspired trend, VCP, "
            "relative-strength, and risk rules."
        ),
    )
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument(
        "--symbols",
        help="Comma-separated Yahoo-style symbols, e.g. RELIANCE.NS,TCS.NS.",
    )
    symbol_group.add_argument(
        "--symbols-file",
        type=Path,
        help="Text file containing one symbol per line; # comments are ignored.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing CSV files named SYMBOL.csv.",
    )
    source_group.add_argument(
        "--live",
        action="store_true",
        help="Fetch live history from Yahoo Finance via yfinance.",
    )
    parser.add_argument(
        "--benchmark",
        default="^NSEI",
        help="Live benchmark symbol for relative strength; default: ^NSEI.",
    )
    parser.add_argument(
        "--benchmark-data",
        type=Path,
        help="CSV file for benchmark history when using --data-dir.",
    )
    parser.add_argument(
        "--sector-file",
        type=Path,
        help=(
            "Optional CSV with symbol and sector columns. Used to show sector "
            "and count matching stocks per sector."
        ),
    )
    parser.add_argument(
        "--period",
        default="18mo",
        help="Yahoo Finance lookback period when using --live; default: 18mo.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Maximum rows to print after ranking; default: 20.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum normalized score to include; default: 0.",
    )
    parser.add_argument(
        "--output",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format; default: table.",
    )
    return parser


def _resolve_symbols(raw_symbols: str | None, symbols_file: Path | None) -> list[str]:
    if raw_symbols:
        symbols = [symbol.strip().upper() for symbol in raw_symbols.split(",")]
    elif symbols_file:
        symbols = []
        for line in symbols_file.read_text(encoding="utf-8").splitlines():
            clean_line = line.split("#", maxsplit=1)[0].strip()
            if clean_line:
                symbols.append(clean_line.upper())
    else:
        symbols = []

    unique_symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))
    if not unique_symbols:
        raise ValueError("no symbols supplied")
    return unique_symbols


def _load_histories(
    symbols: Sequence[str],
    data_dir: Path | None,
    live: bool,
    period: str,
) -> dict[str, list[DailyBar]]:
    histories: dict[str, list[DailyBar]] = {}
    for symbol in symbols:
        if live:
            histories[symbol] = load_yahoo_history(symbol, period=period)
        elif data_dir:
            histories[symbol] = load_csv_history(data_dir / f"{symbol}.csv")
        else:
            raise ValueError("choose --live or --data-dir")
    return histories


def _load_benchmark(args: argparse.Namespace) -> list[DailyBar] | None:
    if args.live:
        return load_yahoo_history(args.benchmark, period=args.period)
    if args.benchmark_data:
        return load_csv_history(args.benchmark_data)
    return None


def _load_sector_map(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row")

        normalized_fields = {
            field.strip().lower().replace(" ", "_").replace("-", "_"): field
            for field in reader.fieldnames
        }
        missing = [
            field
            for field in ("symbol", "sector")
            if field not in normalized_fields
        ]
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(missing)}")

        sector_map: dict[str, str] = {}
        for row in reader:
            symbol = row[normalized_fields["symbol"]].strip().upper()
            sector = row[normalized_fields["sector"]].strip()
            if symbol and sector:
                sector_map[symbol] = sector
        return sector_map


def _write_results(results: Sequence[ScreenResult], output: str) -> None:
    if output == "json":
        print(json.dumps([result.to_dict() for result in results], indent=2))
    elif output == "csv":
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=[
                "symbol",
                "as_of",
                "close",
                "score",
                "label",
                "trend_score",
                "vcp_score",
                "relative_strength_score",
                "relative_strength_pct",
                "pivot",
                "suggested_stop",
                "required_filters_passed",
                "inside_candle_formed",
                "inside_candle_trigger",
                "inside_candle_stop",
                "ema50",
                "ema200",
                "return_3mo_pct",
                "avg_volume_50d",
                "avg_traded_value_50d",
                "nearest_high",
                "nearest_high_distance_pct",
                "pct_above_50ema",
                "sector",
                "sector_match_count",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_dict())
    else:
        _write_table(results)


def _write_table(results: Sequence[ScreenResult]) -> None:
    if not results:
        print("No symbols matched the filter.")
        return

    rows = [
        [
            _display_symbol(result),
            result.as_of.isoformat() if result.as_of else "-",
            f"{result.close:.2f}" if result.close is not None else "-",
            f"{result.score:.1f}",
            result.label,
            f"{result.return_3mo_pct:.1f}" if result.return_3mo_pct is not None else "-",
            f"{result.ema50:.2f}" if result.ema50 is not None else "-",
            f"{result.ema200:.2f}" if result.ema200 is not None else "-",
            f"{result.avg_volume_50d:.0f}" if result.avg_volume_50d is not None else "-",
            (
                f"{result.avg_traded_value_50d / 10_000_000:.1f}cr"
                if result.avg_traded_value_50d is not None
                else "-"
            ),
            (
                f"{result.nearest_high_distance_pct:.1f}"
                if result.nearest_high_distance_pct is not None
                else "-"
            ),
            (
                f"{result.pct_above_50ema:.1f}"
                if result.pct_above_50ema is not None
                else "-"
            ),
            (
                f"{result.inside_candle_trigger:.2f}"
                if result.inside_candle_trigger is not None
                else "-"
            ),
            (
                f"{result.inside_candle_stop:.2f}"
                if result.inside_candle_stop is not None
                else "-"
            ),
            result.sector or "-",
            str(result.sector_match_count) if result.sector_match_count is not None else "-",
            f"{result.pivot:.2f}" if result.pivot is not None else "-",
            f"{result.suggested_stop:.2f}" if result.suggested_stop is not None else "-",
        ]
        for result in results
    ]
    headers = [
        "symbol",
        "as_of",
        "close",
        "score",
        "label",
        "3m%",
        "50ema",
        "200ema",
        "avg_vol",
        "avg_value",
        "dist_high%",
        "ext_50ema%",
        "inside_buy",
        "inside_sl",
        "sector",
        "sector_hits",
        "pivot",
        "stop",
    ]
    widths = [
        max(len(str(row[index])) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def _display_symbol(result: ScreenResult) -> str:
    if result.inside_candle_formed:
        return f"* {result.symbol}"
    return result.symbol


if __name__ == "__main__":
    raise SystemExit(main())
