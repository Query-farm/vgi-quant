"""Quantitative-finance math for DuckDB SQL, backed by QuantLib.

The implementation is split so each concern stays focused:

- ``quant``   -- pure, deterministic compute over QuantLib: option pricing +
  Greeks (Black-Scholes analytic), fixed-rate bond pricing / yield / duration /
  convexity, and day-count year fractions. No Arrow or VGI dependency, directly
  unit-testable. QuantLib is imported once at module load.
- ``scalars`` -- per-row VGI scalar functions (positional-only; optional
  trailing ``opt_type`` / ``convention`` / ``freq`` arguments are exposed as
  arity overloads).
- ``tables``  -- the ``day_count_conventions`` discovery table function.

``quant_worker.py`` at the repo root assembles these into the ``quant`` catalog
and runs the worker over stdio (or HTTP).
"""

from __future__ import annotations

__version__ = "0.1.0"
