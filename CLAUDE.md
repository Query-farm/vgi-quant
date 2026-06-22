# CLAUDE.md — vgi-quant

Contributor/agent notes. User-facing docs live in `README.md`; this is the
"how it's built and where the sharp edges are" companion.

## What this is

A [VGI](https://query.farm) worker that brings **quantitative-finance math** —
European option pricing + Greeks (Black-Scholes analytic), fixed-rate bond
pricing / yield / modified duration / convexity, and day-count year fractions —
into DuckDB as scalar functions, plus one discovery table function. Backed by
[QuantLib](https://www.quantlib.org/) (the `QuantLib` Python wheel; modified
BSD — permissive). `quant_worker.py` assembles every function into one `quant`
catalog (single `main` schema) over stdio. Sibling style/tooling to
`vgi-conform` / `vgi-calendar`.

## Layout

```
quant_worker.py        repo-root stdio entry point; PEP 723 inline deps; main()
vgi_quant/
  quant.py             pure compute over QuantLib; no Arrow/VGI; unit-testable
  scalars.py           per-row scalars (options/bonds/conventions)
  tables.py            discovery table function: day_count_conventions
  schema_utils.py      pa.Field comment / column-doc helper
tests/                 pytest: test_quant (pure), test_tables (in-proc), test_scalars (Client RPC)
test/sql/*.test        haybarn-unittest sqllogictest — authoritative E2E
Makefile               test / test-unit / test-sql / lint
```

To add a function: implement the math in `quant.py` (pure; raise `ValueError`
on bad input), wrap it as a scalar/table function in the matching module,
register it in `quant_worker.py`'s `_FUNCTIONS`.

## Scalars vs table functions — THE core convention (read first)

The VGI SDK makes **scalar functions positional-only**: `name := value` named
args are rejected for scalars and only work on table functions.

- **Every per-row answer is a scalar.** The trailing constant arguments —
  `opt_type` (`'call'`/`'put'`), bond `freq` (`1`/`2`/`4`/`12`) and the
  day-count `convention` — are `ConstParam`s (constant, planning-time values),
  *not* per-row columns. In SQL they must be **literals**; you cannot pass a
  column reference (this is why `conventions.test` exercises each convention
  with a string literal rather than cross-joining `day_count_conventions()`).
- **The single set-returning function is a table function**:
  `day_count_conventions()`.
- The six BS price/Greek scalars share one 6-arg signature, so they are built by
  a small factory (`_make_option_scalar`) in `scalars.py`. A nested `class Meta`
  *inside a function* **can** read the function's locals (`name = fname` works);
  the gotcha that bites in sibling repos is a class nested *inside another class*
  (a class body is not a closure) — not the case here.

## Numerical conventions and sign choices (documented + tested)

- **Options** use the analytic Black-Scholes formula via `ql.BlackCalculator`
  with forward `F = spot * exp(rate*ttm)`, discount `exp(-rate*ttm)`,
  `stdDev = vol * sqrt(ttm)`. **No dividend yield** (carry == rate). Using
  `BlackCalculator` (rather than building a dated `EuropeanExercise`) lets `ttm`
  be an exact real number of years instead of an integer day count.
  - `bs_delta` = d/d(spot); `bs_gamma` = d2/d(spot)2.
  - `bs_vega` is **per 1.00 vol** (≈37.52 ATM 1y, i.e. per 100% — divide by 100
    for per-1%). `bs_theta` is **per year** (`thetaPerDay` = /365). `bs_rho` is
    **per 1.00 rate**.
- **Bonds** are `FixedRateBond` built from the pinned `_EVAL_DATE`
  (2026-06-15) with `ActualActual(ISDA)` and `Compounded` yields at the coupon
  frequency; `bond_price`/`bond_yield` use the **clean** price. A par bond
  (`coupon == yield`) prices to ~`face` (≈99.9999 before rounding, from
  ActualActual coupon-period rounding — `ROUND(...,2)` gives `100.00`).
  `bond_duration` is **modified** duration. `years` is whole years.
- **Day-count** `year_fraction`: `ACT/360`, `ACT/365`, `30/360` (US BondBasis),
  `ACT/ACT` (ISDA); convention strings are upper-cased before lookup (so
  `act/360` == `ACT/360`). `discount_factor`/`present_value` are continuous.

## Sharp edges (learned the hard way)

1. **`haybarn-unittest` skips `require vgi`.** Under haybarn the extension is not
   autoloaded for `require`, so a `.test` using `require vgi` is silently
   SKIPPED. Use an explicit `statement ok` / `LOAD vgi;` (every `.test` here
   does), then `ATTACH 'quant' ... (TYPE vgi, LOCATION '${VGI_QUANT_WORKER}')`.
2. **NULL vs invalid vs error — three distinct outcomes.** Any NULL input cell →
   NULL output cell (the row is skipped in `_map_floats` / `_map_dates`).
   **Invalid (non-NULL) input raises** — `ttm<=0`, negative vol, `years<=0`,
   non-positive spot/strike/face/price, an unknown `opt_type`/`convention`/
   `freq`, or a non-invertible `implied_vol` price. These surface as clear
   DuckDB errors; SQL covers them with `statement error` blocks. There is **no**
   silent-NULL-on-bad-input here (unlike conform's formatters) — quant inputs are
   numeric and a wrong answer is worse than an error.
3. **Assert with tolerance, never exact floats.** SQL uses `ROUND(...)`; pytest
   uses `pytest.approx`. QuantLib results are deterministic but not bit-exact to
   hand formulas.
4. **QuantLib is an expensive import — imported once** at `quant.py` module load;
   the day-count factory table and bond day counter are module-level singletons.
   The process-wide `evaluationDate` is pinned for determinism.
5. **`implied_vol` argument order is `(price, spot, strike, rate, ttm, opt_type)`**
   — `price` first, and it has **no `vol`** (that's what it solves for).
6. **The unit suite can pass while the RPC path is broken.** `test_quant.py`
   calls pure functions directly; only `test_scalars.py` (real `vgi.client.Client`
   subprocess) and `test/sql/*.test` (real `ATTACH`+`SELECT`) exercise the wire.
   **Run the SQL suite** — it's authoritative. If `make test-sql` flakes, re-run
   2–3×; only a *consistent* failure is real.

## Textbook values validated

- BS call spot=strike=100, rate=0.05, vol=0.2, ttm=1: price ≈ **10.4506**,
  delta ≈ **0.6368**, vega ≈ **37.524** (per 1.00 vol).
- Put-call parity `C - P == spot - strike*exp(-rate*ttm)`.
- `implied_vol` round-trips the BS price back to vol ≈ **0.20** (call and put).
- Par bond (coupon==yield==0.05, 10y, semiannual) prices to **100**;
  `bond_yield` inverts it to **0.05**; modified duration ≈ **7.80**, convexity ≈
  **73.65** (both positive, duration < maturity).
- `year_fraction(2026-01-01, 2026-07-01, 'ACT/360')` = **181/360 ≈ 0.5028**;
  `'30/360'` = **0.5**.

## Licensing

vgi-quant's own code is **MIT** (see `LICENSE`). The sole runtime dependency
besides the VGI SDK is **QuantLib** (the `QuantLib` PyPI wheel), distributed
under a permissive **modified-BSD** license — no copyleft caveat, fine for
commercial use, used as an ordinary unmodified pip dependency.

## Testing

```sh
uv sync --extra dev
uv run pytest -q              # unit: pure logic + in-proc table + Client RPC scalars
make test-sql                 # E2E: haybarn-unittest over test/sql/*  (authoritative)
make test                     # both
uv run ruff check . && uv run mypy vgi_quant/
```

`make test-sql` sets `VGI_QUANT_WORKER="uv run --python 3.13 quant_worker.py"`,
puts `~/.local/bin` on PATH, and runs `haybarn-unittest --test-dir . "test/sql/*"`.
Install the runner once: `uv tool install haybarn-unittest`. CI
(`.github/workflows/ci.yml`) runs unit + lint + a gated `e2e` job that installs
haybarn-unittest and runs `make test-sql`. Everything is pure/offline (no
network, no model downloads) — fast and hermetic.
