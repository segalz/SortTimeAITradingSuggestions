# Master Implementation Plan: MCP Short-Term AI Trading Suggestions Engine

## Overview & Objective
This project builds a local, high-precision, short-term (1h–12h horizon, holding hours to a few days) AI trading recommendation engine exposed as a **Model Context Protocol (MCP) Server**.

The system combines:
1. **Quantitative Time-Series Forecasting**: Evaluated via a strict walk-forward harness, baseline comparisons (Naive drift, Last-value), 5 executable leakage tests, and CPU-efficient model candidates (Chronos-Bolt-Tiny, Kronos-Mini).
2. **Catalyst & Fundamental Sentiment Layer**: Ported and adapted from proven patterns in `traidAi` (Finnhub news bundling, LLM news scoring with fallback chains, sell-side analyst consensus, and earnings proximity).
3. **Intraday Opportunity Screener**: Identifying volume surges (RVOL), relative strength vs. SPY/QQQ, and momentum turning points.
4. **Trade Setup & Cost Evaluator**: Calculating asymmetric Risk:Reward (Entry, Stop Loss, Take Profit), factoring in explicit spreads, slippage, taker fees, and mandatory 2x fee sensitivity.
5. **Local MCP Server**: Exposing tools via JSON-RPC over stdio for external AI agents (e.g. Claude, Antigravity, Cline) to scan, forecast, score catalysts, and produce evidence-backed recommendations with explicit abstention (`HOLD` / `NO_DATA`).

---

## Operating Protocol & Ultra-Micro Step Rules (Max 5 Minutes Work)

To ensure rapid, deterministic, and non-blocking execution by coding agents within short session limits:
1. **Nano-Step Granularity**: Every micro-step is budgeted for **at most 2–3 minutes of execution** (maximum 5 minutes end-to-end including review diff and test run).
2. **Single Responsibility Rule**: Each step modifies exactly ONE file and accomplishes ONE atomic unit (one class interface, one function, or one specific test case).
3. **Razor-Sharp Prompts**: Prompt instructions must be concise (< 8 lines), specifying exact signatures and avoiding open-ended ambiguity.
4. **Step Workflow**:
   - Supervisor issues a focused nano-prompt with stdin EOF.
   - Coder Model generates atomic code change.
   - Reviewer Model (Grok) audits diff independently.
   - Supervisor verifies test pass, commits to Git, and records progress in `progress.md`.

---

## Granular Stages and Micro-Steps Breakdown

### Stage 1: Environment, Tooling, Packaging & Data Adequacy

- [x] **1.1 Project Scaffolding & Packaging**
  - [x] 1.1.1 Create `pyproject.toml` with Hatchling, dependencies, and `pythonpath = ["src"]`.
  - [x] 1.1.2 Create `.gitignore` and base directory structure (`src/`, `tests/`, `data/cache/`, `docs/`).
  - [x] 1.1.3 Add basic scaffolding smoke test `tests/test_scaffolding.py`.
- [x] **1.2 Configuration & Secrets Management**
  - [x] 1.2.1 Implement `src/trading_engine/config.py` with `Settings` dataclass and safe redaction.
  - [x] 1.2.2 Implement strict paper-only validation (reject live AK keys, require PK, min secret len).
  - [x] 1.2.3 Add custom `__repr__` leak prevention and unit tests in `tests/test_config.py`.
- [x] **1.3 Data Contracts: Candle & BarSeries**
  - [x] 1.3.1 Create `src/trading_engine/data/__init__.py` and define `DataContractError` and `Candle` dataclass in `src/trading_engine/data/models.py`.
  - [x] 1.3.2 Create `tests/test_candle.py` testing `Candle` price and UTC timestamp validations.
  - [x] 1.3.3 Add `BarSeries` container in `src/trading_engine/data/models.py` with strict monotonic timestamp assertion.
  - [x] 1.3.4 Create `tests/test_bar_series.py` verifying `BarSeries` ordering, duplicate rejection, and indexing.
  - [x] 1.3.5 Add `to_dataframe()` method to `BarSeries`.
  - [x] 1.3.6 Add `from_dataframe()` classmethod to `BarSeries`.
  - [x] 1.3.7 Create `tests/test_dataframe_roundtrip.py` testing DataFrame conversions.
- [x] **1.4 Historical Market Data Ingestion**
  - [x] 1.4.1 Define abstract base class `MarketDataProvider` and `ProviderError` in `src/trading_engine/data/providers/base.py`.
  - [x] 1.4.2 Implement `AlpacaDataProvider` for 1h/1d/1m/5m/15m bars in `src/trading_engine/data/providers/alpaca.py`.
  - [x] 1.4.3a Test `AlpacaDataProvider` single-page bar fetch and `Candle` conversion in `tests/test_alpaca_provider.py`.
  - [x] 1.4.3b Test `AlpacaDataProvider` multi-page pagination with `next_page_token` in `tests/test_alpaca_provider.py`.
  - [x] 1.4.3c Test `AlpacaDataProvider` unsupported timeframe and HTTP error handling in `tests/test_alpaca_provider.py`.
  - [x] 1.4.4a Implement `YFinanceDataProvider` skeleton and timeframe mappings in `src/trading_engine/data/providers/yfinance.py`.
  - [x] 1.4.4b Implement `YFinanceDataProvider.fetch_bars` mapping to `Candle` objects.
  - [x] 1.4.5a Test `YFinanceDataProvider` valid daily bar fetch with mocked data in `tests/test_yfinance_provider.py`.
  - [x] 1.4.5b Test `YFinanceDataProvider` error handling and empty data rejection in `tests/test_yfinance_provider.py`.
- [x] **1.5 Local Persistent Cache (Parquet)**
  - [x] 1.5.1 Implement `ParquetDataCache` path resolver and partition helper in `src/trading_engine/data/cache.py`.
  - [x] 1.5.2 Implement `ParquetDataCache.save_bars()` serializing `BarSeries` to Parquet.
  - [x] 1.5.3 Implement `ParquetDataCache.load_bars()` reading Parquet back to `BarSeries`.
  - [x] 1.5.4 Test cache write, read, and hit roundtrip in `tests/test_cache.py`.
  - [x] 1.5.5 Test cache miss and date range filtering in `tests/test_cache.py`.
- [x] **1.6 Data Adequacy & Corporate Actions Audit**
  - [x] 1.6.1 Define benchmark symbols list (5 liquid symbols) in `src/trading_engine/data/benchmarks.py`.
  - [x] 1.6.2 Implement unadjusted split/dividend spike detector in `src/trading_engine/data/audit.py`.
  - [x] 1.6.3 Add unit tests for split spike detection in `tests/test_audit.py`.
  - [x] 1.6.4 Implement contiguous data depth checker in `src/trading_engine/data/audit.py`.
  - [x] 1.6.5 Add unit tests for depth checker in `tests/test_audit.py`.
- [x] **1.7 Stage 1 Review & Hardening Gate**
  - [x] 1.7.1 Run full Stage 1 regression suite across all providers, cache, and audit.
  - [x] 1.7.2 Grok audit and sign-off report in `docs/stage1_signoff.md`.

---

### Stage 2: Walk-Forward Evaluation Harness & Baselines (Leakage-Proof)

- [x] **2.1 Walk-Forward Splitter**
  - [x] 2.1.1 Implement chronological rolling-origin cutoff generator in `src/trading_engine/evaluation/walk_forward.py`.
  - [x] 2.1.2 Add calibration and out-of-sample test window partitioner.
  - [x] 2.1.3 Create unit tests in `tests/test_walk_forward.py` verifying zero time-travel in splits.
- [ ] **2.2 Baseline Models**
  - [ ] 2.2.1 Implement `LastValueBaseline` (constant persistence) in `src/trading_engine/models/baselines.py`.
  - [ ] 2.2.2 Create unit tests in `tests/test_baseline_last_value.py`.
  - [ ] 2.2.3 Implement `DriftBaseline` (historical return extrapolation) in `src/trading_engine/models/baselines.py`.
  - [ ] 2.2.4 Create unit tests in `tests/test_baseline_drift.py`.
  - [ ] 2.2.5 Implement `MovingAverageBaseline` (SMA/EMA path) in `src/trading_engine/models/baselines.py`.
  - [ ] 2.2.6 Create unit tests in `tests/test_baseline_ma.py`.
- [ ] **2.3 Executable Leakage Tests**
  - [ ] 2.3.1 Implement Leakage Test 1: Off-by-one bar close timestamp assertion in `tests/test_leakage_off_by_one.py`.
  - [ ] 2.3.2 Implement Leakage Test 2: Target shuffle collapse test in `tests/test_leakage_target_shuffle.py`.
  - [ ] 2.3.3 Implement Leakage Test 3: Future-scaler bit-identical test in `tests/test_leakage_future_scaler.py`.
  - [ ] 2.3.4 Implement Leakage Test 4: Incomplete live candle exclusion test in `tests/test_leakage_incomplete_candle.py`.
  - [ ] 2.3.5 Implement Leakage Test 5: Price adjustment consistency check in `tests/test_leakage_adjustment.py`.
- [ ] **2.4 Evaluation Metrics & Runner**
  - [ ] 2.4.1 Implement forecast error metrics (MAE, RMSE, Directional Accuracy) in `src/trading_engine/evaluation/metrics.py`.
  - [ ] 2.4.2 Implement Benjamini-Hochberg multiplicity correction in `src/trading_engine/evaluation/stats.py`.
  - [ ] 2.4.3 Create `HarnessRunner` executing baselines across rolling cutoffs in `src/trading_engine/evaluation/harness.py`.
  - [ ] 2.4.4 Create tests in `tests/test_harness.py` verifying metric calculation on synthetic series.
- [ ] **2.5 Stage 2 Review & Hardening Gate**
  - [ ] 2.5.1 Run all leakage tests and verify pass.
  - [ ] 2.5.2 Grok audit and sign-off report in `docs/stage2_signoff.md`.

---

### Stage 3: Model-Neutral Contract, Calibration & Cost Model

- [ ] **3.1 Data Contracts**
  - [ ] 3.1.1 Define `ForecastRequest` schema in `src/trading_engine/contracts/forecast.py`.
  - [ ] 3.1.2 Define `ForecastResult` schema with quantiles (P10, P50, P90) in `src/trading_engine/contracts/forecast.py`.
  - [ ] 3.1.3 Create unit tests in `tests/test_forecast_contract.py`.
- [ ] **3.2 Model Adapter Interface**
  - [ ] 3.2.1 Define `ModelAdapter` abstract base class with lifecycle hooks (`load`, `predict`, `unload`, `capabilities`) in `src/trading_engine/contracts/adapter.py`.
  - [ ] 3.2.2 Implement thread pinning and CPU affinity clamp helper in `src/trading_engine/contracts/device.py`.
  - [ ] 3.2.3 Create unit tests in `tests/test_model_adapter.py`.
- [ ] **3.3 Transaction Cost Model**
  - [ ] 3.3.1 Implement taker fee and spread calculator in `src/trading_engine/risk/cost_model.py`.
  - [ ] 3.3.2 Implement slippage model (constant + volatility-scaled) in `src/trading_engine/risk/cost_model.py`.
  - [ ] 3.3.3 Implement 2x cost sensitivity gate function in `src/trading_engine/risk/cost_model.py`.
  - [ ] 3.3.4 Create unit tests in `tests/test_cost_model.py`.
- [ ] **3.4 Probability Calibration**
  - [ ] 3.4.1 Implement Platt scaling (logistic) calibrated strictly on calibration window in `src/trading_engine/evaluation/calibration.py`.
  - [ ] 3.4.2 Implement Isotonic regression calibrator in `src/trading_engine/evaluation/calibration.py`.
  - [ ] 3.4.3 Implement Brier score and reliability diagram binning in `src/trading_engine/evaluation/calibration.py`.
  - [ ] 3.4.4 Create unit tests in `tests/test_calibration.py`.
- [ ] **3.5 Stage 3 Review & Hardening Gate**
  - [ ] 3.5.1 Run full Stage 3 test suite.
  - [ ] 3.5.2 Grok audit and sign-off report in `docs/stage3_signoff.md`.

---

### Stage 4: CPU Forecasting Models Spike (Chronos-Bolt-Tiny & Kronos-Mini)

- [ ] **4.1 CPU-Only Device Guard**
  - [ ] 4.1.1 Implement runtime assertion forbidding CUDA/MPS/DirectML in `src/trading_engine/models/device_guard.py`.
  - [ ] 4.1.2 Create unit tests in `tests/test_device_guard.py`.
- [ ] **4.2 Chronos-Bolt-Tiny Integration**
  - [ ] 4.2.1 Implement `ChronosBoltTinyAdapter` in `src/trading_engine/models/chronos_adapter.py`.
  - [ ] 4.2.2 Implement smoke test and cold-load timer in `tests/test_chronos_smoke.py`.
  - [ ] 4.2.3 Run walk-forward benchmark on benchmark symbols and record p50/p95 latency and RSS memory.
- [ ] **4.3 Kronos-Mini Integration**
  - [ ] 4.3.1 Vendor `NeoQuasar/Kronos-mini` code and tokenizer in `src/trading_engine/models/vendored/kronos/`.
  - [ ] 4.3.2 Implement `KronosMiniAdapter` in `src/trading_engine/models/kronos_adapter.py`.
  - [ ] 4.3.3 Implement smoke test verifying paired tokenizer/model weights in `tests/test_kronos_smoke.py`.
  - [ ] 4.3.4 Run walk-forward benchmark and measure latency at sample_count=1 vs calibrated sample count.
- [ ] **4.4 Candidate Comparative Assessment**
  - [ ] 4.4.1 Run harness comparisons (models vs baselines) with Benjamini-Hochberg correction.
  - [ ] 4.4.2 Produce formal assessment report in `docs/cpu-forecasting-models-assessment.md` (GO/DEFER/NO-GO).
- [ ] **4.5 Stage 4 Review & Hardening Gate**
  - [ ] 4.5.1 Run full Stage 4 test suite.
  - [ ] 4.5.2 Grok audit and sign-off report in `docs/stage4_signoff.md`.

---

### Stage 5: Catalyst & Fundamental Sentiment Layer

- [ ] **5.1 News Ingestion & Day Capping**
  - [ ] 5.1.1 Implement Finnhub news fetcher with rate limiter in `src/trading_engine/catalysts/news_fetcher.py`.
  - [ ] 5.1.2 Implement balanced date-capping (`PER_DAY_ARTICLES = 6`, max ceiling 90) in `src/trading_engine/catalysts/news_aggregator.py`.
  - [ ] 5.1.3 Create unit tests in `tests/test_news_aggregator.py`.
- [ ] **5.2 News LLM Scoring Engine**
  - [ ] 5.2.1 Define structured JSON schema `NewsScoreResult` in `src/trading_engine/catalysts/schemas.py`.
  - [ ] 5.2.2 Implement prompt builder for news scoring in `src/trading_engine/catalysts/prompts.py`.
  - [ ] 5.2.3 Implement LLM caller with fallback chain (Grok -> Claude -> OpenAI -> Gemini) in `src/trading_engine/catalysts/news_scorer.py`.
  - [ ] 5.2.4 Create unit tests with mocked LLM outputs in `tests/test_news_scorer.py`.
- [ ] **5.3 Sell-Side Analyst Consensus**
  - [ ] 5.3.1 Implement Finnhub & Yahoo Finance analyst recommendation fetcher in `src/trading_engine/catalysts/analysts.py`.
  - [ ] 5.3.2 Implement consensus score formula (-2.0 to +2.0) and revision delta tracker in `src/trading_engine/catalysts/analysts.py`.
  - [ ] 5.3.3 Create unit tests in `tests/test_analysts.py`.
- [ ] **5.4 Earnings Guardrail**
  - [ ] 5.4.1 Implement earnings calendar lookup and proximity calculator in `src/trading_engine/catalysts/earnings.py`.
  - [ ] 5.4.2 Implement 14-day pre-earnings risk flag rule in `src/trading_engine/catalysts/earnings.py`.
  - [ ] 5.4.3 Create unit tests in `tests/test_earnings.py`.
- [ ] **5.5 Unified Catalyst Aggregator**
  - [ ] 5.5.1 Implement `CatalystEngine` combining News, Analysts, and Earnings into a composite score in `src/trading_engine/catalysts/composite.py`.
  - [ ] 5.5.2 Create unit tests in `tests/test_catalyst_composite.py`.
- [ ] **5.6 Stage 5 Review & Hardening Gate**
  - [ ] 5.6.1 Run full Stage 5 test suite.
  - [ ] 5.6.2 Grok audit and sign-off report in `docs/stage5_signoff.md`.

---

### Stage 6: Intraday Opportunity Screener

- [ ] **6.1 Universe Management**
  - [ ] 6.1.1 Implement liquid universe loader ($> $20M volume, price $> $5) in `src/trading_engine/screener/universe.py`.
  - [ ] 6.1.2 Create unit tests in `tests/test_universe.py`.
- [ ] **6.2 RVOL & Intraday Surge**
  - [ ] 6.2.1 Implement 1h Relative Volume (RVOL) calculator vs 20-period baseline in `src/trading_engine/screener/rvol.py`.
  - [ ] 6.2.2 Create unit tests in `tests/test_rvol.py`.
- [ ] **6.3 Relative Strength (RS)**
  - [ ] 6.3.1 Implement RS vs SPY/QQQ over 1d, 5d, and 20d in `src/trading_engine/screener/relative_strength.py`.
  - [ ] 6.3.2 Create unit tests in `tests/test_relative_strength.py`.
- [ ] **6.4 Momentum & Reversal Indicators**
  - [ ] 6.4.1 Implement RSI(14) and RSI Washout detector in `src/trading_engine/screener/momentum.py`.
  - [ ] 6.4.2 Implement EMA crossover detector in `src/trading_engine/screener/momentum.py`.
  - [ ] 6.4.3 Create unit tests in `tests/test_screener_momentum.py`.
- [ ] **6.5 Composite Screener**
  - [ ] 6.5.1 Implement `MarketScreener` ranking top 5-10 candidates in `src/trading_engine/screener/screener.py`.
  - [ ] 6.5.2 Create integration test in `tests/test_screener.py`.
- [ ] **6.6 Stage 6 Review & Hardening Gate**
  - [ ] 6.6.1 Run full Stage 6 test suite.
  - [ ] 6.6.2 Grok audit and sign-off report in `docs/stage6_signoff.md`.

---

### Stage 7: Trade Setup Evaluator & Decision Policy

- [ ] **7.1 Trade Geometry (Brackets)**
  - [ ] 7.1.1 Implement invalidation Stop Loss calculator (swing low / ATR / P10) in `src/trading_engine/execution/geometry.py`.
  - [ ] 7.1.2 Implement Take Profit target calculator (resistance / P50 / P90) in `src/trading_engine/execution/geometry.py`.
  - [ ] 7.1.3 Create unit tests in `tests/test_geometry.py` asserting gross R:R >= 2.0.
- [ ] **7.2 Net Expected Value (EV) Gate**
  - [ ] 7.2.1 Implement Net EV formula subtracting spread, slippage, and taker fees in `src/trading_engine/execution/ev_gate.py`.
  - [ ] 7.2.2 Implement 2x cost sensitivity rejector in `src/trading_engine/execution/ev_gate.py`.
  - [ ] 7.2.3 Create unit tests in `tests/test_ev_gate.py`.
- [ ] **7.3 Recommendation Policy**
  - [ ] 7.3.1 Implement decision policy (`BUY`, `HOLD`, `NO_DATA`) in `src/trading_engine/execution/policy.py`.
  - [ ] 7.3.2 Implement structured evidence pack generator in `src/trading_engine/execution/evidence.py`.
  - [ ] 7.3.3 Create unit tests for policy and evidence generation in `tests/test_policy.py`.
- [ ] **7.4 Stage 7 Review & Hardening Gate**
  - [ ] 7.4.1 Run full Stage 7 test suite.
  - [ ] 7.4.2 Grok audit and sign-off report in `docs/stage7_signoff.md`.

---

### Stage 8: Local MCP Server Implementation

- [ ] **8.1 FastMCP Server Foundation**
  - [ ] 8.1.1 Initialize FastMCP server with lifecycle management in `src/trading_engine/mcp/server.py`.
  - [ ] 8.1.2 Create smoke test for server startup in `tests/test_mcp_server.py`.
- [ ] **8.2 Tool 1: `scan_market_opportunities`**
  - [ ] 8.2.1 Implement MCP tool registering `scan_market_opportunities` in `src/trading_engine/mcp/tools_screener.py`.
  - [ ] 8.2.2 Add unit test for tool invocation in `tests/test_mcp_tools.py`.
- [ ] **8.3 Tool 2: `get_time_series_forecast`**
  - [ ] 8.3.1 Implement MCP tool registering `get_time_series_forecast` in `src/trading_engine/mcp/tools_forecast.py`.
  - [ ] 8.3.2 Add unit test for tool invocation in `tests/test_mcp_tools.py`.
- [ ] **8.4 Tool 3: `get_catalyst_sentiment`**
  - [ ] 8.4.1 Implement MCP tool registering `get_catalyst_sentiment` in `src/trading_engine/mcp/tools_catalyst.py`.
  - [ ] 8.4.2 Add unit test for tool invocation in `tests/test_mcp_tools.py`.
- [ ] **8.5 Tool 4: `evaluate_trade_setup`**
  - [ ] 8.5.1 Implement MCP tool registering `evaluate_trade_setup` in `src/trading_engine/mcp/tools_risk.py`.
  - [ ] 8.5.2 Add unit test for tool invocation in `tests/test_mcp_tools.py`.
- [ ] **8.6 Tool 5: `get_short_term_recommendation`**
  - [ ] 8.6.1 Implement orchestrated recommendation tool in `src/trading_engine/mcp/tools_orchestration.py`.
  - [ ] 8.6.2 Add unit test for tool invocation in `tests/test_mcp_tools.py`.
- [ ] **8.7 Concurrency & Host UI Safety**
  - [ ] 8.7.1 Enforce process timeouts, async IO, and CPU thread pinning in `src/trading_engine/mcp/server.py`.
  - [ ] 8.7.2 Add unit tests for timeout and error handling in `tests/test_mcp_safety.py`.
- [ ] **8.8 Stage 8 Review & Hardening Gate**
  - [ ] 8.8.1 Run full Stage 8 test suite.
  - [ ] 8.8.2 Grok audit and sign-off report in `docs/stage8_signoff.md`.

---

### Stage 9: End-to-End Integration, CLI & Final Hardening

- [ ] **9.1 End-to-End Synthetic Simulation**
  - [ ] 9.1.1 Implement full simulated run from market scan to trade recommendation in `tests/test_e2e_simulation.py`.
  - [ ] 9.1.2 Verify determinism and zero data leakage.
- [ ] **9.2 Headless CLI Diagnostic Runner**
  - [ ] 9.2.1 Implement `scripts/run_cli.py` for headless execution and quick diagnostic scans.
  - [ ] 9.2.2 Test CLI runner in `tests/test_cli.py`.
- [ ] **9.3 Documentation & MCP Config Snippets**
  - [ ] 9.3.1 Create `README.md` with complete setup instructions.
  - [ ] 9.3.2 Provide Claude Desktop, Antigravity, and Cursor MCP client JSON snippets in `docs/mcp_client_setup.md`.
- [ ] **9.4 Final Audit & Verification**
  - [ ] 9.4.1 Audit all code licenses, credentials safety, and Stage 0 performance budgets.
  - [ ] 9.4.2 Produce final sign-off report in `docs/completion_report.md`.
