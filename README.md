# nifty-options-blast-engine

## Seven Horses AI Trading Engine — v1 research workflow

Configured for swing signals on RELIANCE, HDFCBANK, ICICIBANK, SBIN, INFY, TECHM, and HCLTECH. Uses Zerodha Kite Connect for market data where available. This version is **signals-only**: it does not place orders.

### Local setup and run

Activate your existing Python virtual environment from the repository root, then run:

```powershell
python -m app.seven_horses.market_data check
python -m app.seven_horses.market_data history --days 730
python -m app.seven_horses.signals
python -m app.seven_horses.backtest
```

Run regression tests with:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

The backtest writes `data/seven_horses/backtest_summary.json`. The output includes the strategy equity curve, an approximate buy-and-hold price benchmark, trade details, and a method note. Default estimated costs are 10 bps fees plus 5 bps slippage per side; these are assumptions, not verified brokerage costs.

### Backtest limitations

This is a research baseline, not a production-grade simulator. It uses one fully invested long position per symbol, daily candles, fixed ATR-based stops/targets, simplified costs, and a stop-first assumption when both intraday stop and target levels are touched. The benchmark excludes dividends and costs. Taxes, market impact, portfolio-level hybrid sizing, corporate-action validation, and out-of-sample / walk-forward evaluation remain future work. Historical results are not a forecast and are not trading advice.

### Safety boundary

No automated order placement is implemented. Review signal reasons, data freshness, backtest assumptions, and risk controls before using any output to inform a manual decision.
