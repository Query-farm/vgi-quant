"""Carry scalars: the annual financing rate implied by an instrument's price.

Each function turns one instrument's quote into a **continuously compounded
annual rate**, the same basis as ``rate`` in the option and discounting
functions. Putting every instrument on one basis is the point: a futures
curve, a box spread, a Treasury bill and a perpetual-futures funding rate can
then be compared, subtracted or ranked in one query.

    SELECT implied_carry_rate(spot, future, ttm) - tbill_rate(0.0412, 91)
    SELECT funding_rate_annual(0.0001, 8)  -- a perp floor rate, ~0.1095

NULL in -> NULL out; invalid non-NULL input raises (see ``vgi_quant.quant``).
"""

from __future__ import annotations

from typing import Annotated

import pyarrow as pa
from vgi.arguments import Param, Returns
from vgi.scalar_function import ScalarFunction

from . import quant
from .meta import object_tags
from .scalars import _map_floats

_F64 = pa.float64()
_TTM = Param(_F64, doc="Time to maturity in years (> 0), e.g. days / 365.")
_RESULT = "a `DOUBLE` continuously compounded annual rate (0.05 = 5%/yr). NULL in -> NULL out."


class ImpliedCarryRateFunction(ScalarFunction):
    """``implied_carry_rate(spot, forward, ttm)`` -- rate implied by spot vs a future."""

    class Meta:
        """Function metadata."""

        name = "implied_carry_rate"
        description = "Annual cost of carry implied by a spot and a futures price: ln(forward/spot)/ttm"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Implied Carry Rate",
            doc_llm=(
                "## implied_carry_rate\n\n"
                "The annual rate implied by the gap between a spot price and a forward or "
                "futures price on the same underlying: `ln(forward / spot) / ttm`.\n\n"
                "**Signature:** `implied_carry_rate(spot, forward, ttm)`; prices > 0, `ttm` in years.\n\n"
                "**Meaning:** the net cost of carry, i.e. financing minus any income the "
                "underlying pays (dividends, lease rate, convenience yield). For gold, income "
                "is roughly zero, so this is the financing rate a cash-and-carry trade earns: "
                "buy spot, sell the future. Compare it with `tbill_rate` or `box_spread_rate`.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Implied Carry Rate\n\n"
                "Annualized basis between spot and a future, `ln(forward / spot) / ttm`.\n\n"
                "```sql\n"
                "SELECT quant.implied_carry_rate(4000, 4050, 0.25);  -- ~0.0497\n"
                "```\n\n"
                "- Continuously compounded; convert with `continuous_to_simple`.\n"
                "- Negative when the future trades below spot (backwardation)."
            ),
            keywords=["cost of carry", "basis", "cash and carry", "futures", "forward", "implied repo"],
            examples=[
                (
                    "Gold at 4000 spot with the 3-month future at 4050 implies ~4.97%/yr of carry.",
                    "SELECT ROUND(quant.main.implied_carry_rate(4000, 4050, 0.25), 4) AS carry",
                ),
                (
                    "Carry over a 3-month T-bill: what a cash-and-carry earns above cash.",
                    "SELECT ROUND(quant.main.implied_carry_rate(4000, 4050, 0.25)"
                    " - quant.main.tbill_rate(0.0412, 91), 4) AS excess",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        spot: Annotated[pa.DoubleArray, Param(_F64, doc="Spot price of the underlying (> 0).")],
        forward: Annotated[pa.DoubleArray, Param(_F64, doc="Forward or futures price (> 0).")],
        ttm: Annotated[pa.DoubleArray, _TTM],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([spot, forward, ttm], quant.implied_carry_rate)


class CalendarSpreadRateFunction(ScalarFunction):
    """``calendar_spread_rate(near_price, far_price, near_ttm, far_ttm)`` -- rate between two expiries."""

    class Meta:
        """Function metadata."""

        name = "calendar_spread_rate"
        description = "Annual rate implied between two futures expiries: ln(far/near)/(far_ttm-near_ttm)"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Calendar Spread Rate",
            doc_llm=(
                "## calendar_spread_rate\n\n"
                "The forward financing rate implied by two futures on the same underlying: "
                "`ln(far_price / near_price) / (far_ttm - near_ttm)`.\n\n"
                "**Signature:** `calendar_spread_rate(near_price, far_price, near_ttm, far_ttm)`; "
                "prices > 0, `near_ttm >= 0`, `far_ttm > near_ttm`, both in years from today.\n\n"
                "**Use:** read a futures curve as a strip of forward rates, e.g. the Dec->Feb "
                "and Feb->Apr legs of the gold curve, without needing a spot price.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Calendar Spread Rate\n\n"
                "Forward rate between two futures expiries.\n\n"
                "```sql\n"
                "SELECT quant.calendar_spread_rate(4050, 4110, 0.25, 0.5);  -- ~0.0588\n"
                "```\n\n"
                "- `far_ttm` must be later than `near_ttm`.\n"
                "- Use `LEAD()` over a curve ordered by expiry to get every leg."
            ),
            keywords=["calendar spread", "futures curve", "term structure", "roll yield", "forward rate"],
            examples=[
                (
                    "Gold 3-month future at 4050 and 6-month at 4110 imply ~5.88%/yr between them.",
                    "SELECT ROUND(quant.main.calendar_spread_rate(4050, 4110, 0.25, 0.5), 4) AS fwd_rate",
                ),
                (
                    "Every leg of a futures curve, using LEAD over expiries.",
                    "SELECT ttm, ROUND(quant.main.calendar_spread_rate(px, nx_px, ttm, nx_ttm), 4) AS leg_rate"
                    " FROM (SELECT ttm, px, LEAD(px) OVER (ORDER BY ttm) AS nx_px,"
                    " LEAD(ttm) OVER (ORDER BY ttm) AS nx_ttm"
                    " FROM (VALUES (0.1, 4020.0), (0.25, 4050.0), (0.5, 4110.0)) c(ttm, px))"
                    " WHERE nx_px IS NOT NULL ORDER BY ttm",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        near_price: Annotated[pa.DoubleArray, Param(_F64, doc="Price of the nearer futures expiry (> 0).")],
        far_price: Annotated[pa.DoubleArray, Param(_F64, doc="Price of the later futures expiry (> 0).")],
        near_ttm: Annotated[pa.DoubleArray, Param(_F64, doc="Years until the nearer expiry (>= 0).")],
        far_ttm: Annotated[pa.DoubleArray, Param(_F64, doc="Years until the later expiry (> near_ttm).")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([near_price, far_price, near_ttm, far_ttm], quant.calendar_spread_rate)


class BoxSpreadRateFunction(ScalarFunction):
    """``box_spread_rate(box_price, low_strike, high_strike, ttm)`` -- rate implied by a box."""

    class Meta:
        """Function metadata."""

        name = "box_spread_rate"
        description = "Annual rate implied by a European box spread: ln((high-low)/box_price)/ttm"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Box Spread Rate",
            doc_llm=(
                "## box_spread_rate\n\n"
                "The lending/borrowing rate implied by a European box spread. A box is long a "
                "call and short a put at `low_strike` plus short a call and long a put at "
                "`high_strike`; it pays `high_strike - low_strike` at expiry regardless of the "
                "underlying, so it is a zero-coupon loan.\n\n"
                "**Signature:** `box_spread_rate(box_price, low_strike, high_strike, ttm)`. "
                "`box_price` is the net cost of the four legs: "
                "`call(low) - call(high) + put(high) - put(low)`, in the same units as the "
                "strikes (not multiplied by the contract multiplier).\n\n"
                "**Use:** buying a box lends at this rate; selling one borrows at it. "
                "Compare with `tbill_rate` and `implied_carry_rate`. Only European-style "
                "options (e.g. SPX) are safe from early assignment.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Box Spread Rate\n\n"
                "Implied rate of a European box spread.\n\n"
                "```sql\n"
                "SELECT quant.box_spread_rate(989, 5000, 6000, 0.25);  -- ~0.0442\n"
                "```\n\n"
                "- `box_price = call(low) - call(high) + put(high) - put(low)`.\n"
                "- Use European-exercise options; American legs can be assigned early."
            ),
            keywords=["box spread", "synthetic loan", "options financing", "spx box", "implied rate"],
            examples=[
                (
                    "A 1000-wide SPX box costing 989 with 3 months left lends at ~4.42%/yr.",
                    "SELECT ROUND(quant.main.box_spread_rate(989, 5000, 6000, 0.25), 4) AS box_rate",
                ),
                (
                    "Price the box from its four legs, then take its rate.",
                    "SELECT ROUND(quant.main.box_spread_rate(c_lo - c_hi + p_hi - p_lo, 5000, 6000, 0.25), 4)"
                    " AS box_rate FROM (VALUES (1050.0, 210.0, 160.0, 11.0)) l(c_lo, c_hi, p_hi, p_lo)",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        box_price: Annotated[pa.DoubleArray, Param(_F64, doc="Net cost of the four-leg box, in strike units (> 0).")],
        low_strike: Annotated[pa.DoubleArray, Param(_F64, doc="Lower strike (> 0).")],
        high_strike: Annotated[pa.DoubleArray, Param(_F64, doc="Upper strike (> low_strike).")],
        ttm: Annotated[pa.DoubleArray, _TTM],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([box_price, low_strike, high_strike, ttm], quant.box_spread_rate)


class TbillRateFunction(ScalarFunction):
    """``tbill_rate(discount_rate, days)`` -- continuous rate of a discount-quoted T-bill."""

    class Meta:
        """Function metadata."""

        name = "tbill_rate"
        description = "Continuous annual rate of a T-bill quoted on the bank-discount basis (ACT/360)"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Treasury Bill Rate",
            doc_llm=(
                "## tbill_rate\n\n"
                "Converts a Treasury bill's bank-discount quote into a continuously compounded "
                "annual rate, so it can be compared with the other carry functions.\n\n"
                "**Signature:** `tbill_rate(discount_rate, days)`; `discount_rate` as a decimal "
                "(0.0412 for 4.12%), `days` to maturity (> 0). Price per 1 of face is "
                "`1 - discount_rate * days / 360`; the result is `-ln(price) / (days / 365)`.\n\n"
                "**Use:** the risk-free benchmark. Yahoo's `^IRX` and Treasury's daily bill "
                "rates are discount quotes for the 13-week (91-day) bill.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Treasury Bill Rate\n\n"
                "Bank-discount T-bill quote to a continuous annual rate.\n\n"
                "```sql\n"
                "SELECT quant.tbill_rate(0.0412, 91);  -- ~0.0420\n"
                "```\n\n"
                "- Discount yields understate the true rate; this corrects for that and for ACT/360."
            ),
            keywords=["treasury bill", "t-bill", "discount yield", "risk-free rate", "irx", "money market"],
            examples=[
                (
                    "A 91-day bill quoted at a 4.12% discount is ~4.20%/yr continuous.",
                    "SELECT ROUND(quant.main.tbill_rate(0.0412, 91), 4) AS bill_rate",
                ),
                (
                    "Bill-equivalent rates for a few quotes and tenors.",
                    "SELECT days, ROUND(quant.main.tbill_rate(d, days), 4) AS rate"
                    " FROM (VALUES (0.0412, 28), (0.0412, 91), (0.0400, 182)) q(d, days) ORDER BY days",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        discount_rate: Annotated[pa.DoubleArray, Param(_F64, doc="Bank-discount yield as a decimal (0.0412 = 4.12%).")],
        days: Annotated[pa.DoubleArray, Param(_F64, doc="Days to maturity (> 0).")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([discount_rate, days], quant.tbill_rate)


class FundingRateAnnualFunction(ScalarFunction):
    """``funding_rate_annual(rate, interval_hours)`` -- annualize a perp funding rate."""

    class Meta:
        """Function metadata."""

        name = "funding_rate_annual"
        description = "Continuous annual rate equivalent to a perpetual-futures funding rate"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Annualized Funding Rate",
            doc_llm=(
                "## funding_rate_annual\n\n"
                "Annualizes a perpetual-futures funding rate onto the same continuous basis as "
                "the other carry functions: `ln(1 + rate) * 8760 / interval_hours`.\n\n"
                "**Signature:** `funding_rate_annual(rate, interval_hours)`; `rate` is the "
                "per-interval rate as a decimal (0.0001 = 1 bp), `interval_hours` how often it "
                "is paid (8 on most venues, 1 on Hyperliquid).\n\n"
                "**Sign:** positive means longs pay shorts, so it is what a short earns. A "
                "short perp plus a long future earns `funding_rate_annual(...) - "
                "implied_carry_rate(...)`.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Annualized Funding Rate\n\n"
                "Perp funding to a continuous annual rate.\n\n"
                "```sql\n"
                "SELECT quant.funding_rate_annual(0.0001, 8);  -- the 1 bp/8h floor, ~0.1095\n"
                "```\n\n"
                "- Treats each payment as compounding; the simple `rate * 1095` differs only "
                "slightly at normal rates."
            ),
            keywords=["funding rate", "perpetual futures", "perps", "annualize", "basis trade"],
            examples=[
                (
                    "The common 1 bp per 8 hours funding floor is ~10.95%/yr.",
                    "SELECT ROUND(quant.main.funding_rate_annual(0.0001, 8), 4) AS annual",
                ),
                (
                    "A short perp hedged with a long future: funding minus futures carry.",
                    "SELECT ROUND(quant.main.funding_rate_annual(0.0001, 8)"
                    " - quant.main.implied_carry_rate(4000, 4050, 0.25), 4) AS net_carry",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        rate: Annotated[pa.DoubleArray, Param(_F64, doc="Funding rate per interval as a decimal (> -1).")],
        interval_hours: Annotated[pa.DoubleArray, Param(_F64, doc="Hours between funding payments (> 0).")],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([rate, interval_hours], quant.funding_rate_annual)


class SimpleToContinuousFunction(ScalarFunction):
    """``simple_to_continuous(rate, ttm)`` -- simple annual rate to continuous."""

    class Meta:
        """Function metadata."""

        name = "simple_to_continuous"
        description = "Convert a simple annual rate over ttm years to continuous: ln(1+rate*ttm)/ttm"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Simple to Continuous Rate",
            doc_llm=(
                "## simple_to_continuous\n\n"
                "Converts a simple (money-market) annual rate, where interest is `rate * ttm`, "
                "into the continuously compounded rate the carry functions return: "
                "`ln(1 + rate * ttm) / ttm`.\n\n"
                "**Signature:** `simple_to_continuous(rate, ttm)`; `ttm` in years (> 0).\n\n"
                "**Use:** bring a quoted simple rate (SOFR term rate, a broker's margin rate, "
                "a simple-annualized funding rate) onto the continuous basis.\n\n"
                f"**Output:** {_RESULT}"
            ),
            doc_md=(
                "# Simple to Continuous Rate\n\n"
                "```sql\n"
                "SELECT quant.simple_to_continuous(0.05, 0.5);  -- ~0.0494\n"
                "```\n\n"
                "- Inverse of `continuous_to_simple` for the same `ttm`."
            ),
            keywords=["compounding", "rate conversion", "simple interest", "continuous compounding"],
            examples=[
                (
                    "5% simple over six months is ~4.94% continuous.",
                    "SELECT ROUND(quant.main.simple_to_continuous(0.05, 0.5), 4) AS cont",
                ),
                (
                    "Round trip through continuous_to_simple returns the input.",
                    "SELECT ROUND(quant.main.continuous_to_simple("
                    "quant.main.simple_to_continuous(0.05, 0.5), 0.5), 6) AS back",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        rate: Annotated[pa.DoubleArray, Param(_F64, doc="Simple annual rate as a decimal.")],
        ttm: Annotated[pa.DoubleArray, _TTM],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([rate, ttm], quant.simple_to_continuous)


class ContinuousToSimpleFunction(ScalarFunction):
    """``continuous_to_simple(rate, ttm)`` -- continuous annual rate to simple."""

    class Meta:
        """Function metadata."""

        name = "continuous_to_simple"
        description = "Convert a continuous annual rate to a simple rate over ttm years: (exp(rate*ttm)-1)/ttm"
        categories = ["quant", "carry"]
        tags = object_tags(
            category="carry",
            title="Continuous to Simple Rate",
            doc_llm=(
                "## continuous_to_simple\n\n"
                "Converts a continuously compounded annual rate (what the carry functions "
                "return) into a simple annual rate over a holding period: "
                "`(exp(rate * ttm) - 1) / ttm`.\n\n"
                "**Signature:** `continuous_to_simple(rate, ttm)`; `ttm` in years (> 0).\n\n"
                "**Use:** turn a carry rate into the simple return of a trade held for `ttm`, "
                "e.g. dollars earned = notional * result * ttm.\n\n"
                "**Output:** a `DOUBLE` simple annual rate. NULL in -> NULL out."
            ),
            doc_md=(
                "# Continuous to Simple Rate\n\n"
                "```sql\n"
                "SELECT quant.continuous_to_simple(0.05, 0.5);  -- ~0.0506\n"
                "```\n\n"
                "- Inverse of `simple_to_continuous` for the same `ttm`."
            ),
            keywords=["compounding", "rate conversion", "simple interest", "holding period return"],
            examples=[
                (
                    "5% continuous over six months is ~5.06% simple.",
                    "SELECT ROUND(quant.main.continuous_to_simple(0.05, 0.5), 4) AS simple",
                ),
                (
                    "Dollar carry on $100,000 held 3 months at the gold futures carry rate.",
                    "SELECT ROUND(100000 * quant.main.continuous_to_simple("
                    "quant.main.implied_carry_rate(4000, 4050, 0.25), 0.25) * 0.25, 2) AS dollars",
                ),
            ],
        )

    @classmethod
    def compute(
        cls,
        rate: Annotated[pa.DoubleArray, Param(_F64, doc="Continuously compounded annual rate as a decimal.")],
        ttm: Annotated[pa.DoubleArray, _TTM],
    ) -> Annotated[pa.DoubleArray, Returns(_F64)]:
        """Map each input row to its output value."""
        return _map_floats([rate, ttm], quant.continuous_to_simple)


CARRY_FUNCTIONS: list[type] = [
    ImpliedCarryRateFunction,
    CalendarSpreadRateFunction,
    BoxSpreadRateFunction,
    TbillRateFunction,
    FundingRateAnnualFunction,
    SimpleToContinuousFunction,
    ContinuousToSimpleFunction,
]
