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

## Operating Protocol & Quality Gate Architecture

Each stage is divided into atomic, bite-sized **Micro-Steps**.
For every micro-step:
1. **Task Definition**: The Supervisor (Antigravity) formulates the exact prompt and constraints for the micro-step.
2. **Coder Execution**: The Coder Model writes the minimal, clean, type-hinted code and unit tests.
3. **Reviewer Verification**: The Reviewer Model (e.g., Grok / independent reviewer) audits the diff, checks edge cases, and verifies against constraints.
4. **Immediate Progress Update**: Upon approval, `progress.md` is updated immediately with status, timestamp, and summary of changes.
5. **Stage Gate Review**: At the end of each Stage, full regression tests and leakage/integrity checks are run before transitioning to the next Stage.

---

## Stages and Micro-Steps Breakdown

### Stage 1: Environment, Tooling, Packaging & Data Adequacy
**Goal:** Establish a rock-solid Python 3.12+ project foundation, secret loading, data contracts, local caching, and verify historical data depth for 1h candles.

- [x] **1.1 Project Scaffolding & Packaging**
  - Create `pyproject.toml` with Hatchling build-backend, defining dependencies: `pandas`, `numpy`, `httpx`, `pydantic`, `mcp`, `python-dotenv`, `pytest`.
  - Create `.gitignore` (ignoring `.venv`, `keys.env`, `*.db`, `*.parquet`, `__pycache__`, `artifacts/`, `data/cache/`).
  - Create directory structure: `src/trading_engine/`, `tests/`, `data/cache/`, `docs/`.
- [x] **1.2 Configuration & Secrets Management**
  - Implement `src/trading_engine/config.py` loading `keys.env` with strict redaction in logs.
  - Support credentials: Alpaca Paper API keys, Finnhub API key, and LLM provider keys.
  - Add unit tests validating credential format, prefix checks, and redaction.
- [ ] **1.3 Data Ingestion Contract & Candle Representation**
  - Define immutable data structures: `Candle`, `BarSeries` (timestamp UTC, open, high, low, close, volume, optional amount/vwap).
  - Implement validation: monotonic ascending timestamps, non-negative volumes, high >= low, open/close within [low, high].
  - Add unit tests for candle validation and error handling.
- [ ] **1.4 Historical Market Data Providers (1h & 1d)**
  - Implement provider client interface with support for Alpaca Data API (for 1h bars) and yfinance (for fallback/daily).
  - Implement rate limiting and retry backoff.
  - Add unit tests with mocked HTTP responses.
- [ ] **1.5 Local Persistent Data Cache**
  - Implement local disk caching (Parquet or SQLite) for historical bars to guarantee deterministic, offline-repeatable runs.
  - Implement cache invalidation and cache hit/miss telemetry.
  - Add unit tests testing cache read/write fidelity.
- [ ] **1.6 Data Adequacy & Corporate Adjustment Audit Script**
  - Write verification script `scripts/audit_data_adequacy.py` testing 5 benchmark symbols across at least 2 asset classes/regimes.
  - Verify contiguous 1h history, missing candle handling, holiday calendars, and split/dividend adjustments.
  - Add unit tests for split-detection and unadjusted return threshold checks.
- [ ] **1.7 Stage 1 Review & Hardening Gate**
  - Run full test suite for Stage 1.
  - Reviewer model audit of Stage 1 architecture.
  - Record data adequacy findings in `docs/data_adequacy_report.md`.

---

### Stage 2: Walk-Forward Evaluation Harness & Baselines (Leakage-Proof)
**Goal:** Build a strictly chronological rolling-origin walk-forward evaluation harness with zero lookahead, including all 5 mandatory leakage tests.

- [ ] **2.1 Rolling-Origin Walk-Forward Splitter**
  - Implement chronological walk-forward generator: generates cutoffs $t$, calibration windows, and test evaluation windows.
  - Guarantee strict separation: future data never passed into past transforms.
  - Unit tests verifying split windows and bounds.
- [ ] **2.2 Baseline Model: Last-Value (Persistence / Naive)**
  - Implement naive baseline predicting constant last-known price across horizon $H=12$.
  - Unit tests verifying output shapes and exact values.
- [ ] **2.3 Baseline Model: Historical Drift / Simple Return**
  - Implement drift baseline extrapolating historical trend over specified lookback.
  - Unit tests verifying math and determinism.
- [ ] **2.4 Baseline Model: Exponential Smoothing / Moving Average**
  - Implement EMA / SMA baseline for price path forecasting.
  - Unit tests verifying math against pure Pandas calculations.
- [ ] **2.5 Leakage Test 1: Off-By-One Bar Assertion**
  - Executable test: assert forecast at cutoff $t$ consumes no candle whose bar-close timestamp $> t$.
  - Verify against bar-close semantics, not bar-open.
- [ ] **2.6 Leakage Test 2: Target Shuffle Test**
  - Executable test: shuffle target returns within test window; verify every model collapses to chance ($R^2 \le 0$ or directional accuracy $\approx 50\%$).
- [ ] **2.7 Leakage Test 3: Future-Scaler Test**
  - Executable test: assert normalization statistics computed at cutoff $t$ are bit-identical whether future rows exist in the dataframe or not.
- [ ] **2.8 Leakage Test 4: Incomplete / In-Progress Candle Test**
  - Executable test: assert incomplete (current live) bar is strictly excluded from historical inputs.
- [ ] **2.9 Leakage Test 5: Adjustment-Consistency Test**
  - Executable test: flag any single-bar return exceeding threshold without recorded corporate action.
- [ ] **2.10 Harness Runner & Metric Aggregator**
  - Implement metrics: MAE, RMSE, Directional Accuracy, Pinball loss for quantiles.
  - Multiplicity correction: Benjamini-Hochberg adjustment implementation.
  - Unit tests for metric calculators.
- [ ] **2.11 Stage 2 Review & Hardening Gate**
  - Full test run of all 5 leakage tests and baseline benchmarks.
  - Reviewer model audit of harness integrity.

---

### Stage 3: Model-Neutral Forecast Contract, Calibration & Cost Model
**Goal:** Create an decoupled forecast interface, probability calibration (Isotonic/Platt), and realistic transaction cost model.

- [ ] **3.1 Forecast Data Contracts (`ForecastRequest`, `ForecastResult`)**
  - Define `ForecastRequest` (symbol, timeframe, cutoff, horizon, candles, covariates).
  - Define `ForecastResult` (model_id, predicted_path, quantiles P10/P50/P90, calibrated_probs, uncertainty_score, latency_ms).
  - Pydantic models with strict validation.
- [ ] **3.2 Model Adapter Lifecycle Interface**
  - Abstract base class `ModelAdapter`: `load()`, `predict()`, `health()`, `unload()`, `capabilities()`.
  - Implement thread pinning and CPU thread affinity management.
- [ ] **3.3 Transaction Cost & Sensitivity Model**
  - Implement cost calculator: Taker fee per asset class, bid-ask spread, slippage model (constant + volatility-scaled).
  - Mandatory 2x sensitivity evaluation function: if net edge flips sign at 2x costs, signal is marked unviable.
  - Unit tests for cost computations.
- [ ] **3.4 Probability Calibration Engine**
  - Implement Platt scaling (logistic) and Isotonic regression fitted *strictly on calibration window*.
  - Rule: raw quantile count ending above close is never emitted as probability.
  - Unit tests asserting calibration bounds [0.0, 1.0].
- [ ] **3.5 Reliability Diagram & Brier Score Evaluator**
  - Implement Brier score calculator and reliability curve binning.
  - Unit tests verifying Brier score on synthetic perfect vs random probabilities.
- [ ] **3.6 Stage 3 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of contracts and calibration logic.

---

### Stage 4: CPU Forecasting Models Spike (Chronos-Bolt-Tiny & Kronos-Mini)
**Goal:** Integrate and evaluate CPU-only zero-shot time-series models against Stage 0 budgets and baselines.

- [ ] **4.1 CPU-Only Runtime Environment & Device Guard**
  - Assert runtime explicitly forces CPU; hard fail if CUDA/DirectML/MPS is initialized.
  - Pin PyTorch/ONNX thread count to prevent freezing laptop UI.
- [ ] **4.2 Chronos-Bolt-Tiny Adapter**
  - Implement adapter for `amazon/chronos-bolt-tiny`.
  - Smoke test on CPU, cold load timing, peak RSS tracking.
  - Map output to `ForecastResult` quantiles (P10, P50, P90).
- [ ] **4.3 Chronos-Bolt-Tiny Walk-Forward Benchmark**
  - Run Chronos-Bolt-Tiny through Stage 2 walk-forward harness on benchmark symbols.
  - Record latency (warm p50, p95), memory, and accuracy vs baselines.
- [ ] **4.4 Kronos-Mini Vendored Setup & Tokenizer Verification**
  - Vendor `NeoQuasar/Kronos-mini` model and tokenizer classes with recorded commit SHA.
  - Verify paired tokenizer/weights consistency.
- [ ] **4.5 Kronos-Mini Adapter & CPU Benchmark**
  - Implement adapter for `Kronos-mini`.
  - Measure latency at `sample_count=1` and calibrated sample count.
  - Run walk-forward benchmark and record Stage 0 budget compliance.
- [ ] **4.6 Multiplicity Correction & Comparative Assessment Report**
  - Calculate Benjamini-Hochberg corrected metrics comparing models vs baselines.
  - Generate assessment summary (GO / DEFER / NO-GO) per model.
- [ ] **4.7 Stage 4 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of benchmark results.

---

### Stage 5: Catalyst & Fundamental Sentiment Layer
**Goal:** Port and modernize the news and analyst scoring pipeline from `traidAi` to provide the "Why Now?" catalyst for short-term trades.

- [ ] **5.1 Finnhub News Ingestion & Balanced Day-Capping**
  - Ingest company news via Finnhub API.
  - Implement balanced date-capping (`PER_DAY_ARTICLES = 6`, max ceiling 90) to prevent mega-cap distortion.
  - Unit tests with mock payloads.
- [ ] **5.2 News LLM Scoring Engine with Fallback Chain**
  - Implement news scoring prompt with structured JSON output: `{"score": 0-100, "rationale": "...", "catalyst_type": "..."}`.
  - Implement provider chain: Grok -> Claude -> OpenAI -> Gemini -> fallback.
  - Unit tests testing parsing and fallbacks.
- [ ] **5.3 Sell-Side Analyst Consensus & Trend Tracker**
  - Fetch consensus buckets (strong buy, buy, hold, sell, strong sell) from Finnhub & Yahoo Finance.
  - Calculate normalized consensus score (-2.0 to +2.0) and monthly delta/revisions.
  - Unit tests for score computation.
- [ ] **5.4 Earnings Proximity & Event Guardrail**
  - Detect next earnings date; flag proximity ($\le 14$ days or intraday reporting).
  - Categorize event risk (abstain or adjust risk parameters).
  - Unit tests for calendar logic.
- [ ] **5.5 Unified Catalyst Score Aggregator**
  - Combine News Score (weight ~50%), Analyst Consensus (weight ~30%), and Momentum/Event flags (weight ~20%).
  - Unit tests for weighted catalyst scoring and missing data degradation.
- [ ] **5.6 Stage 5 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of catalyst layer.

---

### Stage 6: Intraday Opportunity Screener
**Goal:** Build a high-speed scanner filtering a universe of stocks down to the top 5–10 short-term breakout/reversal candidates.

- [ ] **6.1 Universe Management & Liquidity Filtering**
  - Manage tradeable universe (e.g. liquid US equities, min average daily volume $\ge \$20M$, price $\ge \$5$).
  - Fast batch quote/data fetching.
  - Unit tests for universe filtering.
- [ ] **6.2 Relative Volume (RVOL) & Intraday Activity Engine**
  - Compute 1h RVOL: current volume over 20-period moving average of volume for that same hour.
  - Flag volume surges ($\ge 1.5\times$ or $2.0\times$).
  - Unit tests for RVOL calculation across intraday bars.
- [ ] **6.3 Relative Strength (RS) vs. Market Benchmarks**
  - Calculate RS vs SPY and QQQ over 1-day, 5-day, and 20-day windows.
  - Identify leadership (stocks rising or holding firm while benchmark drops).
  - Unit tests for RS differential calculation.
- [ ] **6.4 Technical Momentum & Mean-Reversion Triggers**
  - Compute RSI(14), RSI Washout (recent oversold $< 30$ followed by recovery $> 35$), and moving average crossovers (EMA 9/21).
  - Unit tests for indicator triggers.
- [ ] **6.5 Multi-Factor Candidate Ranking & Pipeline Filter**
  - Combine RVOL, RS, Catalyst Score, and Technical Trigger into a composite rank score.
  - Output top 5–10 ranked candidates with tagged setup reasons.
  - Unit tests for ranking and determinism.
- [ ] **6.6 Stage 6 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of screener logic.

---

### Stage 7: Trade Setup Evaluator & Decision Policy
**Goal:** Formulate actionable trade setups (Entry, SL, TP) and enforce strict risk management and fee-adjusted expected return gates.

- [ ] **7.1 Trade Geometry Calculator (Entry, Stop Loss, Take Profit)**
  - Price invalidation stop-loss based on recent swing low / ATR / quantile floor (P10).
  - Price take-profit targets based on resistance levels / quantile target (P50/P90).
  - Calculate gross Risk:Reward ratio (minimum target $\ge 2.0$).
  - Unit tests for price bracket generation.
- [ ] **7.2 Net Expected Value & 2x Fee Gatekeeper**
  - Calculate Net EV: $P(\text{win}) \times (\text{Gain} - \text{Costs}) - P(\text{loss}) \times (\text{Loss} + \text{Costs})$.
  - Run 2x cost sensitivity: if Net EV becomes negative at $2\times$ fees/spread/slippage, trigger immediate rejection.
  - Unit tests for EV gate under varying spreads.
- [ ] **7.3 Recommendation Policy (`BUY`, `HOLD`, `NO_DATA`)**
  - Implement decision matrix: emit `BUY` only if:
    1. Catalyst Score $\ge$ threshold
    2. Model Forecast Direction is positive and calibrated
    3. Net EV after 2x costs is positive
    4. Gross R:R $\ge 2.0$
  - Emit `HOLD` (with explanation) if edge is marginal or uncertainty is high.
  - Emit `NO_DATA` if feeds are incomplete or stale.
  - Unit tests for policy edge cases and abstention logic.
- [ ] **7.4 Structured Trade Evidence Pack Generator**
  - Output transparent payload: Raw model quantiles, Catalyst breakdown, Screener triggers, Price brackets, Net EV table, and plain-English rationale.
  - Unit tests validating evidence pack completeness.
- [ ] **7.5 Stage 7 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of decision policy.

---

### Stage 8: Local MCP Server Implementation
**Goal:** Expose the complete short-term trading engine as a standard Model Context Protocol (MCP) server over stdio for agentic consumption.

- [ ] **8.1 MCP Server Base Setup & Lifecycle**
  - Initialize MCP server using standard Python MCP SDK (`mcp.server.fastmcp` or stdio protocol).
  - Implement lifecycle: startup checks, resource allocations, graceful shutdown.
  - Unit tests for server initialization.
- [ ] **8.2 MCP Tool 1: `scan_market_opportunities`**
  - Expose screener: parameters for minimum RVOL, sector filter, max candidates.
  - Returns ranked candidate list with technical and volume telemetry.
  - Integration tests via MCP tool invocation.
- [ ] **8.3 MCP Tool 2: `get_time_series_forecast`**
  - Expose forecasting engine: inputs (symbol, timeframe, horizon); outputs (quantiles, calibrated probabilities, uncertainty).
  - Integration tests via MCP tool invocation.
- [ ] **8.4 MCP Tool 3: `get_catalyst_sentiment`**
  - Expose catalyst engine: inputs (symbol, days_back); outputs (news summary, analyst consensus score, earnings flag).
  - Integration tests via MCP tool invocation.
- [ ] **8.5 MCP Tool 4: `evaluate_trade_setup`**
  - Expose risk evaluator: inputs (symbol, entry_price, stop_loss, take_profit); outputs (Net EV, 2x cost sensitivity, R:R).
  - Integration tests via MCP tool invocation.
- [ ] **8.6 MCP Tool 5: `get_short_term_recommendation`**
  - Unified orchestration tool: runs scan -> forecast -> catalyst -> risk check -> outputs final evidence-backed recommendation (`BUY`/`HOLD`/`NO_DATA`).
  - Integration tests via MCP tool invocation.
- [ ] **8.7 Error Handling, Concurrency & UI Safety**
  - Bound subprocess timeouts, enforce non-blocking IO, clamp thread counts to preserve host laptop responsiveness.
  - Unit tests for timeout recovery and memory cleanup.
- [ ] **8.8 Stage 8 Review & Hardening Gate**
  - Full test suite run. Reviewer model audit of MCP protocol conformance.

---

### Stage 9: End-to-End Integration, CLI Verification & Final Hardening
**Goal:** Verify the full system end-to-end, provide local CLI test tools, and document all operations.

- [ ] **9.1 End-to-End Synthetic & Historical Integration Tests**
  - Run full simulated cycle from market scan to MCP tool response on historical data.
  - Verify zero leakage, deterministic execution, and reproducible outputs.
- [ ] **9.2 Local CLI Diagnostic Runner**
  - Implement `scripts/run_cli.py` for standalone headless execution and debugging without an MCP client.
- [ ] **9.3 Documentation & Agent Configuration Guide**
  - Write `README.md` in repository root explaining setup, environment keys, and running the MCP server.
  - Provide Claude Desktop / Antigravity / Cursor MCP configuration snippets.
- [ ] **9.4 Final Security, Licensing & Budget Audit**
  - Audit: no keys in git, clean open-source licenses, CPU latency $\le 2000$ ms p95, RAM $\le 2$ GB.
  - Produce final sign-off report in `docs/completion_report.md`.
