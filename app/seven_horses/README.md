# Seven Horses AI Trading Engine — v1

## Locked configuration
- Universe: RELIANCE, HDFCBANK, ICICIBANK, SBIN, INFY, TECHM, HCLTECH (NSE cash equities)
- Horizon: swing trading
- Horse sizing: hybrid (market-cap/index-weight base plus bounded relative-volume adjustment)
- Visualization: animated racetrack
- Execution: manual, signals-only; no order placement
- Provider: Zerodha Kite Connect where available

## Implementation plan
1. **Market data (current slice):** validate Kite session, resolve live NSE EQ tokens from the daily instrument master, download daily candles, and stream full-mode WebSocket ticks to JSONL. Do not hard-code instrument tokens.
2. **Data quality:** detect missing candles, duplicates/out-of-order ticks, stale quotes, reconnects, and token expiry. Store receive time and exchange timestamp.
3. **Signals:** deterministic 20/50-day EMA trend, 20-day momentum, RSI, ATR-based volatility and relative volume. Emit BUY WATCH, BUY CONFIRMED, HOLD or EXIT WATCH with explicit reasons. Keep AI explanations separate from deterministic rules.
4. **Hybrid sizing and race state:** base size from market capitalization or official index weight, then apply a capped relative-volume factor. Horse position comes from normalized swing performance/momentum, not nominal share price.
5. **Backtesting:** walk-forward testing, transaction costs, slippage, no look-ahead bias and benchmark comparison. Report CAGR, maximum drawdown, win rate, expectancy, turnover and per-stock results.
6. **Dashboard:** animated race, session/data health, sizing mode, signal explanations, stop/target references and signal history.
7. **Paper-trading gate:** reconcile signals and timestamps for several weeks before considering any future execution work. Live order execution is out of scope for v1.

## Windows PowerShell setup
Use the existing project virtual environment. The repository requirements already include kiteconnect and python-dotenv.

Create a repository-root .env file (never commit it):
    KITE_API_KEY=your_api_key
    KITE_ACCESS_TOKEN=your_current_trading_day_access_token
    SEVEN_HORSES_EXCHANGE=NSE
    SEVEN_HORSES_INTERVAL=day
    SEVEN_HORSES_HISTORY_DAYS=730

Kite access tokens normally expire at the end of the trading day. Refresh the session through your usual Kite login flow. Never share or commit secrets.

## Run from repository root
    python -m app.seven_horses.market_data check
    python -m app.seven_horses.market_data history --days 730
    python -m app.seven_horses.market_data stream

Data is written to data/seven_horses/. Run the stream during market hours and stop with Ctrl+C.

## Validation status
The source slice has been committed to a feature branch. Live authentication and market-data validation must be run on the user's machine because this environment does not have the user's local .env or authenticated Kite session. Run the check command first; proceed only when all seven symbols resolve.
