# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.3",
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

_QUANT_CATALOG = Catalog(
    name="quant",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Option pricing + Greeks, bond pricing/yield, and day-count math for SQL (QuantLib)",
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
