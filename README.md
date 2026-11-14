<p align="center">
  <img src="https://query.farm/media-kit/products/vgi/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# Option Pricing, Greeks, Bond & Carry Analytics in DuckDB

> **vgi-quant** · a [Query.Farm](https://query.farm) VGI worker · powered by QuantLib

[![CI](https://github.com/Query-farm/vgi-quant/actions/workflows/ci.yml/badge.svg)](https://github.com/Query-farm/vgi-quant/actions/workflows/ci.yml)

A [VGI](https://query.farm) worker that brings **quantitative-finance math**
into DuckDB/SQL. It prices **European options and their Greeks** (Black-Scholes
analytic), **fixed-rate bonds** (price / yield / modified duration / convexity),
and computes **day-count year fractions** and discounting — as plain SQL scalar
functions, backed by [QuantLib](https://www.quantlib.org/) (the
[`QuantLib`](https://pypi.org/project/QuantLib/) Python wheel; modified BSD).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'quant' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-quant@v0.5.0 vgi-quant-worker');

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

## Quick start

The worker isn't on PyPI; [uv](https://docs.astral.sh/uv/) runs it straight from a tagged release on GitHub. `uvx` builds an isolated environment on the first ATTACH and reuses it afterwards:

```sql
INSTALL vgi FROM community;
LOAD vgi;

ATTACH 'quant' AS quant (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-quant@v0.5.0 vgi-quant-worker');

-- Black-Scholes fair value of an at-the-money 1-year European call.
SELECT quant.main.bs_price(100, 100, 0.05, 0.2, 1, 'call') AS call_price;

-- Delta (hedge ratio) of that same at-the-money call.
SELECT quant.main.bs_delta(100, 100, 0.05, 0.2, 1, 'call') AS delta;
```

Change `@v0.5.0` to move to a newer release.

### Other ways to run it

- **Docker** (the image bundles the worker and its dependencies):

  ```sql
  ATTACH 'quant' AS quant (TYPE vgi, LOCATION 'docker://ghcr.io/query-farm/vgi-quant:0.4.0');
  ```

- **From a local checkout** (`git clone https://github.com/Query-farm/vgi-quant`), point `LOCATION` at `uv run --project /path/to/vgi-quant vgi-quant-worker`.

### Build from source

To build and test the worker yourself from a checkout, see [Development](#development).

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
  SELECT year_fraction(start_date, end_date, 'ACT/360')     FROM accruals;
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
| `implied_carry_rate` | scalar | `(spot, forward, ttm)` | `DOUBLE` (continuous annual rate) |
| `calendar_spread_rate` | scalar | `(near_price, far_price, near_ttm, far_ttm)` | `DOUBLE` (continuous annual rate) |
| `box_spread_rate` | scalar | `(box_price, low_strike, high_strike, ttm)` | `DOUBLE` (continuous annual rate) |
| `tbill_rate` | scalar | `(discount_rate, days)` | `DOUBLE` (continuous annual rate) |
| `funding_rate_annual` | scalar | `(rate, interval_hours)` | `DOUBLE` (continuous annual rate) |
| `simple_to_continuous` | scalar | `(rate, ttm)` | `DOUBLE` |
| `continuous_to_simple` | scalar | `(rate, ttm)` | `DOUBLE` |
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

## Combining functions

Because every answer is a scalar, one function's output can feed another. Here
quoted prices go through `implied_vol`, and each strike is then hedged at its
own implied vol with `bs_delta`:

```sql
WITH quotes(strike, price) AS (VALUES (90, 14.50), (100, 8.20), (110, 3.90)),
smile AS (
  SELECT strike, quant.implied_vol(price, 100, strike, 0.05, 0.5, 'call') AS iv
  FROM quotes
)
SELECT strike,
       ROUND(iv, 4)                                                AS iv,    -- 0.2531, 0.2478, 0.2378
       ROUND(quant.bs_delta(100, strike, 0.05, iv, 0.5, 'call'), 4) AS delta -- 0.7933, 0.5911, 0.3692
FROM smile
ORDER BY strike;
```

## Carry: comparing financing rates

The carry functions turn one instrument's quote into a **continuously
compounded annual rate**, the same basis as `rate` everywhere else in this
worker. With every instrument on one basis, a futures curve, a box spread, a
Treasury bill and a perp funding rate can be compared or subtracted directly.

| Function | Formula | Read it as |
| --- | --- | --- |
| `implied_carry_rate(spot, forward, ttm)` | `ln(forward/spot)/ttm` | net cost of carry (financing minus income); negative in backwardation |
| `calendar_spread_rate(near, far, near_ttm, far_ttm)` | `ln(far/near)/(far_ttm-near_ttm)` | forward rate between two futures expiries |
| `box_spread_rate(box_price, low, high, ttm)` | `ln((high-low)/box_price)/ttm` | rate a box buyer lends at; `box_price = call(low) - call(high) + put(high) - put(low)` |
| `tbill_rate(discount_rate, days)` | `-ln(1 - d*days/360)/(days/365)` | a bank-discount bill quote (e.g. `^IRX`) as a true rate |
| `funding_rate_annual(rate, interval_hours)` | `ln(1+rate)*8760/interval_hours` | perp funding a short earns (positive = longs pay) |
| `simple_to_continuous(rate, ttm)` / `continuous_to_simple(rate, ttm)` | `ln(1+r*t)/t` / `(exp(r*t)-1)/t` | move between quoting bases |

```sql
-- Gold cash-and-carry vs cash, and a short perp hedged with a long future.
SELECT ROUND(quant.implied_carry_rate(4000, 4050, 0.25), 4)                     AS futures_carry, -- 0.0497
       ROUND(quant.tbill_rate(0.0412, 91), 4)                                    AS bill,          -- 0.0420
       ROUND(quant.box_spread_rate(989, 5000, 6000, 0.25), 4)                    AS box,           -- 0.0442
       ROUND(quant.funding_rate_annual(0.0001, 8)
             - quant.implied_carry_rate(4000, 4050, 0.25), 4)                    AS perp_vs_futures; -- 0.0598
```

The inputs come from other workers: futures and spot prices from
`vgi-yfinance`, option legs from `vgi-tastytrade`, bill quotes from
`vgi-treasury` or `vgi-fred`, and funding rates from `vgi-perps` (which already
annualizes them; use `funding_rate_annual` on raw venue rates).

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

`make test-sql` needs `haybarn-unittest` (`uv tool install --prerelease allow 'haybarn-unittest>=2.0.0rc11,<2.1'`)
on `PATH` (`export PATH="$HOME/.local/bin:$PATH"`); the Makefile points
`VGI_QUANT_WORKER` at the worker run as a `uv` stdio subprocess.

## License

MIT (see [LICENSE](LICENSE)). QuantLib is distributed under a permissive
modified-BSD license.

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

