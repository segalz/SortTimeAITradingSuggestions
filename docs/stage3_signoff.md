# Stage 3 Sign-Off Audit

**Stage:** 3 — Model-Neutral Contract, Calibration & Cost Model
**Reviewer:** Grok (Reviewer Model)
**Date:** 2026-09-19
**HEAD:** `30c111c` (`feat(calibration): implement Platt scaling, Isotonic PAVA, Brier score, and reliability diagram (3.4.1-3.4.4)`)
**Verdict:** **APPROVED WITH FOLLOW-UPS** — Stage 3 gate may close; listed items are Stage 4 carry-forwards, not blockers.

---

## Evidence

- Independent re-run: `python.exe -m pytest -q` → **134 passed in 0.83s** (CPython 3.12.10). Stage 1 contributed 73; Stage 2 added 36 (109); Stage 3 added 25.
- Scope reviewed: `contracts/{forecast,adapter,device}.py`, `risk/cost_model.py`, `evaluation/calibration.py`, package `__init__` exports, and the four Stage 3 test modules. Cross-checked against `evaluation/{walk_forward,harness}.py`, `models/baselines.py`, `data/models.py`, and the five Stage 2 leakage tests (still green).
- Independent (non-pytest) numerical / immutability / leakage probes were executed against the same interpreter: Inf/NaN rejection, quantile monotonicity, 2x-gate arithmetic, Brier/ECE closed-form checks, Platt overflow-safe sigmoid, PAVA pooling, and adapter train-only inference.
- Working tree has CRLF/LF noise on the same 16 already-committed Stage 1 files (`git diff --ignore-cr-at-eol` is empty). Content is otherwise identical to HEAD; no functional uncommitted delta.

Stage 3 test inventory: forecast contract 4, model adapter / device 7, cost model 6, calibration 8.

---

## Requirement coverage (plan 3.1–3.5)

| Step | Intent | Status |
|---|---|---|
| 3.1.1 `ForecastRequest` | Frozen request schema: symbol, timeframe, history, horizon, quantiles | Met |
| 3.1.2 `ForecastResult` | Quantiles (default P10/P50/P90), point path, probabilities, UTC timestamps | Met |
| 3.1.3 Contract tests | Invariant bypass, freeze, monotonicity | Met |
| 3.2.1 `ModelAdapter` ABC | Lifecycle `load` / `predict` / `unload` / `capabilities` | Met (`BaselineAdapter` wrapper included) |
| 3.2.2 Device helpers | Thread pinning (`OMP`/`MKL`/`OpenBLAS`/`torch`) and CPU affinity clamp | Met (affinity is best-effort by platform) |
| 3.2.3 Adapter tests | Lifecycle, caps, affinity, inference | Met |
| 3.3.1 Taker fee + spread | 5 bps taker, 2.5 bps half-spread; maker fee 0 | Met |
| 3.3.2 Slippage | Constant 2.5 bps + `alpha * volatility` | Met |
| 3.3.3 2x sensitivity gate | Reject if net return under 2× round-trip friction is not strictly positive | Met |
| 3.3.4 Cost tests | Defaults, maker/taker, vol scaling, buy/sell, 2x pass/fail | Met |
| 3.4.1 Platt scaling | Logistic `P = σ(As+B)`, Platt target smoothing, **strictly on caller-supplied cal pairs** | Met at library API; **not wired** to a walk-forward cal partition (see Finding 1) |
| 3.4.2 Isotonic PAVA | Non-decreasing calibrator, pre-aggregated ties | Met |
| 3.4.3 Brier + reliability | Brier MSE; equal-width bins; ECE | Met |
| 3.4.4 Calibration tests | Bounds, monotonicity, ties, constant-score prior, bin edges | Met |
| 3.5 Gate | Full unit regression + this report | Met |

---

## Module assessment

**ForecastRequest / ForecastResult** (`contracts/forecast.py`). Both are `frozen=True` dataclasses. Request uppercases `symbol`, requires a non-empty `BarSeries` whose symbol/timeframe match, rejects `bool` for `horizon_bars`, and requires quantiles strictly increasing in `(0, 1)`. Result requires UTC `created_at`, forecast timestamps strictly monotonic **after** the history cutoff (the last train bar cannot be emitted as a forecast step), positive finite prices, quantile-key equality with the request, and per-step non-strict quantile monotonicity (`P10 ≤ P50 ≤ P90`). Dict fields are replaced with `MappingProxyType`. Nested lists inside `metadata` remain mutable (shallow freeze). Probability values are clamped to `[0, 1]` per key; they are **not** required to sum to 1. Point forecast is not required to lie inside `[P10, P90]`.

**ModelAdapter** (`contracts/adapter.py`). Abstract lifecycle is complete. `ModelAdapterCapabilities` is frozen and rejects empty `model_id` / empty timeframes / non-positive `max_horizon_bars`. `device` is an unconstrained string (CUDA is accepted here; Stage 4 `device_guard` is the intended ban). `BaselineAdapter` refuses `predict` unless loaded, enforces timeframe membership and `max_horizon_bars`, builds future timestamps from `infer_timeframe_delta`, and wraps any `BaselineModel`. Quantiles for baselines are a deterministic pseudo-spread `(q-0.5)*2%` around the point path (floor 0.01), not statistical uncertainty — `supports_quantiles=True` is therefore a contract-compatibility flag, not a claim of real predictive intervals. Directional probabilities are hardcoded 0.60/0.40 (or 0.50/0.50 if flat). `created_at` is the cutoff bar, not wall-clock inference time.

`infer_timeframe_delta` lowercases the token (`1H` → 1 hour). Capability membership does **not**, so a `BarSeries` stored as `"1H"` is a valid `ForecastRequest` but is rejected by a default `BaselineAdapter` whose caps list `"1h"`. `TIMEFRAME_DELTAS` in `data/models.py` is a second, narrower table. Unused imports in this module: `Candle`, `datetime`, `timezone`, `Mapping`, `field`.

**Device helpers** (`contracts/device.py`). `clamp_cpu_threads` writes `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, `NUMEXPR_NUM_THREADS`, and `torch.set_num_threads` when PyTorch is importable. `cpu_thread_limit` restores env (and torch thread count) in `finally`, including on exception. `set_cpu_affinity` uses `os.sched_setaffinity` or `psutil`, returns `None` when unsupported, and is **not** re-exported from `contracts/__init__.py`.

**CostModel** (`risk/cost_model.py`). Frozen. Defaults: taker 5 bps, half-spread 2.5 bps, constant slippage 2.5 bps, `volatility_slippage_coeff=0.05`. One-way taker cost is 10 bps; round-trip is 20 bps. Maker fee is identically 0; makers still pay half-spread and slippage. `apply_execution_costs` is always taker, multiplicative (`buy → P(1+f)`, `sell → max(0.0001, P(1-f))`). `evaluate_trade_viability` is additive on returns: `net = gross − k × round_trip` with `k ∈ {1,2}`. Independent check: for a +1% long, multiplicative net is 0.007982 vs linear `net_1x` 0.008000 (1.8 bps of the *price*, ~0.18 bps of return) — acceptable for a gate, not a fill simulator. Gate order: negative/zero gross fail; 1x net `≤ 0` fail; 2x net `≤ 0` fail; else pass. Strict positivity at the 2x line is the intended conservative rule.

**Calibration** (`evaluation/calibration.py`).

- **Brier** is mean squared error of probabilities; empty / length-mismatch / non-binary / out-of-range / `bool` inputs raise.
- **Reliability diagram** uses `bin = min(n_bins-1, int(p * n_bins))` (p=1.0 lands in the last bin). ECE is `Σ (n_b / n) |acc_b − conf_b|`. Empty bins contribute 0 to ECE but report `accuracy=0.0` and `confidence=bin_center` (plotting hazard, not an ECE bug). Verified: perfectly calibrated 0.2/0.8 block has ECE `≈ 0`; inverted `{0,1}` vs `{1,0}` with 2 bins has ECE `= 1`.
- **Platt** uses Platt 1999 target smoothing `t₊=(N₊+1)/(N₊+2)`, `t₋=1/(N₋+2)`, intercept init `B=log((N₊+1)/(N₋+1))`, L2 `λ=1e-4`, Newton–Raphson on the 2×2 Hessian, step clamp `±2`, and the overflow-safe sigmoid. Requires `n≥5` and both classes. Extreme scores (`±1e300`) and huge `|A|` stay in `[0,1]` with no overflow.
- **Isotonic** pre-aggregates tied `x`, runs PAVA (pool while left mean `≥` right mean), emits flat knots across pooled ranges, interpolates linearly, clamps to `[0,1]`, and is order-invariant. Classic violator `[1,0,1,1]` on `x=1..4` pools to `(0.5, 0.5, 1, 1)`. Dense-grid monotonicity holds. All-positive labels map to 1.

Calibrators are sklearn-style mutable estimators: they do not store `y_true`, and `predict_proba` is a function of scores only. Leakage is therefore a **caller** concern.

---

## Immutability map

| Object | Frozen? | Collections |
|---|---|---|
| `ForecastRequest` / `ForecastResult` | Yes | `quantiles`/`timestamps`/`point_forecast` → tuple; maps → `MappingProxyType` |
| Nested `metadata` values | Shallow only | A list value can still `.append` |
| `BarSeries` / `Candle` (history) | Yes | Bars are a tuple of frozen candles |
| `ModelAdapterCapabilities` | Yes | `supported_timeframes` coerced to tuple |
| `BaselineAdapter` | No | `_is_loaded` is the lifecycle flag |
| `CostModel` / `CostBreakdown` / `CostEvaluationResult` | Yes | — |
| `ReliabilityDiagramResult` | Yes | Tuples |
| `PlattScalingCalibrator` / `IsotonicCalibrator` | No | Fitted `a_`,`b_` / knots are writable (expected) |

Independent probes confirmed: assignment to frozen fields raises; `MappingProxyType` rejects item assignment; `ForecastRequest.history.bars = ()` raises.

---

## Leakage-control map (Stage 3 surfaces)

| Control | Enforced where | On the harness path? |
|---|---|---|
| Forecast timestamps strictly after cutoff | `ForecastResult.__post_init__` | n/a (harness still uses `BaselineModel.predict`, not `ForecastResult`) |
| Adapter sees only `request.history` | `BaselineAdapter.predict` | No — harness does not call `ModelAdapter` |
| Quantile path cannot invert | `ForecastResult` per-step `P_low ≤ P_high` | n/a |
| Platt/Isotonic fit isolated from predict labels | Calibrator stores no `y_true` | No — harness does not calibrate |
| Fit-on-cal-window, apply-on-test | Caller convention only | **No cal partition exists** (`WalkForwardSplit` is still train/test) |
| Stage 2 leakage tests 1–5 | Unchanged modules | Tests still pass; Finding 1 (target shuffle) and Finding 2 (PIT on harness) from Stage 2 remain open |

A last-value adapter fitted on the first 5 bars of an 8-bar series emits the train last close, not the series last close. Forecast timestamps are disjoint from history timestamps. No Stage 3 API *introduces* time-travel. The Stage 2 follow-up that calibration needs a held-out cal window **plus embargo** is still unimplemented.

---

## Numerical stability

| Surface | Result |
|---|---|
| Inf/NaN/bool/`≤0` prices on contracts | Rejected (`DataContractError`) |
| Inf/NaN/bool rates on `CostModel` | Rejected (`ValueError`) |
| Inf scores / non-binary labels on calibrators | Rejected |
| Platt sigmoid | Overflow-safe; `±1e300` → `{0, 0.5, 1}` as expected for tiny `A` |
| Platt Newton | Ridge + det guard + step damping; well-posed aligned scores give `A>0` and strictly increasing probabilities |
| Degenerate constant scores | In-sample `p(s_train)` matches mean Platt target (`≈0.281` vs Laplace `0.30` within the test tolerance). `A` is not identified; L2 splits `A≈B`, so **off-support** scores can invert (see Finding 2) |
| Isotonic | Outputs in `[0,1]`, non-decreasing, tie-order invariant, length-matched even for a single knot |
| 2x gate at exact 40 bps | `total_cost_2x` is the exact binary `0.004`; `(100.4-100)/100` is `0.004+5.6e-17`, so the strict `>0` check **passes** by 1 ULP (see Finding 3) |
| Sell with huge friction | Floor `0.0001`, never negative |
| Brier / ECE | Match closed-form values to `1e-15` / `1e-12` |

“Full numerical stability” holds for well-posed inputs (the production path). Two degenerate/boundary cases are documented below and are not production-breaking.

---

## Stage 1 / Stage 2 follow-up disposition

| Prior item | Stage 3 status |
|---|---|
| Alpaca `adjustment=split` vs yfinance `auto_adjust=True` | **Open.** Providers unchanged. |
| Empty-result contract mismatch | **Open.** |
| Live adequacy run on SPY/QQQ/AAPL/MSFT/NVDA | **Open.** Still synthetic-only. |
| Alpaca pagination page budget; cache naive-index localize | **Open.** |
| CRLF working copies vs LF in git | **Open.** Same 16 Stage 1 files. |
| Stage 2 Finding 1 — target-shuffle test is a label-permutation tautology | **Open.** `tests/test_leakage_target_shuffle.py` still shuffles a hand-built `[1,0,…]` vector, not `split.test` closes against frozen `predict(split.train)` output. |
| Stage 2 Finding 2 — PIT helper not on the harness path | **Open.** |
| Stage 2 Finding 3 — no embargo / no train-cal-test split | **Open.** Now more relevant: Platt/isotonic exist and still have nowhere in `WalkForwardSplit` to fit. |
| Stage 2 Finding 7 — harness typed to `BaselineModel` | **Open.** `HarnessRunner.run` still takes `Mapping[str, BaselineModel]`; `BaselineAdapter` cannot be passed in. Stage 4 model spike must generalize this. |
| SMA-only MA baseline; BH unused by harness | **Open.** (Stage 4) |

---

## Findings (non-blocking)

1. **Platt/isotonic are not bound to a calibration window (follow-up).** Plan 3.4.1 says “calibrated strictly on calibration window”. The library is window-agnostic: `fit(scores, y_true)` will happily consume test labels if the caller passes them. `generate_walk_forward_splits` still emits only train/test with no purge gap. Stage 4 Chronos/Kronos probability heads must: (a) add a cal partition that ends at or before cutoff, (b) fit Platt/isotonic only there, (c) apply to test scores. Until then, “zero leakage” for calibrated probabilities is an API property, not a harness invariant.

2. **Constant-score Platt leaves `A` unidentified (numerical nit).** With all `s=1` and mixed labels, ridge yields `A≈B≈−0.469`. `predict_proba([1.0])≈0.281` is correct; `predict_proba([-10])≈0.986` is inverted. Harden by freezing `A=0` (intercept-only) when score variance `< ε`. The unit test only queries the training score and remains valid.

3. **Exact 2x-cost boundary is 1 ULP on the pass side (numerical nit).** Default round-trip ×2 is binary `0.004` exactly. `(100.4 − 100) / 100` is `0.004 + 5.6e-17`, so `net_return_2x <= 0` does not fire. Existing tests use +25 bps (fail) and +100 bps (pass), so they do not pin the knife-edge. Optional: compare with a small epsilon, or compute gross from integer ticks. Irrelevant at trading precision.

4. **`HarnessRunner` does not speak `ModelAdapter` (integration gap).** The model-neutral contract landed, but evaluation still calls `BaselineModel.predict(history, horizon_bars)`. Cost model and calibrators are also unused by the harness. Acceptable for Stage 3 as library work; Stage 4 walk-forward of Chronos-Bolt-Tiny / Kronos-Mini must go through `ForecastRequest`/`ForecastResult` and the 2x gate.

5. **Timeframe string identity (nit).** `infer_timeframe_delta` lowercases; adapter capability checks do not; `BarSeries` does not normalize. `"1H"` is a valid request and a valid delta, but not a default supported timeframe. Same class of issue Stage 1 noted for `"1H"` vs `TIMEFRAME_DELTAS`.

6. **Capability / cost semantics (nits).** `device="cuda"` is allowed on `ModelAdapterCapabilities` (Stage 4 guard). `max_horizon_bars=True` is accepted (`bool` is an `int`). Makers still pay half-spread. `apply_execution_costs` cannot select maker. `BaselineAdapter.supports_quantiles=True` with synthetic 2% bands. Probability keys need not form a simplex. `set_cpu_affinity` is not in `contracts.__all__`. `adapter.py` carries unused imports.

No production-breaking defect was found in request/result invariants, cutoff-strict timestamps, adapter train-only inference, load/unload gating, taker/spread/slippage arithmetic, 2x-gate fail paths used by the tests, Brier/ECE formulas, PAVA monotonicity, or Platt overflow handling on well-posed data.

---

## Gate decision

**APPROVED.** Close Stage 3. Proceed to Stage 4 (CPU forecasting models: device guard, Chronos-Bolt-Tiny, Kronos-Mini) with Finding 1 (cal window + embargo on the harness path) and the still-open Stage 2 Finding 1 (real target-shuffle test) on the backlog. Do not treat current calibration unit tests as evidence that live model probabilities are walk-forward calibrated.

Signed off: Grok, 2026-09-19.
