"""Composed example queries: several quant functions combined in one query.

Each constant is a ``(description, sql)`` pair defined once here and referenced
from both the schema-level ``vgi.example_queries`` list (``worker.py``) and the
example list of the function that drives the query (``scalars.py``), so the SQL
is never copy-pasted. Every query is offline and deterministic; the expected
rows are pinned in ``test/sql/composed.test``.
"""

from __future__ import annotations

# implied_vol -> bs_delta: back out a vol per strike from quoted prices, then
# hedge each strike at its own implied vol (a volatility skew, not one flat vol).
# Rows: 90 -> iv 0.2531 / delta 0.7933, 100 -> 0.2478 / 0.5911, 110 -> 0.2378 / 0.3692.
IV_SKEW_TO_DELTA = (
    "Back out implied vol for three quoted 6-month calls, then compute each strike's delta "
    "at its own implied vol (implied_vol feeding bs_delta); the vol skews down as strike rises.",
    "WITH quotes(strike, price) AS (VALUES (90, 14.50), (100, 8.20), (110, 3.90)), "
    "smile AS (SELECT strike, quant.main.implied_vol(price, 100, strike, 0.05, 0.5, 'call') AS iv "
    "FROM quotes) "
    "SELECT strike, ROUND(iv, 4) AS iv, "
    "ROUND(quant.main.bs_delta(100, strike, 0.05, iv, 0.5, 'call'), 4) AS delta "
    "FROM smile ORDER BY strike",
)

# year_fraction -> bs_price / bs_delta, aggregated over a small call book.
# One row: book_value 69.4256, book_delta 6.4522.
CALL_BOOK_VALUE = (
    "Value a small call book dated 2026-06-15: each expiry date becomes an ACT/365 time to "
    "maturity via year_fraction, which feeds bs_price and bs_delta summed by position size.",
    "WITH book(qty, strike, expiry) AS (VALUES (10, 100, DATE '2026-09-18'), "
    "(-10, 110, DATE '2026-09-18'), (5, 100, DATE '2026-12-18')), "
    "priced AS (SELECT qty, strike, "
    "quant.main.year_fraction(DATE '2026-06-15', expiry, 'ACT/365') AS ttm FROM book) "
    "SELECT ROUND(SUM(qty * quant.main.bs_price(100, strike, 0.05, 0.2, ttm, 'call')), 4) AS book_value, "
    "ROUND(SUM(qty * quant.main.bs_delta(100, strike, 0.05, 0.2, ttm, 'call')), 4) AS book_delta "
    "FROM priced",
)

# bond_price + bond_duration + bond_convexity: +100bp shock, full reprice vs the
# second-order Taylor estimate. One row: -7.4396 / -7.7955 / -7.4273.
BOND_SHOCK_APPROX = (
    "Shock a 10-year 5% semiannual par bond up 100bp: the full bond_price reprice (-7.44) "
    "versus the duration-only (-7.80) and duration-plus-convexity (-7.43) estimates.",
    "WITH base AS (SELECT quant.main.bond_price(100, 0.05, 0.05, 10, 2) AS p0, "
    "quant.main.bond_duration(100, 0.05, 0.05, 10, 2) AS dur, "
    "quant.main.bond_convexity(100, 0.05, 0.05, 10, 2) AS cvx) "
    "SELECT ROUND(quant.main.bond_price(100, 0.05, 0.06, 10, 2) - p0, 4) AS actual_change, "
    "ROUND(-p0 * dur * 0.01, 4) AS duration_estimate, "
    "ROUND(p0 * (-dur * 0.01 + 0.5 * cvx * 0.0001), 4) AS duration_convexity_estimate "
    "FROM base",
)

# year_fraction -> present_value over a generated coupon schedule.
# One row: pv 100.8373.
COUPON_SCHEDULE_PV = (
    "Present value of a 2-year 5% semiannual coupon schedule settled 2026-06-15, discounting "
    "each cash flow at 4.5% continuous over its ACT/365 year_fraction (~100.84).",
    "SELECT ROUND(SUM(quant.main.present_value("
    "CASE WHEN n = 4 THEN 102.5 ELSE 2.5 END, 0.045, "
    "quant.main.year_fraction(DATE '2026-06-15', "
    "CAST(DATE '2026-06-15' + to_months(6 * n) AS DATE), 'ACT/365'))), 4) AS pv "
    "FROM range(1, 5) AS t(n)",
)

COMPOSED_EXAMPLES: list[tuple[str, str]] = [
    IV_SKEW_TO_DELTA,
    CALL_BOOK_VALUE,
    BOND_SHOCK_APPROX,
    COUPON_SCHEDULE_PV,
]
