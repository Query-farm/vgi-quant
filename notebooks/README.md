# Quant SQL notebooks

[How far can local Greeks approximate a price move?](01_local_greeks_and_full_repricing.ipynb) compares full QuantLib call repricing with delta-only and delta-plus-gamma approximations, checks put–call parity and implied-volatility inversion, and verifies the local Greeks with independent small price bumps.

## Run from this directory

Install [uv](https://docs.astral.sh/uv/) and Git. The notebook uses Python 3.13 or 3.14; its separate worker explicitly uses Python 3.13. First use requires network access for dependencies, the published Haybarn/VGI extension and the pinned worker Git revision. Calculations then run locally without market data. A copy of this entire directory works without the worker source checkout or a local worker build.

```bash
uv sync --frozen
uv run --frozen python execute.py
```

The visible SQL launches `uvx --python 3.13 --with vgi-python==0.51.0 --with vgi-rpc==0.53.1 --with QuantLib==1.44 --from git+https://github.com/Query-farm/vgi-quant@5ccb584b8783909bc5383cf514c8905d53f13f6d vgi-quant-worker`. The worker library and SDK versions match its tested lock. The independent notebook lock pins Haybarn 2.0.0rc11. Rerun both scenarios after upgrading any pin.

For interactive use, register the interpreter and select it in Jupyter:

```bash
uv run --frozen python -m ipykernel install --user --name vgi-quant-notebooks --display-name 'Python (vgi-quant notebooks)'
```

Restart and run all after changing `MAX_MOVE_PCT`. Setup, plotting, result-derived prose source and cleanup are folded; parameters and SQL remain visible. The runner creates a temporary kernel, uses the notebook directory as cwd, and saves outputs only after a successful run. Parameter overrides need a separate output directory; unknown parameters and the source directory as destination are rejected.

## Focused experiment

```bash
uv run --frozen python execute.py --parameters '{"MAX_MOVE_PCT":20}' --output-dir validation/wide-shocks
```

The default range is ±5%; the experiment widens it to ±20%. Both use 0.5-percentage-point steps, including zero. Baseline price, delta, gamma and the separate 0.01-price-unit finite-difference probe stay fixed. Compare maximum approximation errors and the signed residual chart, then restore 5.

[Provenance](fixtures/provenance.json) records the invented model inputs and units. Spot and strike are 100, annual volatility 20%, continuously compounded annual rate 3%, and time to expiry exactly 0.5 years. This horizon is not a calendar maturity or observed timestamp. Values use consistent quote-currency units per one underlying unit, without a contract multiplier.

## Checks and limits

Thirteen SQL checks cover scenario geometry, valid/finite values, call bounds, the zero-shock row, parity, volatility inversion, finite-difference Greeks, a separate textbook call/put anchor and monotonic call prices. Floating-point comparisons use tolerances. QuantLib inversion defaults to 1e-6 standard-deviation accuracy; with a half-year horizon this translates to roughly 1.4e-6 annual volatility, checked at 2e-6. The input provenance is checked separately. Domain calculations and scenario generation remain visible SQL; Python only plots or explains returned values.

**Observed published-runtime limitation:** vectorized `bs_price(...,'call')` and `bs_price(...,'put')` in the same SELECT returned identical call values in Haybarn 2.0.0rc11 with this pinned worker. The notebook materializes them in separate SQL statements, joins by shock, and verifies parity at every row plus a textbook one-year call/put anchor. No worker or engine patch is included.

Full repricing is an analytic result within this no-dividend European Black–Scholes model, not a market-observed price. Only spot changes: there is no elapsed time, changing volatility, trading cost or dynamic hedge. Local Taylor terms omit higher orders; the notebook measures their errors without requiring the quadratic approximation to win everywhere. Internal consistency does not establish market accuracy or hedge profitability.

Source validation: 90 pytest tests, 91 stdio / 101 HTTP / 91 Unix SQL assertions, Ruff/format, mypy, isolated pydoclint, and metadata quality 100/L2 with zero findings. The successful default is saved in the main notebook. Generated logs, chart images and experiment copies are ignored under `validation/`. The runner copies assets, provenance and runtime companions with experiment outputs. [STANDARD.md](STANDARD.md) records presentation conventions.
