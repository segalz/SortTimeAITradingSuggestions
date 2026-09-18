# Stage 1 Sign-Off Audit

**Stage:** 1 — Environment, Tooling, Packaging & Data Adequacy
**Reviewer:** Grok (Reviewer Model)
**Date:** 2026-09-18
**HEAD:** `b4c6ba7` (`feat(data): implement benchmarks and audit utilities with tests (1.6.1-1.6.5)`)
**Verdict:** **APPROVED WITH FOLLOW-UPS** — Stage 1 gate may close; listed items are Stage 2 carry-forwards, not blockers.

---

## Evidence

- Independent re-run: `python.exe -m pytest -q` → **73 passed in 1.39s** (CPython 3.12).
- Scope reviewed: `pyproject.toml`, `config.py`, `data/models.py`, `providers/{base,alpaca,yfinance}.py`, `cache.py`, `audit.py`, `benchmarks.py`, and the nine test modules.
- Working tree has CRLF/LF noise on 16 already-committed files (`git ls-files --eol` shows `i/lf w/crlf`). Content is otherwise identical to HEAD; no functional uncommitted delta.

Test inventory: scaffolding 1, config 22, candle 7, bar series 4, DataFrame roundtrip 7, Alpaca 7, yfinance 8, cache 8, audit/benchmarks 9.

---

## Requirement coverage (plan 1.1–1.7)

| Step | Intent | Status |
|---|---|---|
| 1.1 Scaffolding & Hatchling | `src/` layout, pytest `pythonpath`, `.gitignore` (`keys.env`, parquet, cache) | Met |
| 1.2 Config & secrets | Frozen `Settings`, paper-only `PK` keys, unconditional `AK` reject, redacted `__repr__` | Met |
| 1.3 Candle / BarSeries | UTC-only timestamps, OHLC bounds, monotonic series, DataFrame roundtrip | Met |
| 1.4 Providers | ABC + Alpaca pagination (1m/5m/15m/1h/1d) + yfinance with mocked error paths | Met |
| 1.5 Parquet cache | Canonical `SYMBOL/timeframe.parquet`, atomic `.tmp` replace, merge/dedupe, range load | Met |
| 1.6 Adequacy audit | `SPY,QQQ,AAPL,MSFT,NVDA`; 30% split/div spike detector; depth + gap checker | Met (synthetic only) |
| 1.7 Gate | Full unit regression + this report | Met |

`plan.md` / `progress.md` still mark 1.6–1.7 pending. Implementation and tests are complete; the ledger is stale.

---

## Module assessment

**Config.** Paper-only rule is the strongest control in the stage: live `AK…` keys are rejected even when `require_alpaca=False`. Secrets never appear in `repr`/`redact_secret`. Alias env names (`ALPACA_API_KEY_ID`, `ALPACA_API_KEY`) are accepted but not cleared by `tests/test_config.py`'s autouse fixture — isolation gap only.

**Data contracts.** `Candle` rejects naive/non-UTC timestamps, non-finite or non-positive prices, inverted high/low, and open/close outside `[low, high]`. `BarSeries` uppercases the symbol and raises `DataQualityError` on non-monotonic timestamps. Roundtrip preserves optional `vwap`/`amount`. Timeframe strings are not normalized on the model (the cache lowercases them).

**Alpaca.** Injected `httpx` client, `next_page_token` pagination, `adjustment=split`, `feed=iex`, `limit=10000`. HTTP and malformed-bar errors wrap as `ProviderError`. Empty `bars: []` returns an empty `BarSeries` rather than erroring. Loop exits only on `next_page_token is None` (no max-page cap; empty-string tokens would spin).

**yfinance.** Supported timeframes match Alpaca. `auto_adjust=True` applies **split and dividend** adjustment. Empty/NaN/missing-column paths raise `ProviderError`. Naive index values are assumed UTC (`_index_to_utc_datetime`); tz-aware values (typical yfinance NYSE output) convert correctly.

**Cache.** Partition path `base_dir / SYMBOL / {tf}.parquet`, merge with `keep="last"`, UTC filter on load, empty save rejected. Writes are atomic (`replace`). Naive Parquet indexes are silently `tz_localize(UTC)` instead of failing the contract.

**Audit.** Default 30% close-to-open jump catches 2-for-1, 3-for-2, and reverse splits on synthetic series. Depth checker flags empty series, `min_bars`, and optional hour gaps. No exchange calendar, so weekend/holiday gaps must be parameterized by the caller. Detectors have not been run against live benchmark history.

---

## Findings (non-blocking)

1. **Adjustment policy mismatch (follow-up).** Alpaca requests `adjustment=split`; yfinance uses `auto_adjust=True` (splits **and** dividends). Mixing providers on the same symbol will not yield a bit-identical series. Align both to one policy before Stage 2 leakage test 2.3.5.
2. **Empty-result contract mismatch (follow-up).** Alpaca returns an empty `BarSeries`; yfinance raises `ProviderError`. Callers cannot treat providers interchangeably on a dry range.
3. **No live adequacy run (accepted Stage 1 gap).** 1.6 utilities are unit-tested only. Stage 2 should fetch the five benchmark symbols, run `detect_split_spikes` / `check_contiguous_depth`, and persist the result before walk-forward splits are trusted.
4. **Pagination / cache robustness (nits).** Alpaca pagination has no page budget; cache load localizes naive indexes instead of raising `DataContractError`.
5. **Repo hygiene.** Mixed CRLF working copies vs LF in git; `progress.md` not updated through 1.6.5.

No production-breaking defect was found in the paper-key guard, UTC contract, monotonic series, atomic cache write, or mocked provider error paths.

---

## Gate decision

**Close Stage 1.** Proceed to Stage 2 (walk-forward harness & leakage tests) with the three follow-ups above on the Stage 2 backlog, especially a single corporate-action adjustment policy.

Signed off: Grok, 2026-09-18.
