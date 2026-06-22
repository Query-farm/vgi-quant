"""End-to-end tests for the per-row scalar quant functions.

These spawn ``quant_worker.py`` as a subprocess via ``vgi.client.Client`` and
call each scalar exactly as DuckDB would after ``ATTACH``. The per-row numeric
columns travel in the input batch (``Param``); the constant trailing arguments
(``opt_type`` / ``freq`` / ``convention``) go in ``positional``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest
from vgi import Arguments
from vgi.client import Client, ClientError

_WORKER = str(Path(__file__).resolve().parent.parent / "quant_worker.py")


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    # Current interpreter (deps already installed) + worker_limit=1 so output
    # order matches input order for deterministic per-row assertions.
    with Client(f"{sys.executable} {_WORKER}", worker_limit=1) as c:
        yield c


def _call(
    client: Client,
    name: str,
    columns: dict[str, tuple[pa.DataType, list]],
    *,
    positional: list[pa.Scalar] | None = None,
) -> list:
    batch = pa.RecordBatch.from_pydict({k: pa.array(v, type=t) for k, (t, v) in columns.items()})
    results = list(
        client.scalar_function(
            function_name=name,
            input=iter([batch]),
            arguments=Arguments(positional=positional or []),
        )
    )
    return results[0]["result"].to_pylist()


def _f64cols(**cols: list) -> dict[str, tuple[pa.DataType, list]]:
    return {k: (pa.float64(), v) for k, v in cols.items()}


class TestOptions:
    def test_bs_price_textbook(self, client: Client) -> None:
        out = _call(
            client,
            "bs_price",
            _f64cols(spot=[100.0], strike=[100.0], rate=[0.05], vol=[0.2], ttm=[1.0]),
            positional=[pa.scalar("call")],
        )
        assert out[0] == pytest.approx(10.4506, abs=1e-3)

    def test_bs_delta(self, client: Client) -> None:
        out = _call(
            client,
            "bs_delta",
            _f64cols(spot=[100.0], strike=[100.0], rate=[0.05], vol=[0.2], ttm=[1.0]),
            positional=[pa.scalar("call")],
        )
        assert out[0] == pytest.approx(0.6368, abs=1e-3)

    def test_null_passthrough(self, client: Client) -> None:
        out = _call(
            client,
            "bs_price",
            _f64cols(
                spot=[100.0, None], strike=[100.0, 100.0], rate=[0.05, 0.05], vol=[0.2, 0.2], ttm=[1.0, 1.0]
            ),
            positional=[pa.scalar("call")],
        )
        assert out[1] is None

    def test_implied_vol_round_trip(self, client: Client) -> None:
        out = _call(
            client,
            "implied_vol",
            _f64cols(price=[10.4506], spot=[100.0], strike=[100.0], rate=[0.05], ttm=[1.0]),
            positional=[pa.scalar("call")],
        )
        assert out[0] == pytest.approx(0.20, abs=1e-3)

    def test_bad_opt_type_errors(self, client: Client) -> None:
        with pytest.raises(ClientError):
            _call(
                client,
                "bs_price",
                _f64cols(spot=[100.0], strike=[100.0], rate=[0.05], vol=[0.2], ttm=[1.0]),
                positional=[pa.scalar("nope")],
            )

    def test_zero_ttm_errors(self, client: Client) -> None:
        with pytest.raises(ClientError):
            _call(
                client,
                "bs_price",
                _f64cols(spot=[100.0], strike=[100.0], rate=[0.05], vol=[0.2], ttm=[0.0]),
                positional=[pa.scalar("call")],
            )


class TestBonds:
    def test_par_bond(self, client: Client) -> None:
        out = _call(
            client,
            "bond_price",
            _f64cols(face=[100.0], coupon=[0.05], ytm=[0.05], years=[10.0]),
            positional=[pa.scalar(2, type=pa.int64())],
        )
        assert out[0] == pytest.approx(100.0, abs=1e-2)

    def test_bond_yield_inverts(self, client: Client) -> None:
        out = _call(
            client,
            "bond_yield",
            _f64cols(price=[100.0], face=[100.0], coupon=[0.05], years=[10.0]),
            positional=[pa.scalar(2, type=pa.int64())],
        )
        assert out[0] == pytest.approx(0.05, abs=1e-4)

    def test_duration_and_convexity_positive(self, client: Client) -> None:
        dur = _call(
            client,
            "bond_duration",
            _f64cols(face=[100.0], coupon=[0.05], ytm=[0.05], years=[10.0]),
            positional=[pa.scalar(2, type=pa.int64())],
        )
        conv = _call(
            client,
            "bond_convexity",
            _f64cols(face=[100.0], coupon=[0.05], ytm=[0.05], years=[10.0]),
            positional=[pa.scalar(2, type=pa.int64())],
        )
        assert 0 < dur[0] < 10
        assert conv[0] > 0


class TestConventions:
    def test_year_fraction_act_360(self, client: Client) -> None:
        out = _call(
            client,
            "year_fraction",
            {
                "start": (pa.date32(), [date(2026, 1, 1)]),
                "end": (pa.date32(), [date(2026, 7, 1)]),
            },
            positional=[pa.scalar("ACT/360")],
        )
        assert out[0] == pytest.approx(181 / 360, abs=1e-9)

    def test_unknown_convention_errors(self, client: Client) -> None:
        with pytest.raises(ClientError):
            _call(
                client,
                "year_fraction",
                {
                    "start": (pa.date32(), [date(2026, 1, 1)]),
                    "end": (pa.date32(), [date(2026, 7, 1)]),
                },
                positional=[pa.scalar("NOPE/999")],
            )

    def test_discount_factor(self, client: Client) -> None:
        import math

        out = _call(client, "discount_factor", _f64cols(rate=[0.05], ttm=[1.0]))
        assert out[0] == pytest.approx(math.exp(-0.05), abs=1e-9)

    def test_present_value(self, client: Client) -> None:
        import math

        out = _call(client, "present_value", _f64cols(amount=[100.0], rate=[0.05], ttm=[1.0]))
        assert out[0] == pytest.approx(100 * math.exp(-0.05), abs=1e-6)
