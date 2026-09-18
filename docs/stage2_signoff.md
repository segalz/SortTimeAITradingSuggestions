# Stage 2 Sign-Off Audit

**Stage:** 2 — Walk-Forward Evaluation Harness & Baselines (Leakage-Proof)
**Reviewer:** Grok (Reviewer Model)
**Date:** 2026-09-18
**HEAD:** `bd0c334` (`feat(evaluation): implement metrics, Benjamini-Hochberg stats, and HarnessRunner with tests (2.4.1-2.4.4)`)
**Verdict:** **APPROVED WITH FOLLOW-UPS** — Stage 2 gate may close; listed items are Stage 3/4 carry-forwards, not blockers.

---

## Evidence

- Independent re-run: `python.exe -m pytest -q` → **109 passed in 0.85s** (CPython 3.12). Stage 1 contributed 73; Stage 2 added 36.
- Scope reviewed: `evaluation/{walk_forward,scaling,metrics,stats,harness}.py`, `models/baselines.py`, `data/adjustment.py`, `data/models.py` (`filter_completed_candles`), package `__init__` exports, and the eight Stage 2 test modules.
- Working tree has CRLF/LF noise on 16 already-committed Stage 1 files (`git diff --ignore-cr-at-eol` is empty). Content is otherwise identical to HEAD; no functional uncommitted delta.

Stage 2 test inventory: walk-forward 6, baselines 10, off-by-one leakage 2, target-shuffle leakage 1, future-scaler leakage 2, incomplete-candle leakage 4, adjustment leakage 3, harness/metrics/BH 8.

---

## Requirement coverage (plan 2.1–2.5)

| Step | Intent | Status |
|---|---|---|
| 2.1 Walk-forward splitter | Chronological rolling-origin cutoffs; rolling vs expanding train; zero time-travel | Met (train+test only; no separate calibration partition) |
| 2.2 Baseline models | `LastValueBaseline`, `DriftBaseline`, `MovingAverageBaseline` | Met for SMA persistence/drift/MA; EMA path from 2.2.5 not implemented |
| 2.3.1 Leakage 1 | Off-by-one bar timestamp; disjoint train/test | Met |
| 2.3.2 Leakage 2 | Target shuffle collapse toward chance | **Partially met** — shuffle is a label-permutation tautology, not a model-target shuffle (see Finding 1) |
| 2.3.3 Leakage 3 | Future-scaler bit-identical train transform | Met (`WindowScaler` fit-on-train invariant + leaked-global counterexample) |
| 2.3.4 Leakage 4 | Incomplete live candle exclusion | Met (`filter_completed_candles` for 1m/5m/15m/1h/1d) |
| 2.3.5 Leakage 5 | Point-in-time split action; future splits do not rewrite cutoff history | Met for the helper; **not wired** into providers or `HarnessRunner` |
| 2.4.1 Metrics | MAE, RMSE, directional accuracy (+ MAPE) | Met |
| 2.4.2 Benjamini-Hochberg | FDR step-up adjusted p-values and rejections | Met as a standalone function; not invoked by the harness |
| 2.4.3–2.4.4 Harness | Execute baselines across rolling cutoffs; synthetic-series tests | Met |
| 2.5 Gate | Full unit regression + this report | Met |

`plan.md` still leaves 2.4–2.5 unchecked. `progress.md` is frozen at micro-step 2.4.1 with “35 / 72” complete. Implementation and tests through 2.4.4 are on `bd0c334`; the ledger is stale.

---

## Module assessment

**Walk-forward splitter** (`evaluation/walk_forward.py`). `generate_walk_forward_splits` emits `WalkForwardSplit` objects whose `__post_init__` enforces three invariants: non-empty train/test, `train[-1].timestamp < test[0].timestamp`, and `cutoff == train[-1].timestamp`. Rolling windows slide a fixed `train_bars` block; expanding windows keep origin 0 and grow `train_end`. Stride is `step_bars`. Series shorter than `train_bars + test_bars` yield `[]` (the harness then errors). There is no embargo/purge gap between train and test, and no third calibration partition — acceptable for these price-level baselines, insufficient once lagged features or Platt scaling appear.

**Baselines** (`models/baselines.py`). `Forecast` is a frozen container that checks `horizon_bars > 0` and matching `point_forecasts` length. All three models refuse empty history and non-positive horizons.

- `LastValueBaseline` repeats the last close. Correct persistence null.
- `DriftBaseline` uses arithmetic price slope `(last - first) / (n - 1)`, not log-return or mean period return, then clamps at `0.01`. Single-bar history is zero drift. The clamp preserves the `Candle` positive-price invariant.
- `MovingAverageBaseline` projects a constant SMA over `min(window, len(history))`. No EMA despite plan 2.2.5 “SMA/EMA path”. Mean of strictly positive closes cannot go non-positive, so no floor is required.

**WindowScaler** (`evaluation/scaling.py`). Fit uses `numpy.mean` / `numpy.std` (population, `ddof=0`) on train closes only. Degenerate `std < 1e-8` is replaced with `1.0`. `transform` applies stored parameters to any series; it cannot see future bars unless the caller `fit`s on them. Leakage test 3 proves train transforms are identical under a normal future vs a 1000× spike future, and that a global train+test fit distorts train features.

**Incomplete-candle filter** (`data/models.py`). A bar at `t` is complete iff `current_time >= t + TIMEFRAME_DELTAS[tf]`. Naive `current_time` is rejected; unknown timeframes raise. Lookup lowercases the timeframe; `BarSeries` does not normalize it, so `"1H"` would miss the table. Daily completion is a calendar `timedelta(days=1)`, not a session close — a 1d bar labeled at the open is still “forming” at the US cash close.

**Point-in-time splits** (`data/adjustment.py`). `SplitAction` requires `split_ratio > 0` and a tz-aware `effective_date` (not strictly UTC). `apply_point_in_time_splits` keeps splits with `effective_date <= as_of_time` for the same symbol, then divides OHLC and multiplies volume by the product of ratios for bars strictly before each effective date. Future splits are ignored. Past 2-for-1 on a 200→100 raw series adjusts correctly. The helper drops `vwap`/`amount` (reconstructed candles omit them), does not truncate bars after `as_of_time`, and does not handle dividends. It is not exported from `data/__init__.py`.

**Metrics** (`evaluation/metrics.py`). MAE and RMSE are the standard mean absolute / root-mean-square errors. MAPE is percent error vs actual, skipping non-positive actuals (safe under the `Candle` contract). Directional accuracy vs `base_price` scores sign agreement of `(pred - base)` and `(actual - base)`; a flat prediction against a moved actual scores **0.5** rather than a free miss or hit. Sequential mode (no base) does the same on adjacent steps. Last-value forecasts therefore sit at ~0.5 DA whenever price moved — the intended null. Empty or length-mismatched inputs raise.

**Benjamini-Hochberg** (`evaluation/stats.py`). Implementation is the standard reverse-pass monotone adjustment: sort p ascending, set the last adjusted value to `p_(m)`, then `p̂_(i) = min((m/i) p_(i), p̂_(i+1))`, clamp to `[0, 1]`, map back to input order, reject if adjusted `<= alpha`. Empty input returns empty tuples. Out-of-range p-values raise. `alpha` is not validated. Tests check one rejection pattern (`[0.01, 0.04, 0.03, 0.20]` at `α=0.05`) and the empty path; they do not pin the numeric adjusted vector. The harness never calls this function — Stage 4 candidate comparison is the intended consumer.

**HarnessRunner** (`evaluation/harness.py`). For each split, models `predict` **only** `split.train` with `horizon_bars=test_bars`; actual test closes and the cutoff last close are used afterwards for `calculate_metrics`. That evaluation order does not leak. Summaries are unweighted means of per-split MAE/RMSE/DA/MAPE, rounded to 4 decimals. Insufficient depth raises. Per-split metrics are discarded. Models are typed as `Mapping[str, BaselineModel]`, so Stage 3 `ModelAdapter` will need a protocol or a harness generalization. The runner does not apply `WindowScaler`, `filter_completed_candles`, or `apply_point_in_time_splits`, and does not emit p-values for BH.

---

## Leakage-control map

| Control | Enforced where | On the harness path? |
|---|---|---|
| Train end strictly before test start | `WalkForwardSplit.__post_init__` + tests 2.1.3 / 2.3.1 | Yes |
| Model sees only train bars | `HarnessRunner.run` | Yes |
| Scaler fit isolated from test | `WindowScaler` + test 2.3.3 | No (baselines are unscaled prices) |
| Forming candle excluded | `filter_completed_candles` + test 2.3.4 | No |
| Future split does not rewrite cutoff history | `apply_point_in_time_splits` + test 2.3.5 | No |
| Target-shuffle collapse | test 2.3.2 only | n/a (see Finding 1) |

The splitter + harness loop is leakage-safe for already-final, unadjusted (or consistently adjusted) historical bars. Live bars and vendor retroactive corporate-action adjustment are guarded only by library helpers that the runner does not invoke.

---

## Stage 1 follow-up disposition

| Stage 1 item | Stage 2 status |
|---|---|
| Align Alpaca `adjustment=split` vs yfinance `auto_adjust=True` (split **and** dividend) | **Open.** Providers unchanged. PIT helper is a parallel layer on raw bars, not a provider policy. |
| Empty-result contract (Alpaca empty series vs yfinance `ProviderError`) | **Open.** |
| Live adequacy run on SPY/QQQ/AAPL/MSFT/NVDA | **Open.** Still synthetic-only. |
| Alpaca pagination page budget; cache naive-index localize | **Open.** |
| CRLF working copies vs LF in git | **Open.** Same 16 Stage 1 files. |

---

## Findings (non-blocking)

1. **Leakage Test 2 does not shuffle the model’s out-of-sample targets (follow-up).** `tests/test_leakage_target_shuffle.py` asserts `DriftBaseline` is 100% directionally accurate on a monotonic synthetic trend (tautological for that series), then permutes a hand-built `[1,0,1,0,…]` label vector against an identical prediction vector. The permutation never uses `forecast.point_forecasts` or the test closes. A model that leaked future labels would still pass. Rebuild the test to freeze predictions from `split.train`, shuffle `split.test` closes (or signs vs cutoff), and require mean shuffled accuracy to collapse toward chance while unshuffled accuracy stays high.

2. **PIT adjustment is not on the evaluation path (follow-up).** `apply_point_in_time_splits` is correct in isolation, but `HarnessRunner` evaluates whatever series it is given. Alpaca already returns `adjustment=split` as-of today, which retroactively rewrites cutoff-T history with splits that had not occurred at T. The helper also assumes **raw** bars; applying it to vendor-adjusted bars would double-adjust. Stage 4 live benchmarks need: raw (or reconstructable) bars, a corporate-action calendar, PIT as-of each cutoff, and a single split/dividend policy across providers. Until then, leakage test 5 does not protect harness runs on provider data.

3. **No embargo and no train/cal/test three-way split (follow-up).** Plan 2.1.2 names a calibration partitioner; the implementation treats train as calibration. Overlapping test windows across origins are standard rolling-origin behavior. Once models use lagged features of width W or Stage 3 Platt/isotonic calibration, splits need a purge gap and a held-out cal window that is not the test window.

4. **`MovingAverageBaseline` is SMA-only (coverage gap).** Plan 2.2.5 specified “SMA/EMA path”. Drift is first-to-last price slope, not a return. Neither is wrong as a naive null; document the definitions before Stage 4 model-vs-baseline claims.

5. **BH and scaler/candle/PIT helpers are unused by the harness (integration gap).** Standalone modules are fine for Stage 2. Stage 4 “harness comparisons with Benjamini-Hochberg” must actually call `benjamini_hochberg_correction`. Live or streaming evaluation must call `filter_completed_candles` before the last train bar is taken as cutoff.

6. **PIT helper data loss / bounds (nits).** Rebuilt candles drop `vwap`/`amount`; bars after `as_of_time` are retained unadjusted; `effective_date` is tz-aware but not forced UTC; `SplitAction` is not re-exported from `trading_engine.data`. Daily completion in `filter_completed_candles` is a calendar day.

7. **Harness result shape (nit).** Only mean metrics are kept; per-split errors, cutoffs, and forecasts are discarded. `HarnessRunner.run` is typed to `BaselineModel`. Generalize before adapters land.

8. **Repo hygiene.** `plan.md` / `progress.md` not updated through 2.4.4 / 2.5.2. Mixed CRLF working copies remain.

No production-breaking defect was found in the walk-forward non-leakage invariant, baseline predict-on-train contract, `WindowScaler` fit isolation, PIT future-split exclusion, incomplete-candle cutoff, MAE/RMSE/DA formulas, BH step-up arithmetic, or the harness evaluation order.

---

## Gate decision

**Close Stage 2.** Proceed to Stage 3 (model-neutral contract, calibration, cost model) with Finding 1 (real target-shuffle test) and Finding 2 (PIT + provider adjustment policy on the harness path) on the Stage 3/4 backlog. Do not treat current leakage tests as sufficient evidence that live Alpaca/yfinance series are walk-forward safe.

Signed off: Grok, 2026-09-18.
