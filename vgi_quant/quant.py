"""Pure quantitative-finance compute over QuantLib.

This module is the single home for all numerical work -- option pricing and
Greeks (Black-Scholes analytic), fixed-rate bond pricing / yield / risk, and
day-count year fractions. It has **no** Arrow or VGI dependency, so every
function here is a plain ``float``-in / ``float``-out (or ``str``) callable and
is directly unit-testable.

QuantLib is an expensive import; it is imported **once** at module load and the
day-count factory table is built once and cached for the process lifetime.

Conventions and sign choices (documented + tested)
---------------------------------------------------
Options use the analytic Black-Scholes formula via ``ql.BlackCalculator`` with
forward ``F = spot * exp(rate * ttm)`` and discount ``exp(-rate * ttm)``; there
is no dividend yield (carry == rate). The Greeks follow QuantLib's conventions:

- ``bs_delta``  -- d(value)/d(spot).
- ``bs_gamma``  -- d2(value)/d(spot)2.
- ``bs_vega``   -- d(value)/d(vol), per **1.00** (100 percentage points) of
  volatility. Divide by 100 for the "per 1% vol" desk convention.
- ``bs_theta``  -- d(value)/d(t), per **year** (calendar). ``thetaPerDay`` is
  this divided by 365; we expose the per-year value.
- ``bs_rho``    -- d(value)/d(rate), per **1.00** (100 percentage points) of
  the rate.

Bonds are par-coupon ``FixedRateBond`` instruments priced from the evaluation
date with an ``ActualActual(ISDA)`` day count and ``Compounded`` yields at the
coupon frequency. ``bond_price`` / ``bond_yield`` use the **clean** price.
``bond_duration`` is **modified** duration; ``bond_convexity`` is QuantLib's
``BondFunctions.convexity``.

Invalid-input policy (see each function's docstring):

- ``ttm <= 0``, ``vol < 0``, ``years <= 0`` -> ``ValueError``.
- Unknown ``opt_type`` / day-count ``convention`` / bond ``freq`` ->
  ``ValueError``.
- An out-of-range price for ``implied_vol`` (below intrinsic / above the bound)
  -> ``ValueError`` (QuantLib raises; we surface it as ``ValueError``).

The scalar adapters in :mod:`vgi_quant.scalars` translate ``ValueError`` into a
clear DuckDB error and pass NULL inputs straight through to NULL outputs.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

import QuantLib as ql

# ---------------------------------------------------------------------------
# Process-wide evaluation date. Pure relative-time math (ttm in years) does not
# depend on it for options, but bonds build a schedule from "today", so we pin a
# stable, deterministic evaluation date for the process lifetime.
# ---------------------------------------------------------------------------

_EVAL_DATE = ql.Date(15, 6, 2026)
ql.Settings.instance().evaluationDate = _EVAL_DATE
_NULL_CALENDAR = ql.NullCalendar()


# ===========================================================================
# Options -- Black-Scholes analytic (BlackCalculator, exact ttm control).
# ===========================================================================


def _option_type(opt_type: str) -> int:
    key = opt_type.strip().lower()
    if key == "call":
        return int(ql.Option.Call)
    if key == "put":
        return int(ql.Option.Put)
    raise ValueError(f"unknown option type {opt_type!r}; expected 'call' or 'put'")


def _calculator(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> Any:
    """Build a configured ``ql.BlackCalculator`` or raise ``ValueError``."""
    if ttm <= 0:
        raise ValueError(f"ttm must be > 0, got {ttm}")
    if vol < 0:
        raise ValueError(f"vol must be >= 0, got {vol}")
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    payoff = ql.PlainVanillaPayoff(_option_type(opt_type), strike)
    forward = spot * math.exp(rate * ttm)
    discount = math.exp(-rate * ttm)
    std_dev = vol * math.sqrt(ttm)
    return ql.BlackCalculator(payoff, forward, std_dev, discount)


def bs_price(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """Black-Scholes price of a European option (``opt_type`` 'call'|'put')."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).value())


def bs_delta(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """d(value)/d(spot) of a European option."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).delta(spot))


def bs_gamma(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """d2(value)/d(spot)2 of a European option."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).gamma(spot))


def bs_vega(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """d(value)/d(vol), per 1.00 (100 pct points) of volatility."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).vega(ttm))


def bs_theta(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """d(value)/d(t), per year (calendar)."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).theta(spot, ttm))


def bs_rho(spot: float, strike: float, rate: float, vol: float, ttm: float, opt_type: str) -> float:
    """d(value)/d(rate), per 1.00 (100 pct points) of the rate."""
    return float(_calculator(spot, strike, rate, vol, ttm, opt_type).rho(ttm))


def implied_vol(price: float, spot: float, strike: float, rate: float, ttm: float, opt_type: str) -> float:
    """Black-Scholes implied volatility that reproduces ``price``.

    Raises ``ValueError`` if ``ttm <= 0``, on an unknown ``opt_type``, or if the
    price is outside the no-arbitrage bounds (below intrinsic / non-invertible).
    """
    if ttm <= 0:
        raise ValueError(f"ttm must be > 0, got {ttm}")
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price}")
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    opt = _option_type(opt_type)
    forward = spot * math.exp(rate * ttm)
    discount = math.exp(-rate * ttm)
    try:
        std_dev = ql.blackFormulaImpliedStdDev(opt, strike, forward, price, discount)
    except RuntimeError as exc:  # QuantLib raises on out-of-range / non-invertible prices.
        raise ValueError(f"cannot invert implied vol from price {price}: {exc}") from exc
    return float(std_dev) / math.sqrt(ttm)


# ===========================================================================
# Bonds -- fixed-rate, priced from the evaluation date.
# ===========================================================================

_FREQUENCIES: dict[int, int] = {
    1: ql.Annual,
    2: ql.Semiannual,
    4: ql.Quarterly,
    12: ql.Monthly,
}

_BOND_DC = ql.ActualActual(ql.ActualActual.ISDA)


def _frequency(freq: int) -> int:
    if freq not in _FREQUENCIES:
        raise ValueError(f"unknown coupon frequency {freq!r}; expected one of {sorted(_FREQUENCIES)}")
    return _FREQUENCIES[freq]


def _build_bond(face: float, coupon_rate: float, years: int, freq: int) -> ql.FixedRateBond:
    if years <= 0:
        raise ValueError(f"years must be > 0, got {years}")
    if face <= 0:
        raise ValueError(f"face must be > 0, got {face}")
    freq_enum = _frequency(freq)
    maturity = _EVAL_DATE + ql.Period(int(years), ql.Years)
    schedule = ql.Schedule(
        _EVAL_DATE,
        maturity,
        ql.Period(freq_enum),
        _NULL_CALENDAR,
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )
    return ql.FixedRateBond(0, face, schedule, [coupon_rate], _BOND_DC)


def bond_price(face: float, coupon_rate: float, yield_rate: float, years: int, freq: int) -> float:
    """Clean price of a fixed-rate bond at a given yield.

    A par bond (``coupon_rate == yield_rate``) prices to ``face``.
    """
    bond = _build_bond(face, coupon_rate, years, freq)
    rate = ql.InterestRate(yield_rate, _BOND_DC, ql.Compounded, _frequency(freq))
    return float(ql.BondFunctions.cleanPrice(bond, rate))


def bond_yield(price: float, face: float, coupon_rate: float, years: int, freq: int) -> float:
    """Yield to maturity implied by a clean ``price`` (inverse of ``bond_price``)."""
    if price <= 0:
        raise ValueError(f"price must be > 0, got {price}")
    bond = _build_bond(face, coupon_rate, years, freq)
    bond_price_obj = ql.BondPrice(price, ql.BondPrice.Clean)
    return float(ql.BondFunctions.bondYield(bond, bond_price_obj, _BOND_DC, ql.Compounded, _frequency(freq)))


def bond_duration(face: float, coupon_rate: float, yield_rate: float, years: int, freq: int) -> float:
    """Modified duration of a fixed-rate bond at a given yield."""
    bond = _build_bond(face, coupon_rate, years, freq)
    rate = ql.InterestRate(yield_rate, _BOND_DC, ql.Compounded, _frequency(freq))
    return float(ql.BondFunctions.duration(bond, rate, ql.Duration.Modified))


def bond_convexity(face: float, coupon_rate: float, yield_rate: float, years: int, freq: int) -> float:
    """Convexity of a fixed-rate bond at a given yield."""
    bond = _build_bond(face, coupon_rate, years, freq)
    rate = ql.InterestRate(yield_rate, _BOND_DC, ql.Compounded, _frequency(freq))
    return float(ql.BondFunctions.convexity(bond, rate))


# ===========================================================================
# Conventions -- day-count year fractions and discounting.
# ===========================================================================


def _day_counters() -> dict[str, ql.DayCounter]:
    """Build the supported day-count factory table (called once, cached)."""
    return {
        "ACT/360": ql.Actual360(),
        "ACT/365": ql.Actual365Fixed(),
        "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
        "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
    }


_DAY_COUNTERS: dict[str, ql.DayCounter] = _day_counters()


def day_count_conventions() -> list[str]:
    """The day-count convention strings ``year_fraction`` accepts."""
    return list(_DAY_COUNTERS)


def _day_counter(convention: str) -> ql.DayCounter:
    key = convention.strip().upper()
    counter = _DAY_COUNTERS.get(key)
    if counter is None:
        raise ValueError(f"unknown day-count convention {convention!r}; expected one of {sorted(_DAY_COUNTERS)}")
    return counter


def _to_ql_date(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def year_fraction(start: date, end: date, convention: str) -> float:
    """Year fraction between two dates under a day-count ``convention``.

    Supported conventions: ``ACT/360``, ``ACT/365``, ``30/360``, ``ACT/ACT``.
    An unknown convention raises ``ValueError``.
    """
    counter = _day_counter(convention)
    return float(counter.yearFraction(_to_ql_date(start), _to_ql_date(end)))


def discount_factor(rate: float, ttm: float) -> float:
    """Continuously-compounded discount factor ``exp(-rate * ttm)``."""
    return math.exp(-rate * ttm)


def present_value(amount: float, rate: float, ttm: float) -> float:
    """Present value ``amount * exp(-rate * ttm)`` (continuous compounding)."""
    return amount * math.exp(-rate * ttm)


# Re-export the Greek functions keyed by name for the scalar adapters.
GREEKS: dict[str, Callable[[float, float, float, float, float, str], float]] = {
    "bs_price": bs_price,
    "bs_delta": bs_delta,
    "bs_gamma": bs_gamma,
    "bs_vega": bs_vega,
    "bs_theta": bs_theta,
    "bs_rho": bs_rho,
}
