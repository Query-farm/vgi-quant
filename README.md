<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# vgi-quant

[![CI](https://github.com/Query-farm/vgi-quant/actions/workflows/ci.yml/badge.svg)](https://github.com/Query-farm/vgi-quant/actions/workflows/ci.yml)

A [VGI](https://query.farm) worker that brings **quantitative-finance math**
into DuckDB/SQL. It prices **European options and their Greeks** (Black-Scholes
analytic), **fixed-rate bonds** (price / yield / modified duration / convexity),
and computes **day-count year fractions** and discounting — as plain SQL scalar
functions, backed by [QuantLib](https://www.quantlib.org/) (the
[`QuantLib`](https://pypi.org/project/QuantLib/) Python wheel; modified BSD).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'quant' (TYPE vgi, LOCATION 'uv run quant_worker.py');

SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, 'call');        -- ~10.4506
SELECT quant.bs_delta(100, 100, 0.05, 0.2, 1, 'call');        -- ~0.6368
SELECT quant.bs_vega(100, 100, 0.05, 0.2, 1, 'call');         -- ~37.524 (per 1.00 vol)
SELECT quant.implied_vol(10.4506, 100, 100, 0.05, 1, 'call'); -- ~0.20
SELECT quant.bond_price(100, 0.05, 0.05, 10, 2);              -- ~100 (par bond)
SELECT quant.bond_yield(100, 100, 0.05, 10, 2);               -- ~0.05
SELECT quant.bond_duration(100, 0.05, 0.05, 10, 2);           -- ~7.80 (modified)
SELECT quant.bond_convexity(100, 0.05, 0.05, 10, 2);          -- ~73.65
SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360'); -- 181/360
SELECT quant.discount_factor(0.05, 1);                        -- exp(-0.05) ~0.9512
SELECT quant.present_value(100, 0.05, 1);                     -- ~95.123
SELECT * FROM quant.day_count_conventions();
```

Everything runs **offline and deterministically** — pure numerical compute, the
same input always gives the same answer. QuantLib is imported once at worker
start-up and reused for the process lifetime.

## Scalars (per-row) vs. table functions (discovery)

The split follows what the VGI SDK allows for each function shape:

* **Scalars** take **positional** arguments only and resolve overloads by
  *arity* (DuckDB's `name := value` syntax is a table-function/macro feature,
  not a scalar one). Every per-row answer is a **scalar**, so it works inline in
  any projection or predicate. The trailing `opt_type` (`'call'`/`'put'`),
  `freq` (`1`/`2`/`4`/`12`) and `convention` arguments are passed positionally:

  ```sql
  SELECT id, bs_price(spot, strike, 0.05, vol, ttm, 'call') FROM positions;
  SELECT bond_yield(price, 100, 0.05, 10, 2)                 FROM holdings;
  SELECT year_fraction(start, end, 'ACT/360')               FROM accruals;
  ```

* **Table functions** return *many* rows. Here, one discovery function:
  `day_count_conventions()`.

  ```sql
  SELECT * FROM quant.day_count_conventions() ORDER BY name;
  ```

**NULL semantics.** A NULL input cell yields a NULL output cell for every
function. **Invalid (non-NULL) inputs raise a clear error** rather than
returning a silent wrong answer: `ttm <= 0`, negative volatility, `years <= 0`,
non-positive spot/strike/face/price, an unknown `opt_type` / `convention` /
`freq`, or a price outside the no-arbitrage bounds for `implied_vol`.

## Function catalog

| Function | Form | Signature | Returns |
| --- | --- | --- | --- |
| `bs_price` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` |
| `bs_delta` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` |
| `bs_gamma` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` |
| `bs_vega` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` (per 1.00 vol) |
| `bs_theta` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` (per year) |
| `bs_rho` | scalar | `(spot, strike, rate, vol, ttm, opt_type)` | `DOUBLE` (per 1.00 rate) |
| `implied_vol` | scalar | `(price, spot, strike, rate, ttm, opt_type)` | `DOUBLE` |
| `bond_price` | scalar | `(face, coupon_rate, yield_rate, years, freq)` | `DOUBLE` (clean) |
| `bond_yield` | scalar | `(price, face, coupon_rate, years, freq)` | `DOUBLE` |
| `bond_duration` | scalar | `(face, coupon_rate, yield_rate, years, freq)` | `DOUBLE` (modified) |
| `bond_convexity` | scalar | `(face, coupon_rate, yield_rate, years, freq)` | `DOUBLE` |
| `year_fraction` | scalar | `(start DATE, end DATE, convention)` | `DOUBLE` |
| `discount_factor` | scalar | `(rate, ttm)` | `DOUBLE` |
| `present_value` | scalar | `(amount, rate, ttm)` | `DOUBLE` |
| `day_count_conventions` | table | `()` | `(name VARCHAR)` |

## Conventions and sign choices

* **Options** use the analytic Black-Scholes formula (QuantLib
  `BlackCalculator`) with forward `F = spot * exp(rate * ttm)` and discount
  `exp(-rate * ttm)`; there is **no dividend yield** (carry == rate). `opt_type`
  is `'call'` or `'put'`; `ttm` is in years; `rate` and `vol` are annualized.
  * `bs_delta` — `d(value)/d(spot)`.
  * `bs_gamma` — `d2(value)/d(spot)2`.
  * `bs_vega` — `d(value)/d(vol)`, **per 1.00** (100 percentage points) of
    volatility. Divide by 100 for the "per 1% vol" desk convention.
  * `bs_theta` — `d(value)/d(t)`, **per year** (calendar). Divide by 365 for
    per-day.
  * `bs_rho` — `d(value)/d(rate)`, **per 1.00** (100 percentage points) of rate.

* **Bonds** are `FixedRateBond` instruments built from the worker's pinned
  evaluation date with an `ActualActual(ISDA)` day count and `Compounded` yields
  at the coupon `freq`. `bond_price` / `bond_yield` use the **clean** price; a
  par bond (`coupon_rate == yield_rate`) prices to `face`. `bond_duration` is
  **modified** duration. `years` is whole years; `freq` is `1` (annual), `2`
  (semiannual), `4` (quarterly) or `12` (monthly).

* **Day-count** `year_fraction` supports `ACT/360`, `ACT/365`, `30/360`
  (US bond basis) and `ACT/ACT` (ISDA). `discount_factor` / `present_value` use
  continuous compounding.

## Day-count conventions

`day_count_conventions()` lists every convention string `year_fraction` accepts
(currently `ACT/360`, `ACT/365`, `30/360`, `ACT/ACT`). An unknown convention
raises a clear error.

## Development

```sh
uv sync --extra dev
uv run pytest -q                 # unit + integration (in-process)
make test-sql                    # end-to-end SQL via haybarn-unittest
uv run ruff check . && uv run mypy vgi_quant/
```

`make test-sql` needs `haybarn-unittest` (`uv tool install haybarn-unittest`)
on `PATH` (`export PATH="$HOME/.local/bin:$PATH"`); the Makefile points
`VGI_QUANT_WORKER` at the worker run as a `uv` stdio subprocess.

## License

MIT (see [LICENSE](LICENSE)). QuantLib is distributed under a permissive
modified-BSD license.

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

