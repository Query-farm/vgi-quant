# Quantitative Finance Math examples

Three independently executable stories use invented model inputs and actual released SQL results:

- [How far can local Greeks approximate a price move?](01_local_greeks_and_full_repricing.ipynb) preserves the original spot-shock investigation, comparing fixed delta/gamma approximations with full repricing and checking implied volatility, parity and local derivatives.
- [What does a bond quote change measure?](02_clean_quotes_and_yield_shocks.ipynb) verifies clean-price quote units before comparing yield shocks, modified duration, convexity and yield inversion across three fixed schedules.
- [Can identical payment dates produce different present values?](03_dates_conventions_and_present_value.ipynb) evaluates all four advertised day counts, retains known-zero/missing-date rows, and reconciles discount factors and known-payment subtotals.

## Run locally or in Colab

Open a notebook's Colab badge and run all. Setup installs the base shared package and retrieves two immutable hash-verified presentation/provenance companions. With [uv](https://docs.astral.sh/uv/) and Git installed, a copy of this directory runs independently of the worker checkout:

```bash
uv sync --locked
uv run --locked vgi-notebooks 01_local_greeks_and_full_repricing.ipynb
uv run --locked vgi-notebooks 02_clean_quotes_and_yield_shocks.ipynb
uv run --locked vgi-notebooks 03_dates_conventions_and_present_value.ipynb
```

The local lock includes the shared `[runner]` extra. Colab installs only the base package, preserving existing kernel/Jupyter libraries. An optional local kernel:

```bash
uv run --locked python -m ipykernel install --user --name vgi-quant-notebooks --display-name 'Python (VGI Quant examples)'
```

All books use the literal short released-worker command:

```sql
ATTACH 'quant' (TYPE vgi, LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-quant@v0.5.0 vgi-quant-worker');
```

No local source, worker build or transitive dependency overrides are needed. First use needs internet for public packages and the published Haybarn/VGI extension; calculations are local and require no account, credentials or model downloads. Each connection creates a temporary empty SQL-secret directory, disables persistent secrets and checks the inventory before attachment and at cleanup. Actual resolved worker package versions are retained in [coverage](coverage/resolved-worker-packages.json); the Git release declares dependency ranges, so future resolutions need validation.

## Focused experiments

Each changes one parameter and writes a separate copy:

```bash
uv run --locked vgi-notebooks 01_local_greeks_and_full_repricing.ipynb \
  --parameters '{"MAX_MOVE_PCT":20}' --output-dir artifacts/wider-spot
uv run --locked vgi-notebooks 02_clean_quotes_and_yield_shocks.ipynb \
  --parameters '{"YIELD_RANGE_BP":200}' --output-dir artifacts/wider-yield
uv run --locked vgi-notebooks 03_dates_conventions_and_present_value.ipynb \
  --parameters '{"CONTINUOUS_RATE":0.10}' --output-dir artifacts/higher-rate
```

The spot and yield experiments widen fixed-spacing grids while preserving baseline sensitivities and shared grid points. The rate experiment leaves dates, amounts and all year fractions unchanged. Known-zero and missing-date records retain their states. The runner rejects unknown parameters and unsafe output destinations and preserves the successful default on failure.

## Model conventions and observed runtime limits

All prices, dates, amounts and rates are authored examples, not observed market data or positions. No trades or external writes are performed. These are internal model comparisons, not accuracy estimates, recommendations, hedge-profit tests or forecasts.

- Options use a no-dividend European Black–Scholes model with continuous rates. Price and price-change units are per one underlying unit, with no contract multiplier. Delta and gamma remain fixed at the initial spot. Implied-volatility tolerance accounts for inversion accuracy in standard-deviation units.
- Bonds use the worker's pinned evaluation/start date **2026-06-15**, whole-year maturities, Actual/Actual ISDA, null calendar/unadjusted dates and semiannual compounding. At this issue-date snapshot there is no elapsed coupon accrual. Results do not describe later settlement or a complete market yield curve.
- **Bond quote discrepancy:** the released/current catalog prose says par prices near face value. Actual `bond_price` returns a clean quote **per 100 nominal**: face 100 and 1,000 both return approximately 99.999920 for the tested par instrument. The notebook displays that probe and explains `quote × face / 100` as a clean cash-equivalent amount. Source is preserved.
- **Constant-argument execution limitation:** the actual v0.5.0/Haybarn rc11 probe returns identical call values when different call/put constants appear in one vectorized SELECT. Materializing calls and puts in separate statements restores their distinct prices; parity and textbook anchors verify the workaround. Day-count variants also use separate statements. This is a measured execution-path limitation, not a financial-model identity.
- Day-count strings are planning-time literals. `ACT/ACT` means ISDA and `30/360` means US BondBasis. Discounting is continuous. Holding the same numeric rate across conventions is a controlled model comparison, not conversion of a contractual quote. The five-valued-row subtotal excludes a sixth missing-date amount explicitly; it is never labeled a complete-schedule value.

## Coverage and validation

Actual release v0.5.0 exposes **22 logical named surfaces**: 22 function rows plus the same-named `day_count_conventions` physical table alias, counted once. There are no views, COPY handlers or authenticated/write operations. The stories meaningfully cover **12/22 released surfaces** and **12/22 reviewed current interfaces**, exceeding the required 11. The ten uncovered names remain explicit: `bs_vega`, `bs_theta`, `bs_rho`, `implied_carry_rate`, `calendar_spread_rate`, `box_spread_rate`, `tbill_rate`, `funding_rate_annual`, `simple_to_continuous` and `continuous_to_simple`.

[coverage.json](coverage.json) binds full runtime inventories, native arguments, source comparison, visible SQL, interpreted results and successful saved execution receipts. Current public source **43beb22ff9675305cfa9809a3ad2e130b46d5109** adds composed examples/metadata, with numerical methods, registration, schemas and root dependencies unchanged. Exact-current runtime count is **0**, distinct from reviewed interface compatibility. Proper title/subtitle come from actual released catalog metadata.

Default notebooks contain 13, 10 and 11 SQL invariants respectively, plus face-amount/registry checks. Each default and separate parameter experiment runs the actual release. A fresh notebook-only Python 3.12 kernel preloads eight plotting/Jupyter libraries and checks unchanged versions plus `pip check`; this is Colab-compatible setup validation, not manual operation of hosted Colab. All default and experiment figures are reviewed. SVG geometry/text and content-addressed GitHub images are committed; generated logs, PNG reviews and experiment copies remain ignored.

Worker source is unchanged; its [existing green source CI](https://github.com/Query-farm/vgi-quant/actions/runs/43578820458) is reused. No worker rebuild, repeated full source suite or deployment is performed. [STANDARD.md](STANDARD.md) points to the maintained shared standard.
