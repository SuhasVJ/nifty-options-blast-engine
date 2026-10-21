# MCX Natural Gas Signal Engine

## Scope and safety
- Instrument: MCX Natural Gas futures only (not options, not Natural Gas Mini).
- Modes: intraday and swing signals.
- Execution: signal-only. No order placement, modification, cancellation, or position management APIs are used.
- Data adapter: existing Zerodha Kite Connect credentials and MCX instrument master.
- Status: scanner, local dashboard, CSV signal history, indicator engine, and baseline CSV backtester are now present on the feature branch. They have not yet been executed against the user's Kite account or validated for profitability; treat as development software only.

## Initial balanced strategy
Evaluate only completed candles:
- Intraday: 5-minute candles.
- Swing: 15-minute setup with 60-minute EMA 9/21 and VWAP trend confirmation.
- Indicators: EMA 9/21, RSI 14, ATR 14, session VWAP, 20-candle breakout/breakdown, and relative volume.
- BUY: close above VWAP; EMA9 > EMA21; RSI >= 55; close breaks the previous 20-candle high; volume >= 80% of its 20-candle average; close is not weaker than previous close.
- SELL: inverse conditions, with RSI <= 45 and close below the previous 20-candle low.
- Otherwise WAIT. A setup requires trend, momentum, and structure confirmation; this intentionally prefers fewer signals.
- Initial risk model: stop distance = max(1.2 x ATR, minimum tick guard); target 1 = 1.5R; target 2 = 2R. Levels are analytical estimates from the signal candle, not guaranteed execution prices. Confirm the contract's tick size and validate ATR parameters in backtesting before use.

## Contract selection and data
- Download the current MCX instrument master and select the nearest unexpired row with exchange MCX, name/symbol matching NATURALGAS, and instrument_type FUT.
- Never hardcode the current symbol or expiry; rotate contracts based on the refreshed master and show symbol/expiry in the UI.
- The scanner polls completed 5-minute and 15-minute historical candles, and fetches 60-minute candles when a swing setup requires trend confirmation.
- The scanner excludes incomplete candles and displays API errors in dashboard status. Current data is historical-candle polling, not a tick-by-tick WebSocket stream; check update timestamps before relying on the displayed result.
- Confirm the account has the Kite Connect market-data/historical-data entitlement.

## Signal history and backtesting acceptance criteria
- Append BUY/SELL/WAIT evaluations to `data/natural_gas_signal_history.csv` with timestamp, contract symbol/expiry, timeframe, levels, confidence, reasons, and strategy version; the dashboard reloads the most recent history on restart.
- `app/commodities/natural_gas_backtest.py` runs a time-ordered baseline backtest using next-candle-open entries, configurable slippage/cost points, stop/target checks, and conservative stop-first ordering if both are touched. Convert actual brokerage, exchange charges, taxes, spread and slippage into price points before configuring costs; contract roll and continuous-futures adjustments still require explicit validation.
- Report trade count, win rate, expectancy after costs, profit factor, max drawdown, average R, long/short breakdown, and performance by month and market regime.
- Split development and validation periods chronologically; do not optimize and report results on the same period.
- Paper-trade signals before any live reliance. No profitability claim is implied by the indicator rules.

## Dashboard
Separate Natural Gas section/page; do not modify NIFTY or GOLDM signal thresholds:
- Live connection, selected contract, expiry, last tick timestamp, freshness status.
- Intraday and Swing tabs.
- BUY / SELL / WAIT with entry, stop, target 1/2, risk-reward, confidence, and human-readable reasons.
- Signal history table and downloadable backtest report.
- Clear stale-data and disconnected warnings.

## Running locally
1. Configure `KITE_API_KEY` and `KITE_ACCESS_TOKEN` in the project's `.env` file. Never commit credentials.
2. Install the repository dependencies in the existing virtual environment.
3. From the repository root, run `python natural_gas_live.py`.
4. Open `http://127.0.0.1:8767`. Stop with Ctrl+C. This process does not submit orders.
5. To backtest an authorized OHLCV CSV, run `python natural_gas_backtest.py --csv path/to/candles.csv --timeframe intraday --slippage-points 0.05 --cost-points-per-side 0.0`. The CSV must contain `date,open,high,low,close,volume`; calibrate all-in costs before interpreting results.

## Implementation status and known limitations
- CI unit tests have been added but their result must be checked in GitHub Actions; the model environment could not clone GitHub to execute them locally.
- No live tick stream: scanner polls historical candles once per minute. Dashboard price is the last completed candle close, not a live executable quote.
- Backtest is a baseline single-position model using target 1; it does not yet model partial exits, contract-specific lot sizing, expiry roll, full exchange/brokerage schedule, or monthly/regime reports.
- Validate MCX instrument-master matching, Kite entitlements, timestamps, actual charges and slippage, and backtest on chronologically separated periods. Paper-trade before relying on signals. No profitability claim is implied.
