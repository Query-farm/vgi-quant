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
