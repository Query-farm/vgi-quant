# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.4",
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

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_quant.scalars import SCALAR_FUNCTIONS
from vgi_quant.tables import TABLE_FUNCTIONS

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
    "# quant\n\n"
    "Quantitative-finance math for DuckDB via VGI, backed by [QuantLib](https://www.quantlib.org/).\n\n"
    "**Option scalars (Black-Scholes analytic):** `bs_price`, `bs_delta`, `bs_gamma`, `bs_vega`, "
    "`bs_theta`, `bs_rho`, `implied_vol`.\n\n"
    "**Bond scalars (fixed-rate):** `bond_price`, `bond_yield`, `bond_duration`, `bond_convexity`.\n\n"
    "**Day-count / discounting scalars:** `year_fraction`, `discount_factor`, `present_value`.\n\n"
    "**Table function:** `day_count_conventions`.\n\n"
    "Option/bond inputs are per-row columns; `opt_type` ('call'|'put'), bond `freq` (1/2/4/12), and "
    "the day-count `convention` are constant (literal) arguments. See `quant.day_count_conventions()` "
    "for the supported convention strings."
)

_SCHEMA_DESCRIPTION_LLM = (
    "Option pricing + Greeks (Black-Scholes), implied volatility, fixed-rate bond pricing / yield / "
    "modified duration / convexity, day-count year fractions, and continuous discounting / present "
    "value functions."
)

_SCHEMA_DESCRIPTION_MD = "Option pricing + Greeks, bond pricing/yield/duration, and day-count math over Apache Arrow."

_QUANT_CATALOG = Catalog(
    name="quant",
    default_schema="main",
    comment="Option pricing + Greeks, bond pricing/yield, and day-count math for SQL (QuantLib)",
    tags={
        "vgi.description_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.description_md": _CATALOG_DESCRIPTION_MD,
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
                "vgi.description_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.description_md": _SCHEMA_DESCRIPTION_MD,
            },
            functions=list(_FUNCTIONS),
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
