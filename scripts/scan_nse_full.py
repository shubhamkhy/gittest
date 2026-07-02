"""Scan the full NSE symbol list with batched Yahoo Finance downloads."""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

import yfinance as yf

from minervini_india.cli import _write_results
from minervini_india.screener import DailyBar, score_stock

DEFAULT_SYMBOL_FILE = Path(__file__).resolve().parent.parent / "examples" / "nse_all_symbols.txt"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "results"
PERIOD = "18mo"
CHUNK_SIZE = 100


def frame_to_bars(frame) -> list[DailyBar]:
    required = ["Open", "High", "Low", "Close", "Volume"]
    if frame is None or frame.empty or any(column not in frame.columns for column in required):
        return []
    clean = frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    bars: list[DailyBar] = []
    for index, row in clean.iterrows():
        bar_date = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        close = float(row["Close"])
        volume = float(row["Volume"])
        if close <= 0 or volume < 0:
            continue
        bars.append(
            DailyBar(
                date=bar_date,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=close,
                volume=volume,
            )
        )
    return bars


def ticker_frame(downloaded, symbol: str, chunk_size: int):
    if downloaded is None or downloaded.empty:
        return None
    if chunk_size == 1 and not hasattr(downloaded.columns, "levels"):
        return downloaded
    if hasattr(downloaded.columns, "levels"):
        level_0 = downloaded.columns.get_level_values(0)
        level_1 = downloaded.columns.get_level_values(1)
        if symbol in level_0:
            return downloaded[symbol]
        if symbol in level_1:
            return downloaded.xs(symbol, level=1, axis=1)
    return None


def download_many(symbols: list[str], period: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            tickers=" ".join(symbols),
            period=period,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )


def load_symbols(path: Path) -> list[str]:
    return [
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def scan_symbols(symbols: list[str], period: str) -> list:
    results = []
    loaded = 0
    total_chunks = (len(symbols) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for start in range(0, len(symbols), CHUNK_SIZE):
        chunk = symbols[start : start + CHUNK_SIZE]
        chunk_number = start // CHUNK_SIZE + 1
        print(
            f"Downloading chunk {chunk_number}/{total_chunks}: "
            f"{chunk[0]} ... {chunk[-1]}",
            flush=True,
        )
        try:
            downloaded = download_many(chunk, period=period)
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped chunk due to download error: {exc}", flush=True)
            continue
        for symbol in chunk:
            bars = frame_to_bars(ticker_frame(downloaded, symbol, len(chunk)))
            if not bars:
                continue
            loaded += 1
            results.append(score_stock(symbol, bars, benchmark=None))

    print(f"Loaded price history for {loaded}/{len(symbols)} symbols.", flush=True)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the full NSE universe.")
    parser.add_argument(
        "--symbols-file",
        type=Path,
        default=DEFAULT_SYMBOL_FILE,
        help=f"Symbol list file (default: {DEFAULT_SYMBOL_FILE})",
    )
    parser.add_argument(
        "--output",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format for passing stocks.",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save scan output.",
    )
    parser.add_argument(
        "--period",
        default=PERIOD,
        help="Yahoo Finance lookback period (default: 18mo).",
    )
    args = parser.parse_args(argv)

    if not args.symbols_file.exists():
        print(f"error: symbol file not found: {args.symbols_file}", file=sys.stderr)
        return 2

    symbols = load_symbols(args.symbols_file)
    print(f"Scanning {len(symbols)} NSE symbols with {args.period} Yahoo Finance data...")
    print("Benchmark scoring disabled to reduce rate-limit issues.", flush=True)

    results = scan_symbols(symbols, period=args.period)
    passing = [
        result
        for result in sorted(results, key=lambda item: item.score, reverse=True)
        if result.required_filters_passed and result.label != "insufficient_data"
    ]

    print(
        f"\n{len(passing)} symbols passed mandatory filters "
        "(50/200 EMA, 40% 3m return, liquidity, price > 60, 7-10% from high "
        "(inside 6-10% with score >= 77, otherwise 7-10%), score >= 75, "
        "inside candle or VCP >= 21).",
        flush=True,
    )
    print("All passing results:\n", flush=True)
    _write_results(passing, args.output)

    args.save_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = args.save_dir / f"picks_{stamp}.{args.output if args.output != 'table' else 'txt'}"
    if args.output == "table":
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _write_results(passing, "table")
        save_path.write_text(buffer.getvalue(), encoding="utf-8")
    else:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _write_results(passing, args.output)
        save_path.write_text(buffer.getvalue(), encoding="utf-8")

    print(f"\nSaved copy to {save_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
