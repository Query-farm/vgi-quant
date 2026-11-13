"""Unit tests for the pure quant compute layer (``vgi_quant.quant``).

These call the pure ``float``-in / ``float``-out functions directly (no Arrow,
no worker) and assert against KNOWN textbook values within tolerance. The Arrow
adapters are exercised separately in ``test_scalars.py`` (real Client RPC) and
``test/sql/*.test`` (real ATTACH + SELECT).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from vgi_quant import quant

# A standard textbook Black-Scholes case:
# spot=100, strike=100, rate=0.05, vol=0.20, ttm=1, call.
_STD = dict(spot=100.0, strike=100.0, rate=0.05, vol=0.20, ttm=1.0)


class TestBlackScholes:
    def test_call_price(self) -> None:
        # Hull-style textbook value ~10.4506.
        assert quant.bs_price(opt_type="call", **_STD) == pytest.approx(10.4506, abs=1e-3)

    def test_call_delta(self) -> None:
        assert quant.bs_delta(opt_type="call", **_STD) == pytest.approx(0.6368, abs=1e-3)

    def test_put_delta_is_call_delta_minus_one(self) -> None:
        call_d = quant.bs_delta(opt_type="call", **_STD)
        put_d = quant.bs_delta(opt_type="put", **_STD)
        assert put_d == pytest.approx(call_d - 1.0, abs=1e-9)

    def test_gamma_positive_and_symmetric(self) -> None:
        # Gamma is the same for a call and a put at the same strike.
        g_call = quant.bs_gamma(opt_type="call", **_STD)
        g_put = quant.bs_gamma(opt_type="put", **_STD)
        assert g_call > 0
        assert g_call == pytest.approx(g_put, abs=1e-12)

    def test_vega_per_full_vol(self) -> None:
        # Vega is per 1.00 (100 pct) vol; ATM 1y ~37.52.
        assert quant.bs_vega(opt_type="call", **_STD) == pytest.approx(37.524, abs=1e-2)

    def test_theta_negative_for_long_call(self) -> None:
        assert quant.bs_theta(opt_type="call", **_STD) < 0

    def test_rho_call_positive(self) -> None:
        assert quant.bs_rho(opt_type="call", **_STD) > 0

    def test_put_call_parity(self) -> None:
        # C - P = spot - strike * exp(-rate * ttm)
        c = quant.bs_price(opt_type="call", **_STD)
        p = quant.bs_price(opt_type="put", **_STD)
        lhs = c - p
        rhs = _STD["spot"] - _STD["strike"] * math.exp(-_STD["rate"] * _STD["ttm"])
        assert lhs == pytest.approx(rhs, abs=1e-9)

    def test_zero_vol_call_is_discounted_intrinsic_forward(self) -> None:
        # vol == 0 is allowed: value collapses to the (forward) intrinsic.
        v = quant.bs_price(spot=100, strike=90, rate=0.05, vol=0.0, ttm=1, opt_type="call")
        expected = (100 * math.exp(0.05) - 90) * math.exp(-0.05)
        assert v == pytest.approx(expected, abs=1e-9)

    def test_invalid_opt_type_raises(self) -> None:
        with pytest.raises(ValueError):
            quant.bs_price(spot=100, strike=100, rate=0.05, vol=0.2, ttm=1, opt_type="straddle")

    @pytest.mark.parametrize("bad", [{"ttm": 0.0}, {"ttm": -1.0}, {"vol": -0.1}])
    def test_invalid_numeric_raises(self, bad: dict) -> None:
        args = {**_STD, **bad, "opt_type": "call"}
        with pytest.raises(ValueError):
            quant.bs_price(**args)


class TestImpliedVol:
    def test_round_trips_input_vol(self) -> None:
        price = quant.bs_price(opt_type="call", **_STD)
        iv = quant.implied_vol(price, spot=100, strike=100, rate=0.05, ttm=1, opt_type="call")
        assert iv == pytest.approx(0.20, abs=1e-4)

    def test_put_round_trip(self) -> None:
        price = quant.bs_price(opt_type="put", **_STD)
        iv = quant.implied_vol(price, spot=100, strike=100, rate=0.05, ttm=1, opt_type="put")
        assert iv == pytest.approx(0.20, abs=1e-4)

    def test_price_below_intrinsic_raises(self) -> None:
        # A call cannot trade below its discounted intrinsic; not invertible.
        with pytest.raises(ValueError):
            quant.implied_vol(0.0, spot=200, strike=100, rate=0.05, ttm=1, opt_type="call")

    def test_zero_ttm_raises(self) -> None:
        with pytest.raises(ValueError):
            quant.implied_vol(10.0, spot=100, strike=100, rate=0.05, ttm=0, opt_type="call")


class TestBonds:
    def test_par_bond_prices_to_face(self) -> None:
        # coupon == yield -> price ~ face.
        assert quant.bond_price(100, 0.05, 0.05, 10, 2) == pytest.approx(100.0, abs=1e-3)

    def test_premium_when_coupon_above_yield(self) -> None:
        assert quant.bond_price(100, 0.06, 0.05, 10, 2) > 100.0

    def test_discount_when_coupon_below_yield(self) -> None:
        assert quant.bond_price(100, 0.04, 0.05, 10, 2) < 100.0

    def test_yield_inverts_price(self) -> None:
        price = quant.bond_price(100, 0.05, 0.05, 10, 2)
        assert quant.bond_yield(price, 100, 0.05, 10, 2) == pytest.approx(0.05, abs=1e-4)

    def test_modified_duration_sign_and_magnitude(self) -> None:
        # Positive, and shorter than maturity (here ~7.8 < 10).
        d = quant.bond_duration(100, 0.05, 0.05, 10, 2)
        assert 0 < d < 10

    def test_convexity_positive(self) -> None:
        assert quant.bond_convexity(100, 0.05, 0.05, 10, 2) > 0

    def test_unknown_frequency_raises(self) -> None:
        with pytest.raises(ValueError):
            quant.bond_price(100, 0.05, 0.05, 10, 3)

    def test_non_positive_years_raises(self) -> None:
        with pytest.raises(ValueError):
            quant.bond_price(100, 0.05, 0.05, 0, 2)


class TestConventions:
    def test_year_fraction_act_360(self) -> None:
        # 2026-01-01 -> 2026-07-01 is 181 days; ACT/360 = 181/360.
        yf = quant.year_fraction(date(2026, 1, 1), date(2026, 7, 1), "ACT/360")
        assert yf == pytest.approx(181 / 360, abs=1e-9)

    def test_year_fraction_30_360(self) -> None:
        # Exactly half a year under 30/360.
        yf = quant.year_fraction(date(2026, 1, 1), date(2026, 7, 1), "30/360")
        assert yf == pytest.approx(0.5, abs=1e-9)

    def test_year_fraction_case_insensitive(self) -> None:
        a = quant.year_fraction(date(2026, 1, 1), date(2026, 7, 1), "act/360")
        b = quant.year_fraction(date(2026, 1, 1), date(2026, 7, 1), "ACT/360")
        assert a == b

    def test_unknown_convention_raises(self) -> None:
        with pytest.raises(ValueError):
            quant.year_fraction(date(2026, 1, 1), date(2026, 7, 1), "NOPE/999")

    def test_day_count_conventions_nonempty(self) -> None:
        conv = quant.day_count_conventions()
        assert len(conv) > 0
        assert "ACT/360" in conv

    def test_discount_factor(self) -> None:
        assert quant.discount_factor(0.05, 1) == pytest.approx(math.exp(-0.05), abs=1e-12)

    def test_present_value(self) -> None:
        assert quant.present_value(100, 0.05, 1) == pytest.approx(100 * math.exp(-0.05), abs=1e-9)


class TestCarry:
    def test_implied_carry_rate(self) -> None:
        assert quant.implied_carry_rate(4000, 4050, 0.25) == pytest.approx(math.log(4050 / 4000) / 0.25)
        assert quant.implied_carry_rate(4000, 4050, 0.25) == pytest.approx(0.04969, abs=1e-5)

    def test_backwardation_is_negative(self) -> None:
        assert quant.implied_carry_rate(100, 99, 1) < 0

    def test_carry_round_trips_forward_price(self) -> None:
        # forward = spot * exp(rate * ttm) inverts implied_carry_rate.
        rate = quant.implied_carry_rate(100, 103, 0.5)
        assert 100 * math.exp(rate * 0.5) == pytest.approx(103)

    def test_calendar_spread_rate(self) -> None:
        assert quant.calendar_spread_rate(4050, 4110, 0.25, 0.5) == pytest.approx(0.058825, abs=1e-6)

    def test_calendar_legs_compose(self) -> None:
        # The spot->near and near->far legs average to the spot->far rate, weighted by time.
        s, f1, f2 = 100.0, 101.0, 103.0
        r1 = quant.implied_carry_rate(s, f1, 0.25)
        r12 = quant.calendar_spread_rate(f1, f2, 0.25, 1.0)
        assert (r1 * 0.25 + r12 * 0.75) == pytest.approx(quant.implied_carry_rate(s, f2, 1.0))

    def test_calendar_spread_zero_near_is_spot(self) -> None:
        assert quant.calendar_spread_rate(100, 105, 0, 1) == pytest.approx(quant.implied_carry_rate(100, 105, 1))

    def test_box_spread_rate(self) -> None:
        assert quant.box_spread_rate(989, 5000, 6000, 0.25) == pytest.approx(0.044244, abs=1e-6)

    def test_box_priced_by_black_scholes_recovers_rate(self) -> None:
        # Under BS, call(lo) - call(hi) + put(hi) - put(lo) = (hi - lo) * exp(-r t).
        args = {"spot": 100.0, "rate": 0.045, "vol": 0.3, "ttm": 0.5}
        legs = (
            quant.bs_price(strike=90, opt_type="call", **args)
            - quant.bs_price(strike=110, opt_type="call", **args)
            + quant.bs_price(strike=110, opt_type="put", **args)
            - quant.bs_price(strike=90, opt_type="put", **args)
        )
        assert quant.box_spread_rate(legs, 90, 110, 0.5) == pytest.approx(0.045, abs=1e-9)

    def test_tbill_rate(self) -> None:
        assert quant.tbill_rate(0.0412, 91) == pytest.approx(0.041991, abs=1e-6)

    def test_tbill_rate_exceeds_discount_quote(self) -> None:
        assert quant.tbill_rate(0.04, 182) > 0.04

    def test_funding_rate_annual(self) -> None:
        assert quant.funding_rate_annual(0.0001, 8) == pytest.approx(0.109495, abs=1e-6)
        assert quant.funding_rate_annual(-0.0001, 1) < 0

    def test_funding_hourly_equals_eight_hourly_compounded(self) -> None:
        hourly = 0.0000125
        eight = (1 + hourly) ** 8 - 1
        assert quant.funding_rate_annual(hourly, 1) == pytest.approx(quant.funding_rate_annual(eight, 8))

    def test_simple_continuous_round_trip(self) -> None:
        assert quant.simple_to_continuous(0.05, 0.5) == pytest.approx(0.049385, abs=1e-6)
        assert quant.continuous_to_simple(0.05, 0.5) == pytest.approx(0.050630, abs=1e-6)
        assert quant.continuous_to_simple(quant.simple_to_continuous(0.07, 2), 2) == pytest.approx(0.07)

    @pytest.mark.parametrize(
        ("fn", "args"),
        [
            (quant.implied_carry_rate, (0, 100, 1)),
            (quant.implied_carry_rate, (100, -1, 1)),
            (quant.implied_carry_rate, (100, 101, 0)),
            (quant.calendar_spread_rate, (100, 101, 0.5, 0.5)),
            (quant.calendar_spread_rate, (100, 101, -0.1, 0.5)),
            (quant.box_spread_rate, (989, 6000, 5000, 0.25)),
            (quant.box_spread_rate, (0, 5000, 6000, 0.25)),
            (quant.tbill_rate, (0.04, 0)),
            (quant.tbill_rate, (4.0, 91)),
            (quant.funding_rate_annual, (0.0001, 0)),
            (quant.funding_rate_annual, (-1.0, 8)),
            (quant.simple_to_continuous, (-3.0, 0.5)),
            (quant.continuous_to_simple, (0.05, 0)),
        ],
    )
    def test_invalid_inputs_raise(self, fn: object, args: tuple[float, ...]) -> None:
        with pytest.raises(ValueError):
            fn(*args)  # type: ignore[operator]
