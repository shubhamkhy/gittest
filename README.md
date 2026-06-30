# Indian Minervini Screener

A small Python screening system for Indian equities. It ranks NSE/BSE symbols
using Mark Minervini-inspired concepts:

- trend-template checks using 50/150/200-day moving averages
- required price confirmation above the 50-day and 200-day EMAs
- required 40% or better return over roughly the last three months
- required current price within 10% of the nearest recent high
- required latest close at or above the previous day's close
- required latest close above the latest open
- price location versus 52-week high and low
- liquidity filter using 50-day average volume
- volatility contraction pattern (VCP) style setup checks
- breakout volume confirmation
- inside-candle marker when the latest high/low sits within the prior day's range
- optional relative strength versus a benchmark such as NIFTY 50 (`^NSEI`)
- suggested stop level based on a predefined maximum risk percentage

This project is an educational screening tool, not financial advice. Always
validate fundamentals, news, liquidity, slippage, and position sizing before
placing any trade.

## Install

Core CSV screening uses only the Python standard library:

```bash
python3 -m pip install -e .
```

For live Yahoo Finance data, install the optional live extra:

```bash
python3 -m pip install -e ".[live]"
```

## Run with live NSE symbols

Yahoo Finance typically uses `.NS` for NSE stocks and `.BO` for BSE stocks.

```bash
indian-minervini \
  --symbols RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS \
  --live \
  --benchmark ^NSEI \
  --top 10
```

You can also use the included example symbol file:

```bash
indian-minervini \
  --symbols-file examples/nse_symbols.txt \
  --live \
  --top 20 \
  --min-score 60
```

## Run with local CSV data

Create one CSV per symbol, named exactly like the symbol:

```text
data/
  RELIANCE.NS.csv
  TCS.NS.csv
  NIFTY.csv
```

Each CSV needs these columns:

```csv
Date,Open,High,Low,Close,Volume
2026-01-01,100,105,99,104,150000
```

Then run:

```bash
indian-minervini \
  --symbols RELIANCE.NS,TCS.NS \
  --data-dir data \
  --benchmark-data data/NIFTY.csv \
  --output table
```

Supported outputs are `table`, `json`, and `csv`.

By default, CLI results only include stocks that pass the mandatory filters:

- latest close above the 50-day EMA
- latest close above the 200-day EMA
- at least 40% return over the last 63 trading days, roughly three months
- 50-day average daily volume above 100,000 shares
- latest close above 60
- latest close within 10% of the highest high from the prior 20 trading days
- latest close at or above the previous day's close
- latest close above the latest open

## How the score works

The normalized score is built from three components:

1. **Trend template, 50 points**
   - close above 50/150/200-day moving averages
   - close above the 50-day and 200-day EMAs
   - close above 60
   - close within 10% of the highest high from the prior 20 trading days
   - latest close at or above the previous day's close
   - latest close above the latest open
   - 50SMA > 150SMA > 200SMA
   - 200SMA rising versus 20 trading days ago
   - close within 25% of 52-week high
   - close at least 30% above 52-week low
   - return over the last 63 trading days is at least 40%
   - 50-day average daily volume above 100,000 shares
2. **VCP/setup, 30 points**
   - recent price range contraction
   - volume dry-up
   - tight recent closes
   - close near the pivot
   - breakout above pivot on strong volume
3. **Relative strength, 20 points**
   - stock return versus benchmark return over roughly six months

If no benchmark is supplied, relative strength is not scored and the remaining
80 points are normalized to 100.

## Output labels

- `breakout_candidate`: high score with breakout-volume confirmation
- `watchlist`: strong trend/setup characteristics, but no confirmed breakout
- `building_setup`: improving structure that still needs confirmation
- `avoid_for_now`: does not currently meet enough rules
- `insufficient_data`: fewer than 260 daily bars

The table output prefixes the symbol with `*` when the latest completed candle
is a strict inside candle: latest high is below the previous high, latest low is
above the previous low, and both candles have valid high/low ranges. CSV and JSON
outputs expose the same signal as `inside_candle_formed`.

The `suggested_stop` value is a simple 8% risk reference from the latest close.
It is not a promise of execution or loss control; gap risk and liquidity still
matter.

## Run tests

```bash
python3 -m unittest discover -s tests
```
