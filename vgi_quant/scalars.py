"""Per-row scalar quant functions.

Every function here is a true DuckDB **scalar** -- one value (per row) in, one
value out -- so it can be used inline in any projection or predicate:

    SELECT bs_price(spot, strike, 0.05, vol, ttm, 'call')  FROM options;
    SELECT id, bond_price(100, 0.05, ytm, 10, 2)           FROM bonds;
    SELECT year_fraction(start, end, 'ACT/360')            FROM accruals;

A note on argument syntax
-------------------------
VGI / DuckDB *scalar* functions take **positional** arguments and resolve
overloads by *arity* (the ``name := value`` named-argument syntax is a property
of table functions and macros, not scalars). The option functions take a
trailing constant ``opt_type`` ('call'|'put') and the bond functions a trailing
constant ``freq`` (1/2/4/12); these are constant ``ConstParam`` arguments, not
per-row columns. ``year_fraction`` takes a trailing constant ``convention``.

NULL semantics: any NULL input cell yields a NULL output cell (the row is
skipped). Invalid (non-NULL) inputs -- ``ttm <= 0``, negative volatility,
``years <= 0``, an unknown ``opt_type`` / ``convention`` / ``freq``, or an
un-invertible price for ``implied_vol`` -- raise, surfacing a clear DuckDB
error. See :mod:`vgi_quant.quant` for the full convention + sign documentation.

The ``day_count_conventions`` discovery function is a *table function* and lives
in :mod:`vgi_quant.tables`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Annotated

import pyarrow as pa
from vgi.arguments import ConstParam, Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import quant

_F64 = pa.float64()


# ---------------------------------------------------------------------------
# Row-wise mapping helpers. Each zips N float64 input columns, passes NULL rows
# straight through to NULL, and applies a pure ``quant`` callable to the rest.
# A ``ValueError`` from the pure layer propagates out to a clear DuckDB error.
# ---------------------------------------------------------------------------


def _map_floats(
    columns: Sequence[pa.Array],
    fn: Callable[..., float],
) -> pa.DoubleArray:
    pylists = [c.to_pylist() for c in columns]
    out: list[float | None] = []
    for row in zip(*pylists, strict=True):
        if any(v is None for v in row):
            out.append(None)
        else:
            out.append(fn(*row))
    return pa.array(out, type=_F64)


def _map_dates(
    start: pa.Date32Array,
    end: pa.Date32Array,
    fn: Callable[[date, date], float],
) -> pa.DoubleArray:
    out: list[float | None] = []
    for s, e in zip(start.to_pylist(), end.to_pylist(), strict=True):
        out.append(None if s is None or e is None else fn(s, e))
    return pa.array(out, type=_F64)


# ===========================================================================
# Options -- Black-Scholes analytic. Signature: (spot, strike, rate, vol, ttm)
# plus a trailing constant opt_type ('call'|'put').
# ===========================================================================

_SPOT = Param(_F64, doc="Underlying spot price (> 0).")
_STRIKE = Param(_F64, doc="Option strike price (> 0).")
_RATE = Param(_F64, doc="Continuously-compounded annualized risk-free rate.")
_VOL = Param(_F64, doc="Annualized volatility (>= 0), e.g. 0.2 for 20%.")
_TTM = Param(_F64, doc="Time to maturity in years (> 0).")
_OPT_TYPE = ConstParam("Option type: 'call' or 'put'.")


def _make_option_scalar(fname: str, summary: str, example_extra: str) -> type[ScalarFunction]:
    """Build a 6-arg option scalar class for one of the BS price/Greek funcs."""
    compute_fn = quant.GREEKS[fname]

    class _OptionScalar(ScalarFunction):
        class Meta:
            name = fname
            description = summary
            categories = ["quant", "options"]
            examples = [
                FunctionExample(
                    sql=f"SELECT quant.{fname}(100, 100, 0.05, 0.2, 1, 'call')",
                    description=example_extra,
                ),
            ]

        @classmethod
        def compute(
            cls,
            spot: Annotated[pa.DoubleArray, _SPOT],
            strike: Annotated[pa.DoubleArray, _STRIKE],
            rate: Annotated[pa.DoubleArray, _RATE],
            vol: Annotated[pa.DoubleArray, _VOL],
            ttm: Annotated[pa.DoubleArray, _TTM],
            opt_type: Annotated[str, _OPT_TYPE],
        ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
            return _map_floats(
                [spot, strike, rate, vol, ttm],
                lambda s, k, r, v, t: compute_fn(s, k, r, v, t, opt_type),
            )

    _OptionScalar.__name__ = _camel(fname) + "Function"
    _OptionScalar.__qualname__ = _OptionScalar.__name__
    return _OptionScalar


def _camel(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_"))


BsPriceFunction = _make_option_scalar(
    "bs_price",
    "Black-Scholes price of a European option ('call'|'put')",
    "Standard at-the-money BS call price",
)
BsDeltaFunction = _make_option_scalar(
    "bs_delta", "Black-Scholes delta d(value)/d(spot) of a European option", "Delta of an ATM call"
)
BsGammaFunction = _make_option_scalar(
    "bs_gamma", "Black-Scholes gamma d2(value)/d(spot)2 of a European option", "Gamma of an ATM call"
)
BsVegaFunction = _make_option_scalar(
    "bs_vega",
    "Black-Scholes vega d(value)/d(vol), per 1.00 of volatility",
    "Vega of an ATM call (per 1.00 vol)",
)
BsThetaFunction = _make_option_scalar(
    "bs_theta", "Black-Scholes theta d(value)/d(t), per year", "Theta of an ATM call (per year)"
)
BsRhoFunction = _make_option_scalar(
    "bs_rho", "Black-Scholes rho d(value)/d(rate), per 1.00 of the rate", "Rho of an ATM call (per 1.00 rate)"
)


class ImpliedVolFunction(ScalarFunction):
    """``implied_vol(price, spot, strike, rate, ttm, opt_type)`` -- BS implied vol."""

    class Meta:
        name = "implied_vol"
        description = (
            "Black-Scholes implied volatility reproducing an option price (raises if not invertible)"
        )
        categories = ["quant", "options"]
        examples = [
            FunctionExample(
                sql="SELECT quant.implied_vol(10.45, 100, 100, 0.05, 1, 'call')",
                description="Recover ~0.20 vol from a BS call price",
            ),
        ]

    @classmethod
    def compute(
        cls,
        price: Annotated[pa.DoubleArray, Param(_F64, doc="Observed option price (>= 0).")],
        spot: Annotated[pa.DoubleArray, _SPOT],
        strike: Annotated[pa.DoubleArray, _STRIKE],
        rate: Annotated[pa.DoubleArray, _RATE],
        ttm: Annotated[pa.DoubleArray, _TTM],
        opt_type: Annotated[str, _OPT_TYPE],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats(
            [price, spot, strike, rate, ttm],
            lambda p, s, k, r, t: quant.implied_vol(p, s, k, r, t, opt_type),
        )


# ===========================================================================
# Bonds -- fixed-rate. Trailing constant freq (1=annual, 2=semi, 4=qtr, 12=mo).
# ===========================================================================

_FACE = Param(_F64, doc="Face (par) value of the bond (> 0).")
_COUPON = Param(_F64, doc="Annual coupon rate, e.g. 0.05 for 5%.")
_YIELD = Param(_F64, doc="Annual yield to maturity, e.g. 0.05 for 5%.")
_YEARS = Param(_F64, doc="Whole years to maturity (> 0).")
_FREQ = ConstParam("Coupon frequency per year: 1, 2, 4, or 12.", arrow_type=int)


class BondPriceFunction(ScalarFunction):
    """``bond_price(face, coupon_rate, yield_rate, years, freq)`` -- clean price."""

    class Meta:
        name = "bond_price"
        description = "Clean price of a fixed-rate bond at a given yield (par bond prices to face)"
        categories = ["quant", "bonds"]
        examples = [
            FunctionExample(
                sql="SELECT quant.bond_price(100, 0.05, 0.05, 10, 2)",
                description="A par bond (coupon == yield) prices to 100",
            ),
        ]

    @classmethod
    def compute(
        cls,
        face: Annotated[pa.DoubleArray, _FACE],
        coupon_rate: Annotated[pa.DoubleArray, _COUPON],
        yield_rate: Annotated[pa.DoubleArray, _YIELD],
        years: Annotated[pa.DoubleArray, _YEARS],
        freq: Annotated[int, _FREQ],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats(
            [face, coupon_rate, yield_rate, years],
            lambda f, c, y, yr: quant.bond_price(f, c, y, int(yr), freq),
        )


class BondYieldFunction(ScalarFunction):
    """``bond_yield(price, face, coupon_rate, years, freq)`` -- yield to maturity."""

    class Meta:
        name = "bond_yield"
        description = "Yield to maturity implied by a clean bond price (inverse of bond_price)"
        categories = ["quant", "bonds"]
        examples = [
            FunctionExample(
                sql="SELECT quant.bond_yield(100, 100, 0.05, 10, 2)",
                description="A par-priced 5% bond yields ~0.05",
            ),
        ]

    @classmethod
    def compute(
        cls,
        price: Annotated[pa.DoubleArray, Param(_F64, doc="Observed clean price (> 0).")],
        face: Annotated[pa.DoubleArray, _FACE],
        coupon_rate: Annotated[pa.DoubleArray, _COUPON],
        years: Annotated[pa.DoubleArray, _YEARS],
        freq: Annotated[int, _FREQ],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats(
            [price, face, coupon_rate, years],
            lambda p, f, c, yr: quant.bond_yield(p, f, c, int(yr), freq),
        )


class BondDurationFunction(ScalarFunction):
    """``bond_duration(face, coupon_rate, yield_rate, years, freq)`` -- modified duration."""

    class Meta:
        name = "bond_duration"
        description = "Modified duration of a fixed-rate bond at a given yield"
        categories = ["quant", "bonds"]
        examples = [
            FunctionExample(
                sql="SELECT quant.bond_duration(100, 0.05, 0.05, 10, 2)",
                description="Modified duration of a 10y par bond",
            ),
        ]

    @classmethod
    def compute(
        cls,
        face: Annotated[pa.DoubleArray, _FACE],
        coupon_rate: Annotated[pa.DoubleArray, _COUPON],
        yield_rate: Annotated[pa.DoubleArray, _YIELD],
        years: Annotated[pa.DoubleArray, _YEARS],
        freq: Annotated[int, _FREQ],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats(
            [face, coupon_rate, yield_rate, years],
            lambda f, c, y, yr: quant.bond_duration(f, c, y, int(yr), freq),
        )


class BondConvexityFunction(ScalarFunction):
    """``bond_convexity(face, coupon_rate, yield_rate, years, freq)`` -- convexity."""

    class Meta:
        name = "bond_convexity"
        description = "Convexity of a fixed-rate bond at a given yield"
        categories = ["quant", "bonds"]
        examples = [
            FunctionExample(
                sql="SELECT quant.bond_convexity(100, 0.05, 0.05, 10, 2)",
                description="Convexity of a 10y par bond",
            ),
        ]

    @classmethod
    def compute(
        cls,
        face: Annotated[pa.DoubleArray, _FACE],
        coupon_rate: Annotated[pa.DoubleArray, _COUPON],
        yield_rate: Annotated[pa.DoubleArray, _YIELD],
        years: Annotated[pa.DoubleArray, _YEARS],
        freq: Annotated[int, _FREQ],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats(
            [face, coupon_rate, yield_rate, years],
            lambda f, c, y, yr: quant.bond_convexity(f, c, y, int(yr), freq),
        )


# ===========================================================================
# Conventions -- day-count year fraction + discounting.
# ===========================================================================


class YearFractionFunction(ScalarFunction):
    """``year_fraction(start, end, convention)`` -- day-count year fraction."""

    class Meta:
        name = "year_fraction"
        description = (
            "Year fraction between two dates under a day-count convention "
            "('ACT/360', 'ACT/365', '30/360', 'ACT/ACT'). Unknown convention raises."
        )
        categories = ["quant", "conventions"]
        examples = [
            FunctionExample(
                sql="SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360')",
                description="Half-ish year under ACT/360 (181/360)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        start: Annotated[pa.Date32Array, Param(doc="Start date.")],
        end: Annotated[pa.Date32Array, Param(doc="End date.")],
        convention: Annotated[str, ConstParam("Day-count convention string; see day_count_conventions().")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_dates(start, end, lambda s, e: quant.year_fraction(s, e, convention))


class DiscountFactorFunction(ScalarFunction):
    """``discount_factor(rate, ttm)`` -- continuously-compounded discount factor."""

    class Meta:
        name = "discount_factor"
        description = "Continuously-compounded discount factor exp(-rate * ttm)"
        categories = ["quant", "conventions"]
        examples = [
            FunctionExample(
                sql="SELECT quant.discount_factor(0.05, 1)",
                description="One-year discount factor at 5%",
            ),
        ]

    @classmethod
    def compute(
        cls,
        rate: Annotated[pa.DoubleArray, _RATE],
        ttm: Annotated[pa.DoubleArray, Param(_F64, doc="Time horizon in years.")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats([rate, ttm], quant.discount_factor)


class PresentValueFunction(ScalarFunction):
    """``present_value(amount, rate, ttm)`` -- continuously-discounted present value."""

    class Meta:
        name = "present_value"
        description = "Present value amount * exp(-rate * ttm) (continuous compounding)"
        categories = ["quant", "conventions"]
        examples = [
            FunctionExample(
                sql="SELECT quant.present_value(100, 0.05, 1)",
                description="Present value of 100 due in one year at 5%",
            ),
        ]

    @classmethod
    def compute(
        cls,
        amount: Annotated[pa.DoubleArray, Param(_F64, doc="Future cash amount.")],
        rate: Annotated[pa.DoubleArray, _RATE],
        ttm: Annotated[pa.DoubleArray, Param(_F64, doc="Time horizon in years.")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        return _map_floats([amount, rate, ttm], quant.present_value)


SCALAR_FUNCTIONS: list[type] = [
    # options
    BsPriceFunction,
    BsDeltaFunction,
    BsGammaFunction,
    BsVegaFunction,
    BsThetaFunction,
    BsRhoFunction,
    ImpliedVolFunction,
    # bonds
    BondPriceFunction,
    BondYieldFunction,
    BondDurationFunction,
    BondConvexityFunction,
    # conventions
    YearFractionFunction,
    DiscountFactorFunction,
    PresentValueFunction,
]
