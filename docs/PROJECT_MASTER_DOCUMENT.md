# NIFTY Options Blast Engine — Master Project Document

**Repository:** https://github.com/SuhasVJ/nifty-options-blast-engine  
**Document status:** Living project specification  
**Last updated:** 11 October 2026  
**Current phase:** Supervised, observation-only live validation  
**Next planned validation session:** Monday, 12 October 2026. Confirm the exchange calendar and market hours before running.

## 1. Product vision

Build a Python-based NIFTY 50 options monitoring engine that consumes live market data, evaluates selected option contracts, calculates option Greeks and market-activity signals, and surfaces ranked Call (CE) and Put (PE) candidates.

This is a decision-support and monitoring tool. A high score is a ranking signal, not a guaranteed trade, investment recommendation, or promise of profit.

### Agreed scope
- Underlying: NIFTY 50 only.
- Instruments: NIFTY index options.
- Expiry: monthly expiry is the intended default. Some observed runs selected the nearest available expiry; make the policy explicit in configuration before relying on it.
- Data source: Zerodha Kite Connect REST API and KiteTicker WebSocket.
- Primary use: live observation, signal evaluation, and reporting.
- Automated order placement: not in scope.

## 2. Technology stack

- Python in a local virtual environment (.venv).
- kiteconnect 5.2.2 for Kite Connect REST and WebSocket access.
- NumPy, pandas, and SciPy for data handling and numerical calculations.
- python-dotenv for environment-based configuration and secrets.
- FastAPI and Uvicorn are in requirements.txt for a possible API/monitoring surface; their production readiness and runtime role are not certified.
- Development environment reported: Windows / PowerShell.
- Refer to requirements.txt for pinned dependency versions.

## 3. High-level architecture

    Kite Connect REST
        |
        +--> Load/cache NFO instrument master
        |       |
        |       +--> Filter NIFTY option contracts and expiry/strike universe
        |
    KiteTicker WebSocket
        |
        +--> Subscribe to NIFTY 50 spot + selected option tokens
                |
                v
          Live market-state manager
          (latest prices, OI/volume fields, timestamps, freshness)
                |
                v
          Option analytics / Greeks
          (Delta, Gamma, IV and related values)
                |
                v
          Eligibility rules / data-quality checks
                |
                v
          BlastScoreEngine
          (weighted multi-factor ranking)
                |
                v
          Ranked CE and PE candidates
          (intended top 3 per side)
                |
                v
          Console/reporting and supervised operator review

This is the logical architecture reconstructed from implementation and testing discussions. Verify exact class and module names against the current working tree before treating this as a source-code map.

## 4. Data ingestion and contract selection

### REST / instrument master
- Fetch or reuse a local cache of NFO instrument metadata.
- Filter contracts to NIFTY options.
- Resolve expiry, strike, option type (CE/PE), and instrument token.
- Select a bounded set of contracts around ATM for live monitoring.

### WebSocket
- Subscribe to NIFTY 50 index token 256265 (observed in testing) and selected option tokens.
- Update live state as ticks arrive.
- Recover from disconnects by reconnecting and restoring subscriptions.
- Reject stale or missing market data; stale values must not be treated as current signals.

### Historical debugging snapshots (not current prices)
- One run loaded a local instrument cache containing 1,888 NIFTY contracts.
- One live-chain run tracked 42 contracts around ATM.
- A previous test snapshot showed NIFTY at 22,231.8, ATM 22,250, expiry 13 October 2026. These are historical debugging values only and must never be reused as live prices.

## 5. Candidate eligibility rules

Initial agreed filters:

| Metric | Initial rule | Notes |
|---|---:|---|
| Absolute Delta | abs(delta) > 0.30 | Use absolute delta for eligibility so CE and PE can both qualify. Preserve signed delta for interpretation/reporting. |
| Implied Volatility | IV < 15% | Keep IV representation consistent as a percentage, not a decimal fraction. |
| Gamma | gamma > 0.0012 | Validate Greek calculation and units/assumptions. |
| Data freshness | Required | Reject candidates with stale or incomplete quote/underlying/analytics inputs. |
| History readiness | Required | Do not score momentum or other history-dependent factors until sufficient fresh observations exist. |

These are configurable screening rules, not universal trading truths. Validate them through observations and historical analysis before using them for live trading decisions.

## 6. Blast Score — initial factor weights

| Factor | Weight |
|---|---:|
| Momentum | 25 |
| Delta | 15 |
| Gamma | 15 |
| Open-interest change / OI signal | 15 |
| Implied volatility | 10 |
| Volume | 10 |
| NIFTY underlying movement | 10 |
| **Total** | **100** |

Implementation requirements:
1. Normalize factor values before combining them so different scales do not dominate accidentally.
2. Document the direction of each factor (for example, whether lower IV scores better).
3. Define missing-data behaviour explicitly; do not silently treat missing values as zero or favourable.
4. Keep eligibility filtering separate from ranking.
5. Log factor-level contributions alongside the final score for explainability.
6. Treat weights as an initial hypothesis to test, not evidence of predictive edge.

## 7. Greeks and analytics considerations

A historical test reported approximately:
- Spot: 22,231.8
- Strike: 22,250
- Option price: 135.35
- IV: 13.04%
- Delta: 0.5031
- Gamma: 0.001176
- Vega: 10.3803
- Theta/day: -15.3472

This is a historical test example, not a current signal. Document and test:
- Pricing model and option type handling.
- Time to expiry and timezone conventions.
- Risk-free rate and dividend/yield assumptions.
- IV solver bounds, convergence failures, and invalid/zero prices.
- Greek units (per index point, per 1% IV change, or otherwise).
- Behaviour near expiry and for illiquid contracts.
- Reconciliation against known reference calculations.

## 8. Reliability and data-quality behaviour

Protections discussed or observed:
- Local instrument cache.
- WebSocket connection and subscription recovery.
- Re-subscription to NIFTY and selected option tokens after reconnect.
- Stale-data cleanup / freshness checks.
- Bounded near-ATM subscription set.
- Console output for live underlying and option state.

Before production use, verify each protection with repeatable tests and add explicit diagnostics for:
- Last tick timestamp per instrument.
- WebSocket connection state and reconnect count.
- Subscription count and failures.
- Missing, crossed, zero, or stale prices.
- API throttling/errors and instrument-cache age.
- Greek solver failures.
- Time from tick receipt to candidate output.

## 9. Testing status and limitations

A recent development update reported 15 test modules passing. This is encouraging but is not proof of production readiness.

Outstanding validation:
- Confirm the full test suite passes from a clean environment.
- Add/verify tests for stale data, reconnect recovery, missing ticks, malformed quotes, and expiry rollover.
- Test score normalization and missing-factor handling.
- Validate monthly-expiry selection and holiday/expiry changes.
- Test through a full market session and during network interruptions.
- Confirm logs can diagnose unexpected signals.
- Review Kite Connect rate limits and operational error handling.
- Document safe stop/restart steps.

## 10. Operating rules for initial live observation

1. Run in observation-only mode.
2. Do not enable automated order placement.
3. Confirm credentials and API session validity before market open.
4. Confirm machine clock/timezone, selected expiry, ATM strike, subscription count, and initial spot tick.
5. Verify timestamps advance and stale instruments are excluded.
6. Record candidate outputs, factor contributions, errors, reconnects, and operator observations.
7. Compare candidates with actual market context; do not assume the highest score is a trade.
8. Stop if data becomes stale, subscriptions fail repeatedly, output is inconsistent, or the feed is disconnected.
9. Review logs and record defects after the session before changing scoring rules.

The first session is a controlled validation exercise, not production approval.

## 11. Security and compliance rules

- Never commit Kite API secrets, access tokens, passwords, or .env files.
- Load credentials from environment variables or a local ignored secrets file.
- Rotate credentials if exposed in logs, screenshots, commits, or chat.
- Use authorized data access and follow broker API terms and exchange rules.
- Do not place orders automatically in the current phase.
- Any future execution feature requires separate design review, risk controls, explicit authorization, and extensive paper testing.

## 12. Roadmap

### Milestone A — Supervised live validation
- Confirm clean startup and valid authentication.
- Validate live NIFTY and option ticks.
- Validate contract/expiry selection.
- Verify stale-data and reconnect behaviour.
- Capture ranked CE/PE candidates and factor contributions.
- Complete post-session review and defect list.

Exit criteria: documented full-session observation run with reliable timestamps, explainable outputs, no unresolved critical data-integrity issues, and repeatable startup/shutdown instructions.

### Milestone B — Hardening
- Improve structured logging and health diagnostics.
- Add resilience and edge-case tests.
- Make expiry policy, thresholds, weights, and history window explicit configuration.
- Add clear health summary and deterministic report format.
- Validate API rate-limit behaviour and recovery.

### Milestone C — Historical evaluation / paper validation
- Store suitable market history or derived snapshots where permitted.
- Evaluate behaviour across volatility and trend regimes.
- Include spreads, slippage, liquidity, and transaction costs in performance studies.
- Prevent look-ahead bias and selection bias.
- Keep paper evaluation separate from live execution.

### Milestone D — Operational dashboard (optional)
- Decide whether FastAPI is the API layer and define the UI separately.
- Expose health, feed freshness, active contracts, score breakdowns, and recent events.
- Add monitoring and alerts only after data-quality semantics are stable.

### Milestone E — Production-readiness review
Production approval must be a deliberate gate, not inferred from a successful local run. Require documented tests, monitoring, failure recovery, security review, operational runbook, and a clear statement of intended use.

## 13. Definition of done for the current phase

- [ ] Clean start succeeds using documented steps.
- [ ] Authentication and WebSocket subscriptions are confirmed.
- [ ] NIFTY and selected option ticks update with current timestamps.
- [ ] Stale/incomplete inputs are excluded from scoring.
- [ ] Eligibility filters and factor weights match this specification.
- [ ] CE and PE ranking output is explainable.
- [ ] Reconnect/re-subscription behaviour is observed or tested.
- [ ] Logs and post-session summary are saved.
- [ ] No critical defect remains open.
- [ ] System remains observation-only.

## 14. Change control

When changing a threshold, weight, expiry policy, pricing assumption, data source, or scoring formula:
1. Update this document.
2. Add or update tests.
3. Record rationale and expected effect.
4. Compare results against a baseline.
5. Do not tune rules solely to fit one session.
6. Keep a dated note of the change and validation outcome.

## 15. Current status summary

Working direction: Python + Kite Connect; cached instrument metadata; WebSocket feed; bounded near-ATM contract set; Greeks and multi-factor ranking; top CE/PE candidate reporting.

Current phase: supervised live validation, observation-only.

Not yet established: production readiness, stable predictive edge, long-duration reliability, complete operational monitoring, and safe automated execution. Automated execution is not in scope.

---
This document consolidates project decisions and test notes available as of 11 October 2026. Details not verified directly against the latest source tree are described as the agreed design or historical observations, not guarantees about the current code.
