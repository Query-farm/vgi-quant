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
from .meta import object_tags

_F64 = pa.float64()

# VGI509: a JSON string of guaranteed-runnable, catalog-qualified examples. Each
# `sql` is self-contained and re-runnable against an attached `quant` worker; we
# omit `expected_result` (the linter only requires clean execution, and pinning
# exact floating-point output is brittle). Attached to a representative object.
_YEAR_FRACTION_EXECUTABLE_EXAMPLES = (
    "["
    '{"description": "Black-Scholes price of an at-the-money 1y European call.",'
    ' "sql": "SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, \'call\') AS price"},'
    '{"description": "Recover implied volatility from a Black-Scholes call price.",'
    ' "sql": "SELECT quant.implied_vol(10.45, 100, 100, 0.05, 1, \'call\') AS iv"},'
    '{"description": "Clean price of a 10y semiannual par bond.",'
    ' "sql": "SELECT quant.bond_price(100, 0.05, 0.05, 10, 2) AS clean_price"},'
    '{"description": "Year fraction of a half-year span under ACT/360.",'
    " \"sql\": \"SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360') AS yf\"},"
    '{"description": "List the supported day-count conventions.",'
    ' "sql": "SELECT name FROM quant.day_count_conventions() ORDER BY name"}'
    "]"
)


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


def _make_option_scalar(
    fname: str,
    summary: str,
    example_extra: str,
    *,
    title: str,
    doc_llm: str,
    doc_md: str,
    keywords: list[str],
) -> type[ScalarFunction]:
    """Build a 6-arg option scalar class for one of the BS price/Greek funcs.

    Args:
        fname: SQL function name, e.g. ``"bs_price"``.
        summary: One-line description for the function.
        example_extra: Description text for the bundled example query.
        title: Human-friendly display name (VGI124).
        doc_llm: Markdown narrative for an LLM/agent audience (VGI112).
        doc_md: Markdown narrative for human docs (VGI113).
        keywords: Search terms / synonyms (VGI126) as a list of strings.

    Returns:
        A configured ``ScalarFunction`` subclass.
    """
    compute_fn = quant.GREEKS[fname]
    fn_tags = object_tags(
        title=title,
        doc_llm=doc_llm,
        doc_md=doc_md,
        keywords=keywords,
    )

    class _OptionScalar(ScalarFunction):
        class Meta:
            """Function metadata."""

            name = fname
            description = summary
            categories = ["quant", "options"]
            tags = fn_tags
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
            """Map each input row to its output value."""
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
    title="Black-Scholes Option Price",
    doc_llm=(
        "## bs_price\n\n"
        "Compute the analytic **Black-Scholes** fair value of a European option.\n\n"
        "**Signature:** `bs_price(spot, strike, rate, vol, ttm, opt_type)`\n\n"
        "**Inputs:** `spot` and `strike` are prices (> 0); `rate` is the "
        "continuously-compounded annual risk-free rate; `vol` is annualized "
        "volatility (>= 0, e.g. `0.2` for 20%); `ttm` is time to maturity in "
        "years (> 0); `opt_type` is the **literal** `'call'` or `'put'`.\n\n"
        "**Output:** a `DOUBLE` option premium in the same currency as `spot`.\n\n"
        "Use this when you need a theoretical option premium per row. There is "
        "no dividend yield (carry equals `rate`). Any NULL input yields NULL; "
        "`ttm <= 0`, negative `vol`, non-positive `spot`/`strike`, or an unknown "
        "`opt_type` raise a clear error. Pair with `implied_vol` to invert a "
        "market price back to volatility."
    ),
    doc_md=(
        "# Black-Scholes Option Price\n\n"
        "Prices a European option with the closed-form Black-Scholes model.\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, 'call');  -- ~10.45\n"
        "```\n\n"
        "## Notes\n\n"
        "- `opt_type` must be a literal `'call'` or `'put'`.\n"
        "- No dividend yield is modeled; carry equals the risk-free `rate`.\n"
        "- At-the-money 1y example above returns roughly `10.4506`."
    ),
    keywords=[
        "black-scholes",
        "option price",
        "european option",
        "call",
        "put",
        "premium",
        "derivatives",
        "bs_price",
    ],
)
BsDeltaFunction = _make_option_scalar(
    "bs_delta",
    "Black-Scholes delta d(value)/d(spot) of a European option",
    "Delta of an ATM call",
    title="Black-Scholes Option Delta",
    doc_llm=(
        "## bs_delta\n\n"
        "First-order Greek: the sensitivity of a European option's value to the "
        "underlying spot price, `d(value)/d(spot)`.\n\n"
        "**Signature:** `bs_delta(spot, strike, rate, vol, ttm, opt_type)` -- "
        "same arguments as `bs_price`; `opt_type` is the literal `'call'`/`'put'`.\n\n"
        "**Output:** a unitless `DOUBLE` in roughly `[0, 1]` for calls and "
        "`[-1, 0]` for puts. Use it for hedge ratios and directional exposure. "
        "NULL in -> NULL out; invalid inputs raise."
    ),
    doc_md=(
        "# Black-Scholes Option Delta\n\n"
        "Delta -- the rate of change of option value with respect to spot.\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_delta(100, 100, 0.05, 0.2, 1, 'call');  -- ~0.637\n"
        "```\n\n"
        "## Notes\n\n"
        "- Calls have positive delta (0..1); puts negative (-1..0).\n"
        "- Commonly used as a hedge ratio against the underlying."
    ),
    keywords=[
        "black-scholes",
        "delta",
        "greeks",
        "hedge ratio",
        "option sensitivity",
        "spot",
        "bs_delta",
    ],
)
BsGammaFunction = _make_option_scalar(
    "bs_gamma",
    "Black-Scholes gamma d2(value)/d(spot)2 of a European option",
    "Gamma of an ATM call",
    title="Black-Scholes Option Gamma",
    doc_llm=(
        "## bs_gamma\n\n"
        "Second-order Greek: the rate of change of delta with respect to spot, "
        "`d2(value)/d(spot)2`.\n\n"
        "**Signature:** `bs_gamma(spot, strike, rate, vol, ttm, opt_type)`.\n\n"
        "Gamma is identical for a call and the matching put. It is largest "
        "at-the-money near expiry and measures how quickly a delta hedge must be "
        "rebalanced. Output is `DOUBLE`. NULL in -> NULL out; invalid inputs raise."
    ),
    doc_md=(
        "# Black-Scholes Option Gamma\n\n"
        "Gamma -- the curvature of option value in spot (rate of change of delta).\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_gamma(100, 100, 0.05, 0.2, 1, 'call');\n"
        "```\n\n"
        "## Notes\n\n"
        "- Equal for a call and its matching put.\n"
        "- Peaks at-the-money and as expiry approaches."
    ),
    keywords=[
        "black-scholes",
        "gamma",
        "greeks",
        "convexity",
        "delta change",
        "option sensitivity",
        "bs_gamma",
    ],
)
BsVegaFunction = _make_option_scalar(
    "bs_vega",
    "Black-Scholes vega d(value)/d(vol), per 1.00 of volatility",
    "Vega of an ATM call (per 1.00 vol)",
    title="Black-Scholes Option Vega",
    doc_llm=(
        "## bs_vega\n\n"
        "Sensitivity of a European option's value to volatility, "
        "`d(value)/d(vol)`, expressed **per 1.00 of volatility** (i.e. per "
        "100%).\n\n"
        "**Signature:** `bs_vega(spot, strike, rate, vol, ttm, opt_type)`.\n\n"
        "Divide the result by 100 to get the more common per-1%-vol vega. Vega "
        "is equal for a call and its matching put and is largest at-the-money. "
        "Output is `DOUBLE`. NULL in -> NULL out; invalid inputs raise."
    ),
    doc_md=(
        "# Black-Scholes Option Vega\n\n"
        "Vega -- sensitivity of option value to volatility, per 1.00 (100%) vol.\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_vega(100, 100, 0.05, 0.2, 1, 'call');  -- ~37.52\n"
        "```\n\n"
        "## Notes\n\n"
        "- Per 1.00 vol; divide by 100 for per-1% vega.\n"
        "- Equal for a call and its matching put."
    ),
    keywords=[
        "black-scholes",
        "vega",
        "greeks",
        "volatility sensitivity",
        "vol",
        "option sensitivity",
        "bs_vega",
    ],
)
BsThetaFunction = _make_option_scalar(
    "bs_theta",
    "Black-Scholes theta d(value)/d(t), per year",
    "Theta of an ATM call (per year)",
    title="Black-Scholes Option Theta",
    doc_llm=(
        "## bs_theta\n\n"
        "Time decay: the rate of change of a European option's value as time "
        "passes, `d(value)/d(t)`, expressed **per year**.\n\n"
        "**Signature:** `bs_theta(spot, strike, rate, vol, ttm, opt_type)`.\n\n"
        "Divide by 365 for theta per calendar day. Theta is typically negative "
        "for long option positions (value erodes toward expiry). Output is "
        "`DOUBLE`. NULL in -> NULL out; invalid inputs raise."
    ),
    doc_md=(
        "# Black-Scholes Option Theta\n\n"
        "Theta -- option time decay, expressed per year.\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_theta(100, 100, 0.05, 0.2, 1, 'call');\n"
        "```\n\n"
        "## Notes\n\n"
        "- Per year; divide by 365 for per-day theta.\n"
        "- Usually negative for long options."
    ),
    keywords=[
        "black-scholes",
        "theta",
        "greeks",
        "time decay",
        "time value",
        "option sensitivity",
        "bs_theta",
    ],
)
BsRhoFunction = _make_option_scalar(
    "bs_rho",
    "Black-Scholes rho d(value)/d(rate), per 1.00 of the rate",
    "Rho of an ATM call (per 1.00 rate)",
    title="Black-Scholes Option Rho",
    doc_llm=(
        "## bs_rho\n\n"
        "Sensitivity of a European option's value to the risk-free interest "
        "rate, `d(value)/d(rate)`, expressed **per 1.00 of the rate** (per 100%).\n\n"
        "**Signature:** `bs_rho(spot, strike, rate, vol, ttm, opt_type)`.\n\n"
        "Divide by 100 for rho per 1% rate move. Calls have positive rho, puts "
        "negative. Output is `DOUBLE`. NULL in -> NULL out; invalid inputs raise."
    ),
    doc_md=(
        "# Black-Scholes Option Rho\n\n"
        "Rho -- sensitivity of option value to the interest rate, per 1.00 rate.\n\n"
        "## Usage\n\n"
        "```sql\n"
        "SELECT quant.bs_rho(100, 100, 0.05, 0.2, 1, 'call');\n"
        "```\n\n"
        "## Notes\n\n"
        "- Per 1.00 rate; divide by 100 for per-1% rho.\n"
        "- Positive for calls, negative for puts."
    ),
    keywords=[
        "black-scholes",
        "rho",
        "greeks",
        "interest rate sensitivity",
        "rate",
        "option sensitivity",
        "bs_rho",
    ],
)


class ImpliedVolFunction(ScalarFunction):
    """``implied_vol(price, spot, strike, rate, ttm, opt_type)`` -- BS implied vol."""

    class Meta:
        """Function metadata."""

        name = "implied_vol"
        description = "Black-Scholes implied volatility reproducing an option price (raises if not invertible)"
        categories = ["quant", "options"]
        tags = object_tags(
            title="Black-Scholes Implied Volatility",
            doc_llm=(
                "## implied_vol\n\n"
                "Invert the Black-Scholes model: given an observed option "
                "**price**, solve for the volatility that reproduces it.\n\n"
                "**Signature:** `implied_vol(price, spot, strike, rate, ttm, opt_type)` "
                "-- note `price` comes **first** and there is no `vol` argument "
                "(that is what is solved for). `opt_type` is the literal "
                "`'call'`/`'put'`.\n\n"
                "**Output:** annualized volatility as a `DOUBLE` (e.g. `0.20` for "
                "20%). Use it to back out market-implied vol from quoted prices. "
                "NULL in -> NULL out; a non-invertible price (e.g. below intrinsic "
                "value) raises a clear error."
            ),
            doc_md=(
                "# Black-Scholes Implied Volatility\n\n"
                "Solves for the volatility consistent with an observed option price.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.implied_vol(10.45, 100, 100, 0.05, 1, 'call');  -- ~0.20\n"
                "```\n\n"
                "## Notes\n\n"
                "- Argument order is `(price, spot, strike, rate, ttm, opt_type)`.\n"
                "- Round-trips `bs_price`: feeding its output recovers the vol.\n"
                "- Raises if the price is not invertible (e.g. below intrinsic)."
            ),
            keywords=[
                "black-scholes",
                "implied volatility",
                "iv",
                "invert",
                "option price",
                "vol surface",
                "implied_vol",
            ],
        )
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
        """Map each input row to its output value."""
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
        """Function metadata."""

        name = "bond_price"
        description = "Clean price of a fixed-rate bond at a given yield (par bond prices to face)"
        categories = ["quant", "bonds"]
        tags = object_tags(
            title="Fixed-Rate Bond Price",
            doc_llm=(
                "## bond_price\n\n"
                "Compute the **clean** price of a fixed-rate coupon bond at a "
                "given yield.\n\n"
                "**Signature:** `bond_price(face, coupon_rate, yield_rate, years, freq)` "
                "-- `face` is par value (> 0); `coupon_rate` and `yield_rate` are "
                "annual decimals (e.g. `0.05`); `years` is whole years to "
                "maturity (> 0); `freq` is the **literal** coupon frequency "
                "(`1`=annual, `2`=semiannual, `4`=quarterly, `12`=monthly).\n\n"
                "**Output:** clean price as a `DOUBLE`. A par bond (coupon == "
                "yield) prices to ~`face`. Inverse of `bond_yield`. NULL in -> "
                "NULL out; `years <= 0` or an unknown `freq` raise."
            ),
            doc_md=(
                "# Fixed-Rate Bond Price\n\n"
                "Clean price of a fixed-rate bond given its yield to maturity.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.bond_price(100, 0.05, 0.05, 10, 2);  -- ~100 (par)\n"
                "```\n\n"
                "## Notes\n\n"
                "- `freq` must be a literal `1`, `2`, `4`, or `12`.\n"
                "- Uses ActualActual(ISDA), compounded at the coupon frequency.\n"
                "- A par bond (coupon == yield) prices to face value."
            ),
            keywords=[
                "bond",
                "fixed-rate bond",
                "clean price",
                "present value",
                "coupon",
                "fixed income",
                "bond_price",
            ],
        )
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
        """Map each input row to its output value."""
        return _map_floats(
            [face, coupon_rate, yield_rate, years],
            lambda f, c, y, yr: quant.bond_price(f, c, y, int(yr), freq),
        )


class BondYieldFunction(ScalarFunction):
    """``bond_yield(price, face, coupon_rate, years, freq)`` -- yield to maturity."""

    class Meta:
        """Function metadata."""

        name = "bond_yield"
        description = "Yield to maturity implied by a clean bond price (inverse of bond_price)"
        categories = ["quant", "bonds"]
        tags = object_tags(
            title="Fixed-Rate Bond Yield",
            doc_llm=(
                "## bond_yield\n\n"
                "Solve for the **yield to maturity** implied by a clean bond "
                "price -- the inverse of `bond_price`.\n\n"
                "**Signature:** `bond_yield(price, face, coupon_rate, years, freq)` "
                "-- `price` is the observed clean price (> 0); `face` is par "
                "(> 0); `coupon_rate` is the annual decimal coupon; `years` is "
                "whole years; `freq` is the **literal** coupon frequency "
                "(`1`/`2`/`4`/`12`).\n\n"
                "**Output:** annual yield to maturity as a `DOUBLE` (e.g. `0.05` "
                "for 5%). Use it to convert a quoted price into a comparable "
                "yield. NULL in -> NULL out; invalid inputs raise."
            ),
            doc_md=(
                "# Fixed-Rate Bond Yield\n\n"
                "Yield to maturity implied by a clean bond price.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.bond_yield(100, 100, 0.05, 10, 2);  -- ~0.05\n"
                "```\n\n"
                "## Notes\n\n"
                "- Argument order is `(price, face, coupon_rate, years, freq)`.\n"
                "- Inverts `bond_price`: feed its output to recover the yield.\n"
                "- `freq` must be a literal `1`, `2`, `4`, or `12`."
            ),
            keywords=[
                "bond",
                "yield to maturity",
                "ytm",
                "fixed income",
                "invert price",
                "coupon",
                "bond_yield",
            ],
        )
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
        """Map each input row to its output value."""
        return _map_floats(
            [price, face, coupon_rate, years],
            lambda p, f, c, yr: quant.bond_yield(p, f, c, int(yr), freq),
        )


class BondDurationFunction(ScalarFunction):
    """``bond_duration(face, coupon_rate, yield_rate, years, freq)`` -- modified duration."""

    class Meta:
        """Function metadata."""

        name = "bond_duration"
        description = "Modified duration of a fixed-rate bond at a given yield"
        categories = ["quant", "bonds"]
        tags = object_tags(
            title="Fixed-Rate Bond Modified Duration",
            doc_llm=(
                "## bond_duration\n\n"
                "Compute the **modified duration** of a fixed-rate bond at a "
                "given yield -- the first-order sensitivity of price to yield, "
                "in years.\n\n"
                "**Signature:** `bond_duration(face, coupon_rate, yield_rate, years, freq)` "
                "-- same inputs as `bond_price`; `freq` is the literal coupon "
                "frequency (`1`/`2`/`4`/`12`).\n\n"
                "**Output:** modified duration in years as a `DOUBLE`. A 1% (100 "
                "bp) yield rise drops price by roughly `duration%`. Duration is "
                "less than maturity for a coupon bond. NULL in -> NULL out; "
                "invalid inputs raise."
            ),
            doc_md=(
                "# Fixed-Rate Bond Modified Duration\n\n"
                "Modified duration -- price sensitivity to yield, in years.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.bond_duration(100, 0.05, 0.05, 10, 2);  -- ~7.80\n"
                "```\n\n"
                "## Notes\n\n"
                "- Modified (not Macaulay) duration.\n"
                "- A 1% yield rise drops price by roughly `duration%`.\n"
                "- Always less than maturity for a coupon-paying bond."
            ),
            keywords=[
                "bond",
                "modified duration",
                "interest rate risk",
                "sensitivity",
                "fixed income",
                "bond_duration",
            ],
        )
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
        """Map each input row to its output value."""
        return _map_floats(
            [face, coupon_rate, yield_rate, years],
            lambda f, c, y, yr: quant.bond_duration(f, c, y, int(yr), freq),
        )


class BondConvexityFunction(ScalarFunction):
    """``bond_convexity(face, coupon_rate, yield_rate, years, freq)`` -- convexity."""

    class Meta:
        """Function metadata."""

        name = "bond_convexity"
        description = "Convexity of a fixed-rate bond at a given yield"
        categories = ["quant", "bonds"]
        tags = object_tags(
            title="Fixed-Rate Bond Convexity",
            doc_llm=(
                "## bond_convexity\n\n"
                "Compute the **convexity** of a fixed-rate bond at a given yield "
                "-- the second-order sensitivity of price to yield that refines "
                "the duration estimate.\n\n"
                "**Signature:** `bond_convexity(face, coupon_rate, yield_rate, years, freq)` "
                "-- same inputs as `bond_price`; `freq` is the literal coupon "
                "frequency (`1`/`2`/`4`/`12`).\n\n"
                "**Output:** convexity as a `DOUBLE` (positive for plain bonds). "
                "Combine with `bond_duration` for a second-order price-change "
                "approximation under large yield moves. NULL in -> NULL out; "
                "invalid inputs raise."
            ),
            doc_md=(
                "# Fixed-Rate Bond Convexity\n\n"
                "Convexity -- second-order price sensitivity to yield.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.bond_convexity(100, 0.05, 0.05, 10, 2);  -- ~73.65\n"
                "```\n\n"
                "## Notes\n\n"
                "- Positive for plain vanilla bonds.\n"
                "- Refines the duration-based price-change estimate.\n"
                "- Larger for longer maturities and lower coupons."
            ),
            keywords=[
                "bond",
                "convexity",
                "interest rate risk",
                "second order",
                "fixed income",
                "bond_convexity",
            ],
        )
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
        """Map each input row to its output value."""
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
        """Function metadata."""

        name = "year_fraction"
        description = (
            "Year fraction between two dates under a day-count convention "
            "('ACT/360', 'ACT/365', '30/360', 'ACT/ACT'). Unknown convention raises."
        )
        categories = ["quant", "conventions"]
        tags = {
            **object_tags(
                title="Day-Count Year Fraction",
                doc_llm=(
                    "## year_fraction\n\n"
                    "Compute the **year fraction** between two dates under a "
                    "day-count convention -- the accrual basis used to prorate "
                    "interest and discount factors.\n\n"
                    "**Signature:** `year_fraction(start, end, convention)` -- "
                    "`start` and `end` are `DATE` columns; `convention` is the "
                    "**literal** convention string: `'ACT/360'`, `'ACT/365'`, "
                    "`'30/360'`, or `'ACT/ACT'` (case-insensitive). Discover the "
                    "accepted strings with `quant.day_count_conventions()`.\n\n"
                    "**Output:** the elapsed time as a fraction of a year "
                    "(`DOUBLE`). NULL dates -> NULL; an unknown convention raises."
                ),
                doc_md=(
                    "# Day-Count Year Fraction\n\n"
                    "Year fraction between two dates under a day-count convention.\n\n"
                    "## Usage\n\n"
                    "```sql\n"
                    "SELECT quant.year_fraction(DATE '2026-01-01', "
                    "DATE '2026-07-01', 'ACT/360');  -- 181/360 ~ 0.5028\n"
                    "```\n\n"
                    "## Notes\n\n"
                    "- Conventions: `ACT/360`, `ACT/365`, `30/360`, `ACT/ACT`.\n"
                    "- Convention matching is case-insensitive.\n"
                    "- See `day_count_conventions()` for the full list."
                ),
                keywords=[
                    "day count",
                    "year fraction",
                    "accrual",
                    "act/360",
                    "act/365",
                    "30/360",
                    "act/act",
                    "convention",
                    "year_fraction",
                ],
            ),
            "vgi.executable_examples": _YEAR_FRACTION_EXECUTABLE_EXAMPLES,
        }
        examples = [
            FunctionExample(
                sql="SELECT quant.year_fraction(DATE '2026-01-01', DATE '2026-07-01', 'ACT/360')",
                description="Half-ish year under ACT/360 (181/360)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        start: Annotated[pa.Date32Array, Param(doc="Start of the accrual period (inclusive).")],
        end: Annotated[pa.Date32Array, Param(doc="End of the accrual period; the span runs from start to here.")],
        convention: Annotated[str, ConstParam("Day-count convention string; see day_count_conventions().")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_dates(start, end, lambda s, e: quant.year_fraction(s, e, convention))


class DiscountFactorFunction(ScalarFunction):
    """``discount_factor(rate, ttm)`` -- continuously-compounded discount factor."""

    class Meta:
        """Function metadata."""

        name = "discount_factor"
        description = "Continuously-compounded discount factor exp(-rate * ttm)"
        categories = ["quant", "conventions"]
        tags = object_tags(
            title="Continuous Discount Factor",
            doc_llm=(
                "## discount_factor\n\n"
                "Compute the continuously-compounded **discount factor** "
                "`exp(-rate * ttm)` -- the present value today of one unit of "
                "currency received at a future time.\n\n"
                "**Signature:** `discount_factor(rate, ttm)` -- `rate` is the "
                "continuously-compounded annual rate; `ttm` is the time horizon "
                "in years.\n\n"
                "**Output:** a `DOUBLE` in `(0, 1]` for non-negative rates. "
                "Multiply a future cash flow by it to discount (or use "
                "`present_value`). NULL in -> NULL out."
            ),
            doc_md=(
                "# Continuous Discount Factor\n\n"
                "Continuously-compounded discount factor `exp(-rate * ttm)`.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.discount_factor(0.05, 1);  -- exp(-0.05) ~ 0.9512\n"
                "```\n\n"
                "## Notes\n\n"
                "- Continuous compounding (not periodic).\n"
                "- Multiply a future amount by this to get its present value."
            ),
            keywords=[
                "discount factor",
                "present value",
                "continuous compounding",
                "exp",
                "discounting",
                "discount_factor",
            ],
        )
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
        """Map each input row to its output value."""
        return _map_floats([rate, ttm], quant.discount_factor)


class PresentValueFunction(ScalarFunction):
    """``present_value(amount, rate, ttm)`` -- continuously-discounted present value."""

    class Meta:
        """Function metadata."""

        name = "present_value"
        description = "Present value amount * exp(-rate * ttm) (continuous compounding)"
        categories = ["quant", "conventions"]
        tags = object_tags(
            title="Continuous Present Value",
            doc_llm=(
                "## present_value\n\n"
                "Compute the **present value** of a future cash amount under "
                "continuous compounding: `amount * exp(-rate * ttm)`.\n\n"
                "**Signature:** `present_value(amount, rate, ttm)` -- `amount` is "
                "the future cash flow; `rate` is the continuously-compounded "
                "annual discount rate; `ttm` is the time horizon in years.\n\n"
                "**Output:** the discounted value today as a `DOUBLE`. Equivalent "
                "to `amount * discount_factor(rate, ttm)`. NULL in -> NULL out."
            ),
            doc_md=(
                "# Continuous Present Value\n\n"
                "Present value of a future amount, `amount * exp(-rate * ttm)`.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT quant.present_value(100, 0.05, 1);  -- ~95.12\n"
                "```\n\n"
                "## Notes\n\n"
                "- Continuous compounding.\n"
                "- Equals `amount * discount_factor(rate, ttm)`."
            ),
            keywords=[
                "present value",
                "discounting",
                "npv",
                "continuous compounding",
                "time value of money",
                "present_value",
            ],
        )
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
        """Map each input row to its output value."""
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
