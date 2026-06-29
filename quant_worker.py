# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.5",
#     "QuantLib>=1.42",
#     "pyarrow",
# ]
# ///
"""VGI worker bringing quantitative-finance math to DuckDB SQL via QuantLib.

Assembles the quant functions in ``vgi_quant`` into a single ``quant`` catalog
and runs the worker over stdio (DuckDB subprocess) or HTTP. It exposes option
pricing + Greeks (Black-Scholes analytic), fixed-rate bond pricing / yield /
duration / convexity, and day-count year fractions as DuckDB scalar functions,
plus one day-count discovery table function.

Usage:
    uv run quant_worker.py              # serve over stdio (DuckDB subprocess)

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'quant' (TYPE vgi, LOCATION 'uv run quant_worker.py');

    SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, 'call');   -- ~10.45
    SELECT quant.bs_delta(100, 100, 0.05, 0.2, 1, 'call');   -- ~0.637
    SELECT quant.implied_vol(10.45, 100, 100, 0.05, 1, 'call'); -- ~0.20
    SELECT quant.bond_price(100, 0.05, 0.05, 10, 2);         -- ~100 (par)
    SELECT quant.bond_yield(100, 100, 0.05, 10, 2);          -- ~0.05
    SELECT quant.bond_duration(100, 0.05, 0.05, 10, 2);      -- modified duration
    SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360');
    SELECT quant.discount_factor(0.05, 1);                   -- exp(-0.05)
    SELECT * FROM quant.day_count_conventions();
"""

from __future__ import annotations

import json

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_quant.scalars import SCALAR_FUNCTIONS
from vgi_quant.tables import TABLE_FUNCTIONS, TABLES

_FUNCTIONS: list[type] = [
    *SCALAR_FUNCTIONS,
    *TABLE_FUNCTIONS,
]

_CATALOG_DESCRIPTION_LLM = (
    "Quantitative-finance math for SQL: price European options and compute their Black-Scholes "
    "Greeks (price, delta, gamma, vega, theta, rho) and implied volatility; price fixed-rate bonds "
    "and invert price to yield to maturity, with modified duration and convexity; compute day-count "
    "year fractions ('ACT/360', 'ACT/365', '30/360', 'ACT/ACT') between two dates and continuously-"
    "compounded discount factors and present values. Backed by QuantLib. Use for option pricing, "
    "Greeks, bond analytics, yield/duration, and day-count / discounting questions in SQL."
)

_CATALOG_DESCRIPTION_MD = (
    "# Quantitative Finance Math in SQL\n\n"
    "![QuantLib logo](https://upload.wikimedia.org/wikipedia/commons/7/74/QL-title.jpg)\n\n"
    "**Price options, compute Black-Scholes Greeks, value fixed-rate bonds, and do day-count and "
    "discounting math directly in DuckDB SQL** — no spreadsheets, no external pricing service, no "
    "round-trips to Python. The `quant` catalog turns industry-standard quantitative-finance "
    "calculations into ordinary SQL functions you can call inline in any query.\n\n"
    "This extension is for analysts, quants, risk teams, and data engineers who keep their market "
    "data in DuckDB and want option pricing, implied volatility, bond analytics, and yield/duration "
    "math to live right next to the data. Because every calculation is exposed as a scalar function, "
    "you can price a whole portfolio in a single `SELECT`, filter on a computed Greek in a `WHERE` "
    "clause, or join model output back onto your positions — all with the speed of DuckDB's "
    "vectorized engine over Apache Arrow.\n\n"
    "Under the hood the math is backed by [QuantLib](https://www.quantlib.org/), the widely used "
    "open-source library for quantitative finance. QuantLib provides the analytic Black-Scholes "
    "option pricing, the fixed-rate bond pricing and yield solvers, and the day-count conventions "
    "this worker exposes. See the QuantLib "
    "[source code on GitHub](https://github.com/lballabio/QuantLib), the "
    "[official documentation](https://www.quantlib.org/docs.shtml), and the "
    "[Python bindings reference](https://quantlib-python-docs.readthedocs.io/) for the underlying "
    "models and conventions.\n\n"
    "## What you can compute\n\n"
    "**Option pricing & Greeks (Black-Scholes analytic):** `bs_price`, `bs_delta`, `bs_gamma`, "
    "`bs_vega`, `bs_theta`, `bs_rho`, and `implied_vol` to invert a market price back to volatility. "
    "Each option scalar takes `(spot, strike, rate, vol, ttm)` per-row columns plus a constant "
    "`opt_type` of `'call'` or `'put'`.\n\n"
    "**Fixed-rate bond analytics:** `bond_price` (clean price from a yield), `bond_yield` (yield to "
    "maturity solved from a price), `bond_duration` (modified duration), and `bond_convexity`. Bond "
    "scalars take a constant coupon `freq` of 1, 2, 4, or 12 payments per year.\n\n"
    "**Day-count & discounting:** `year_fraction` between two dates under a chosen `convention` "
    "(`'ACT/360'`, `'ACT/365'`, `'30/360'`, `'ACT/ACT'`), plus continuously-compounded "
    "`discount_factor` and `present_value`. The `day_count_conventions()` table function lists every "
    "supported convention string.\n\n"
    "## Example queries\n\n"
    "```sql\n"
    "SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, 'call');        -- ~10.45\n"
    "SELECT quant.bs_delta(100, 100, 0.05, 0.2, 1, 'call');        -- ~0.637\n"
    "SELECT quant.implied_vol(10.45, 100, 100, 0.05, 1, 'call');   -- ~0.20\n"
    "SELECT quant.bond_yield(100, 100, 0.05, 10, 2);               -- ~0.05\n"
    "SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360');\n"
    "SELECT * FROM quant.day_count_conventions() ORDER BY name;\n"
    "```\n\n"
    "Option and bond inputs are per-row columns, while `opt_type`, bond `freq`, and the day-count "
    "`convention` are constant (literal) arguments — so you can price an entire table of positions "
    "in one pass."
)

_SCHEMA_DESCRIPTION_LLM = (
    "Option pricing + Greeks (Black-Scholes), implied volatility, fixed-rate bond pricing / yield / "
    "modified duration / convexity, day-count year fractions, and continuous discounting / present "
    "value functions."
)

_SCHEMA_DESCRIPTION_MD = (
    "The single schema of the `quant` catalog, grouping every quantitative-finance "
    "function over Apache Arrow. It contains the Black-Scholes option scalars "
    "(`bs_price` plus the `bs_delta`/`bs_gamma`/`bs_vega`/`bs_theta`/`bs_rho` Greeks "
    "and `implied_vol`), the fixed-rate bond scalars (`bond_price`, `bond_yield`, "
    "`bond_duration`, `bond_convexity`), the day-count and continuous-discounting "
    "scalars (`year_fraction`, `discount_factor`, `present_value`), and the "
    "`day_count_conventions` reference table/function listing the accepted "
    "day-count convention strings. Use it for option pricing and Greeks, bond "
    "analytics, yield/duration, and day-count or present-value math directly in SQL."
)

_SCHEMA_EXAMPLE_QUERIES = (
    "SELECT quant.main.bs_price(100, 100, 0.05, 0.2, 1, 'call');\n"
    "SELECT quant.main.bs_delta(100, 100, 0.05, 0.2, 1, 'call');\n"
    "SELECT quant.main.implied_vol(10.45, 100, 100, 0.05, 1, 'call');\n"
    "SELECT quant.main.bond_price(100, 0.05, 0.05, 10, 2);\n"
    "SELECT quant.main.bond_yield(100, 100, 0.05, 10, 2);\n"
    "SELECT quant.main.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360');\n"
    "SELECT quant.main.discount_factor(0.05, 1);\n"
    "SELECT * FROM quant.main.day_count_conventions() ORDER BY name;"
)

_QUANT_CATALOG = Catalog(
    name="quant",
    default_schema="main",
    comment="Option pricing + Greeks, bond pricing/yield, and day-count math for SQL (QuantLib)",
    tags={
        "vgi.title": "Quantitative Finance Math",
        "vgi.keywords": json.dumps(
            [
                "quant",
                "quantitative finance",
                "options",
                "black-scholes",
                "greeks",
                "implied volatility",
                "bonds",
                "yield",
                "duration",
                "convexity",
                "day count",
                "discounting",
                "present value",
                "quantlib",
            ]
        ),
        "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
        "vgi.author": "Query.Farm",
        "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-quant/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-quant/blob/main/README.md",
    },
    source_url="https://github.com/Query-farm/vgi-quant",
    schemas=[
        Schema(
            name="main",
            comment="Option/Greeks, bond, and day-count functions: the quant catalog's single schema",
            tags={
                "vgi.title": "Quant — main",
                "vgi.keywords": json.dumps(
                    [
                        "quant",
                        "options",
                        "greeks",
                        "black-scholes",
                        "implied volatility",
                        "bonds",
                        "yield",
                        "duration",
                        "convexity",
                        "year fraction",
                        "discount factor",
                        "present value",
                    ]
                ),
                # VGI123 classifying tags use BARE keys (NOT vgi.-namespaced).
                "domain": "finance",
                "category": "quantitative-finance",
                "topic": "option-and-bond-pricing",
                "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
                "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
            },
            functions=list(_FUNCTIONS),
            # VGI311: expose the parameterless table function as a regular table
            # too (defined alongside the function in vgi_quant.tables).
            tables=list(TABLES),
        ),
    ],
)


class QuantWorker(Worker):
    """Worker process hosting the ``quant`` catalog."""

    catalog = _QUANT_CATALOG


def main() -> None:
    """Run the quant worker process (stdio or, via flags, HTTP)."""
    QuantWorker.main()


if __name__ == "__main__":
    main()
