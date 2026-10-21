# nifty-options-blast-engine

## Seven Horses AI Trading Engine — v1 research workflow

Configured for swing signals on RELIANCE, HDFCBANK, ICICIBANK, SBIN, INFY, TECHM, and HCLTECH. Uses Zerodha Kite Connect for market data where available. This version is **signals-only**: it does not place orders.

### Local setup and run

Activate your existing Python virtual environment from the repository root, then run:

```powershell
python -m app.seven_horses.market_data check
python -m app.seven_horses.market_data history --days 730
python -m app.seven_horses.data_quality
python -m app.seven_horses.signals
python -m app.seven_horses.sizing
python -m app.seven_horses.backtest
```

Run regression tests with:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

The sizing command writes explainable hybrid target weights to `data/seven_horses/latest_allocations.json`; it combines 30% liquidity, 25% strategic weightage, and 45% signal strength by default. Only `BUY_CONFIRMED` and `BUY_WATCH` signals are eligible; per-stock exposure is capped at 25% and total deployed exposure at 80%. These are configurable research defaults, not investment recommendations. The backtest writes `data/seven_horses/backtest_summary.json`. The output includes the strategy equity curve, an approximate buy-and-hold price benchmark, trade details, and a method note. Default estimated costs are 10 bps fees plus 5 bps slippage per side; these are assumptions, not verified brokerage costs.

### Backtest limitations

This is a research baseline, not a production-grade simulator. It uses one fully invested long position per symbol, daily candles, fixed ATR-based stops/targets, simplified costs, and a stop-first assumption when both intraday stop and target levels are touched. The benchmark excludes dividends and costs. Taxes, market impact, portfolio-level hybrid sizing inside the backtest, corporate-action verification, and out-of-sample / walk-forward evaluation remain future work.

### Historical data-quality audit

Run `python -m app.seven_horses.data_quality` after downloading history. The audit writes `data/seven_horses/data_quality_report.json` and checks required fields, parseable timestamps (normalized to Asia/Kolkata), numeric and positive prices, OHLC consistency, non-negative volume, duplicate timestamps, ordering, candles on listed full-day exchange holidays, and possible missing trading sessions. It never edits or deletes source candle files. The version-controlled `app/seven_horses/nse_equity_holidays.json` contains NSE Capital Market (Equities) full-day closures for the historical period and includes source circular URLs. Weekday gaps are reported only after weekends and listed holidays are excluded; any unlisted weekday gap remains a warning. Special Muhurat trading sessions are not treated as full-day closures. Review official NSE circulars before extending the calendar. Corporate-action adjustments are explicitly marked `NOT_CHECKED`; verify split/bonus adjustments separately before interpreting long-period returns. Any symbol with an error makes the command exit non-zero. Run `python -m unittest discover -s tests -p "test_*.py" -v` to exercise the validation tests. The standalone sizing module currently produces target weights only; it does not change historical backtest position sizes. Historical results are not a forecast and are not trading advice.

### Safety boundary

No automated order placement is implemented. Review signal reasons, data freshness, backtest assumptions, and risk controls before using any output to inform a manual decision.
