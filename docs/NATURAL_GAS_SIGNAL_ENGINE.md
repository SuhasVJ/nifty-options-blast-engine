# MCX Natural Gas Signal Engine

## Scope and safety
- Instrument: MCX Natural Gas futures only (not options, not Natural Gas Mini).
- Modes: intraday and swing signals.
- Execution: signal-only. No order placement, modification, cancellation, or position management APIs are used.
- Data adapter: existing Zerodha Kite Connect credentials and MCX instrument master.
- Status: signal calculation foundation added; live scanner, dashboard view, durable history, and end-to-end backtest integration remain to be wired and validated. Do not treat this branch as a running live signal service.

## Initial balanced strategy
Evaluate only completed candles:
- Intraday: 5-minute candles.
- Swing: 15-minute candles for setup and 60-minute trend confirmation (multi-timeframe confirmation must be added in the scanner integration).
- Indicators: EMA 9/21, RSI 14, ATR 14, session VWAP, 20-candle breakout/breakdown, and relative volume.
- BUY: close above VWAP; EMA9 > EMA21; RSI >= 55; close breaks the previous 20-candle high; volume >= 80% of its 20-candle average; close is not weaker than previous close.
- SELL: inverse conditions, with RSI <= 45 and close below the previous 20-candle low.
- Otherwise WAIT. A setup requires trend, momentum, and structure confirmation; this intentionally prefers fewer signals.
- Initial risk model: stop distance = max(1.2 x ATR, minimum tick guard); target 1 = 1.5R; target 2 = 2R. Levels are analytical estimates from the signal candle, not guaranteed execution prices. Confirm the contract's tick size and validate ATR parameters in backtesting before use.

## Contract selection and data
- Download the current MCX instrument master and select the nearest unexpired row with exchange MCX, name/symbol matching NATURALGAS, and instrument_type FUT.
- Never hardcode the current symbol or expiry; rotate contracts based on the refreshed master and show symbol/expiry in the UI.
- Kite historical data supports candle intervals such as 5minute and 15minute; fetch 60-minute data using the supported hourly interval for the SDK/account.
- Reject stale/missing ticks and incomplete candles. Do not publish a fresh signal when market data is stale, the token is unavailable, or the contract rolls.
- Confirm the account has the Kite Connect market-data/historical-data entitlement.

## Signal history and backtesting acceptance criteria
- Persist every signal and WAIT evaluation with timestamp, contract symbol/expiry, timeframe, candle timestamp, entry/stop/targets, score, reasons, data freshness, and strategy version.
- Backtest using time-ordered candles and signals computed only from information available at that time. Include brokerage, exchange charges, taxes, slippage, spread, contract expiry/roll, and conservative assumptions for stop/target ordering when both are touched in one candle.
- Report trade count, win rate, expectancy after costs, profit factor, max drawdown, average R, long/short breakdown, and performance by month and market regime.
- Split development and validation periods chronologically; do not optimize and report results on the same period.
- Paper-trade signals before any live reliance. No profitability claim is implied by the indicator rules.

## Planned dashboard
Separate Natural Gas section/page; do not modify NIFTY or GOLDM signal thresholds:
- Live connection, selected contract, expiry, last tick timestamp, freshness status.
- Intraday and Swing tabs.
- BUY / SELL / WAIT with entry, stop, target 1/2, risk-reward, confidence, and human-readable reasons.
- Signal history table and downloadable backtest report.
- Clear stale-data and disconnected warnings.

## Implementation status
This branch currently contains the pure indicator/signal engine and unit-test scaffold. Next work is to connect the Kite candle/tick adapter, contract selector, signal history store, dashboard publisher/UI, and repeatable backtest runner; then run tests and validate using historical data and paper-trading observations.
