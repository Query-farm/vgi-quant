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
    "data in DuckDB and want option pricing, implied volatility, bond analytics, and rate-risk math "
    "to live right next to the data. Because the calculations are exposed as scalar functions, you "
    "can value a whole portfolio in a single `SELECT`, filter on a computed risk measure in a "
    "`WHERE` clause, or join model output back onto your positions — all with the speed of DuckDB's "
    "vectorized engine over Apache Arrow.\n\n"
    "## Key concepts\n\n"
    "- **Per-row vs. constant arguments.** Market inputs (spot, strike, rate, volatility, price, "
    "coupon, yield, dates) are per-row columns, while the option kind, the bond coupon frequency, "
    "and the day-count convention are constant (literal) arguments fixed at planning time. That "
    "split lets you value an entire table of positions in one pass.\n"
    "- **Analytic and deterministic.** Option values use the closed-form Black-Scholes model (no "
    "dividend yield — carry equals the risk-free rate); bond analytics use a fixed-rate bond priced "
    "on a pinned evaluation date. Results are reproducible run to run.\n"
    "- **NULL vs. error.** Any NULL input yields a NULL result, but a genuinely invalid non-NULL "
    "input (a non-positive time to maturity, a negative volatility, an unknown convention) raises a "
    "clear error rather than silently returning a wrong number.\n\n"
    "## When to reach for it\n\n"
    "Use `quant` whenever you need theoretical option premia and their risk sensitivities, want to "
    "convert between bond prices and yields or measure interest-rate risk, or need consistent "
    "day-count and present-value math alongside your data — without exporting to a separate "
    "analytics stack. Because every calculation is a deterministic, closed-form function, results "
    "are reproducible and cheap enough to run across a whole portfolio in a single query.\n\n"
    "## Backed by QuantLib\n\n"
    "Under the hood the math is backed by [QuantLib](https://www.quantlib.org/), the widely used "
    "open-source library for quantitative finance, which provides the analytic option pricing, the "
    "fixed-rate bond pricing and yield solvers, and the day-count conventions this worker exposes. "
    "See the QuantLib [source code on GitHub](https://github.com/lballabio/QuantLib), the "
    "[official documentation](https://www.quantlib.org/docs.shtml), and the "
    "[Python bindings reference](https://quantlib-python-docs.readthedocs.io/) for the underlying "
    "models and conventions."
)

_SCHEMA_DESCRIPTION_LLM = (
    "Option pricing + Greeks (Black-Scholes), implied volatility, fixed-rate bond pricing / yield / "
    "modified duration / convexity, day-count year fractions, and continuous discounting / present "
    "value functions."
)

_SCHEMA_DESCRIPTION_MD = (
    "# Quant — the `main` schema\n\n"
    "The single schema of the `quant` catalog. It groups every quantitative-finance "
    "calculation the worker exposes over Apache Arrow into one namespace.\n\n"
    "## What lives here\n\n"
    "Three families of functionality:\n\n"
    "- **Options** — closed-form Black-Scholes pricing and the full set of first- and "
    "second-order Greeks, plus inversion of a market price back to implied volatility.\n"
    "- **Fixed-rate bonds** — clean pricing from a yield, the inverse yield-to-maturity "
    "solve, and interest-rate risk measures (modified duration and convexity).\n"
    "- **Day-count & discounting** — year fractions under the common day-count "
    "conventions and continuously-compounded discount factors and present values, "
    "with a discovery listing of the accepted convention strings.\n\n"
    "## When to use it\n\n"
    "Use this schema for option pricing and risk sensitivities, bond price/yield "
    "conversion and rate-risk analytics, and day-count or present-value math directly "
    "in SQL. Every object is a deterministic scalar (or the one discovery table), so the "
    "math composes inline in projections, `WHERE` filters, and joins over your positions."
)

# VGI515: schema-level examples must each carry a non-empty description, so this
# is a JSON list of {"description", "sql"} objects (not a bare SQL string).
_SCHEMA_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "Black-Scholes fair value of an at-the-money 1-year European call.",
            "sql": "SELECT quant.main.bs_price(100, 100, 0.05, 0.2, 1, 'call') AS call_price",
        },
        {
            "description": "Delta (hedge ratio) of that same at-the-money call.",
            "sql": "SELECT quant.main.bs_delta(100, 100, 0.05, 0.2, 1, 'call') AS delta",
        },
        {
            "description": "Recover the implied volatility (~0.20) from a quoted call price.",
            "sql": "SELECT quant.main.implied_vol(10.45, 100, 100, 0.05, 1, 'call') AS iv",
        },
        {
            "description": "Clean price of a 10-year 5% semiannual par bond (prices to 100).",
            "sql": "SELECT quant.main.bond_price(100, 0.05, 0.05, 10, 2) AS clean_price",
        },
        {
            "description": "Invert a par price back to the bond's yield to maturity (~0.05).",
            "sql": "SELECT quant.main.bond_yield(100, 100, 0.05, 10, 2) AS ytm",
        },
        {
            "description": "Day-count year fraction of a half-year span under ACT/360 (181/360).",
            "sql": "SELECT quant.main.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360') AS yf",
        },
        {
            "description": "One-year continuously-compounded discount factor at 5% (~0.9512).",
            "sql": "SELECT quant.main.discount_factor(0.05, 1) AS df",
        },
        {
            "description": "List the supported day-count convention names, alphabetically.",
            "sql": "SELECT name FROM quant.main.day_count_conventions() ORDER BY name",
        },
    ]
)

# VGI413/VGI409/VGI410: the schema's category registry. Every function/table
# carries a `vgi.category` (via `object_tags`) naming one of these; the three
# names mirror the worker's natural groupings (options / bonds / conventions).
_SCHEMA_CATEGORIES = json.dumps(
    [
        {
            "name": "options",
            "description": (
                "Black-Scholes European option pricing, the option Greeks "
                "(delta, gamma, vega, theta, rho), and implied volatility."
            ),
        },
        {
            "name": "bonds",
            "description": (
                "Fixed-rate bond pricing, yield to maturity, and interest-rate "
                "risk measures (modified duration and convexity)."
            ),
        },
        {
            "name": "conventions",
            "description": ("Day-count year fractions and continuously-compounded discounting and present-value math."),
        },
    ]
)

# VGI152/VGI920: the fixed analyst-task suite `vgi-lint simulate` grades the
# worker against. Each task is unambiguous and its `reference_sql` is the
# canonical single-function solution; grading ignores output column names
# (the analyst picks its own alias) but is strict on values (QuantLib results
# are deterministic, so the analyst calling the same function matches exactly).
_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "atm_call_price",
            "prompt": (
                "Price a 1-year at-the-money European call option using the quant worker: "
                "spot price 100, strike 100, continuously-compounded risk-free rate 0.05, "
                "annualized volatility 0.20. Return the option price rounded to 4 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_price(100, 100, 0.05, 0.2, 1, 'call'), 4) AS price",
            "success_criteria": "Returns the Black-Scholes call price, approximately 10.4506.",
            "ignore_column_names": True,
        },
        {
            "name": "call_delta",
            "prompt": (
                "What is the Black-Scholes delta of a 1-year at-the-money European call "
                "(spot 100, strike 100, rate 0.05, volatility 0.20)? Round to 4 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_delta(100, 100, 0.05, 0.2, 1, 'call'), 4) AS delta",
            "success_criteria": "Returns the call delta, approximately 0.6368.",
            "ignore_column_names": True,
        },
        {
            "name": "atm_call_gamma",
            "prompt": (
                "What is the Black-Scholes gamma of a 1-year at-the-money European call "
                "(spot 100, strike 100, rate 0.05, volatility 0.20)? Round to 4 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_gamma(100, 100, 0.05, 0.2, 1, 'call'), 4) AS gamma",
            "success_criteria": "Returns the call gamma, approximately 0.0188.",
            "ignore_column_names": True,
        },
        {
            "name": "atm_call_vega",
            "prompt": (
                "What is the Black-Scholes vega (per 1.00 of volatility) of a 1-year "
                "at-the-money European call (spot 100, strike 100, rate 0.05, volatility 0.20)? "
                "Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_vega(100, 100, 0.05, 0.2, 1, 'call'), 2) AS vega",
            "success_criteria": "Returns the call vega per 1.00 vol, approximately 37.52.",
            "ignore_column_names": True,
        },
        {
            "name": "atm_call_theta",
            "prompt": (
                "What is the Black-Scholes theta (per year) of a 1-year at-the-money European "
                "call (spot 100, strike 100, rate 0.05, volatility 0.20)? Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_theta(100, 100, 0.05, 0.2, 1, 'call'), 2) AS theta",
            "success_criteria": "Returns the call theta per year, a negative value near -6.41.",
            "ignore_column_names": True,
        },
        {
            "name": "atm_call_rho",
            "prompt": (
                "What is the Black-Scholes rho (per 1.00 of the rate) of a 1-year at-the-money "
                "European call (spot 100, strike 100, rate 0.05, volatility 0.20)? Round to 2 "
                "decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bs_rho(100, 100, 0.05, 0.2, 1, 'call'), 2) AS rho",
            "success_criteria": "Returns the call rho per 1.00 rate, approximately 53.23.",
            "ignore_column_names": True,
        },
        {
            "name": "implied_vol_from_price",
            "prompt": (
                "A European call option with spot 100, strike 100, risk-free rate 0.05, and "
                "1 year to maturity trades at a price of 10.4506. What annualized implied "
                "volatility does that price imply? Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.implied_vol(10.4506, 100, 100, 0.05, 1, 'call'), 2) AS iv",
            "success_criteria": "Recovers an implied volatility of about 0.20.",
            "ignore_column_names": True,
        },
        {
            "name": "par_bond_price",
            "prompt": (
                "Compute the clean price of a fixed-rate bond with face value 100, a 5% annual "
                "coupon paid semiannually, a 5% yield to maturity, and 10 years to maturity. "
                "Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bond_price(100, 0.05, 0.05, 10, 2), 2) AS clean_price",
            "success_criteria": "Returns the clean price of a par bond, 100.00.",
            "ignore_column_names": True,
        },
        {
            "name": "par_bond_yield",
            "prompt": (
                "A fixed-rate bond with face value 100, a 5% annual coupon paid semiannually, "
                "and 10 years to maturity is quoted at a clean price of 100. What is its yield "
                "to maturity? Round to 4 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bond_yield(100, 100, 0.05, 10, 2), 4) AS ytm",
            "success_criteria": "Returns the yield to maturity of a par bond, about 0.05.",
            "ignore_column_names": True,
        },
        {
            "name": "bond_modified_duration",
            "prompt": (
                "Compute the modified duration of a fixed-rate bond with face value 100, a 5% "
                "annual coupon paid semiannually, a 5% yield to maturity, and 10 years to "
                "maturity. Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bond_duration(100, 0.05, 0.05, 10, 2), 2) AS modified_duration",
            "success_criteria": "Returns the modified duration in years, roughly 7.8.",
            "ignore_column_names": True,
        },
        {
            "name": "bond_convexity",
            "prompt": (
                "Compute the convexity of a fixed-rate bond with face value 100, a 5% annual "
                "coupon paid semiannually, a 5% yield to maturity, and 10 years to maturity. "
                "Round to 2 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.bond_convexity(100, 0.05, 0.05, 10, 2), 2) AS convexity",
            "success_criteria": "Returns the bond convexity, approximately 73.65.",
            "ignore_column_names": True,
        },
        {
            "name": "act360_year_fraction",
            "prompt": (
                "What is the ACT/360 day-count year fraction between 2026-01-01 and "
                "2026-07-01? Round to 4 decimal places."
            ),
            "reference_sql": (
                "SELECT ROUND(quant.main.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360'), 4) AS yf"
            ),
            "success_criteria": "Returns 181/360, approximately 0.5028.",
            "ignore_column_names": True,
        },
        {
            "name": "discount_factor_2y",
            "prompt": (
                "Compute the continuously-compounded discount factor for a rate of 0.05 over "
                "2 years. Round to 6 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.discount_factor(0.05, 2), 6) AS df",
            "success_criteria": "Returns exp(-0.10), approximately 0.904837.",
            "ignore_column_names": True,
        },
        {
            "name": "present_value_2y",
            "prompt": (
                "What is the present value today of 1000 units of currency received in 2 years, "
                "discounted continuously at an annual rate of 0.05? Round to 4 decimal places."
            ),
            "reference_sql": "SELECT ROUND(quant.main.present_value(1000, 0.05, 2), 4) AS pv",
            "success_criteria": "Returns 1000 * exp(-0.10), approximately 904.8374.",
            "ignore_column_names": True,
        },
        {
            "name": "list_day_count_conventions",
            "prompt": "List every day-count convention string this worker supports.",
            "reference_sql": "SELECT name FROM quant.main.day_count_conventions() ORDER BY name",
            "success_criteria": "Lists the supported day-count conventions (ACT/360, ACT/365, 30/360, ACT/ACT).",
            "ignore_column_names": True,
            "unordered": True,
        },
    ]
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
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
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
                "vgi.categories": _SCHEMA_CATEGORIES,
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
