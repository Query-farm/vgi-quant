"""Placement and drift checks for the composed example queries.

The composed SQL is defined once in ``vgi_quant.composed_examples``; its rows
are asserted end-to-end in ``test/sql/composed.test``. These checks keep the
three copies in step: the schema-level list, the driving function's first five
examples (all the vgi-lint agent simulator shows), and the SQL test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vgi_quant import composed_examples as ce
from vgi_quant.scalars import (
    BondConvexityFunction,
    BsPriceFunction,
    ImpliedVolFunction,
    PresentValueFunction,
)
from vgi_quant.worker import _QUANT_CATALOG

_SQL_TEST = Path(__file__).resolve().parent.parent / "test" / "sql" / "composed.test"

_DRIVERS = [
    (ce.IV_SKEW_TO_DELTA, ImpliedVolFunction),
    (ce.CALL_BOOK_VALUE, BsPriceFunction),
    (ce.BOND_SHOCK_APPROX, BondConvexityFunction),
    (ce.COUPON_SCHEDULE_PV, PresentValueFunction),
]


def test_every_composed_example_has_a_driver() -> None:
    assert [e for e, _ in _DRIVERS] == ce.COMPOSED_EXAMPLES


@pytest.mark.parametrize(("example", "fn"), _DRIVERS)
def test_on_driving_function_within_first_five(example: tuple[str, str], fn: type) -> None:
    listed = json.loads(fn.Meta.tags["vgi.example_queries"])[:5]
    assert {"description": example[0], "sql": example[1]} in listed


@pytest.mark.parametrize("example", ce.COMPOSED_EXAMPLES)
def test_in_schema_example_queries(example: tuple[str, str]) -> None:
    schema = _QUANT_CATALOG.schemas[0]
    listed = json.loads(schema.tags["vgi.example_queries"])
    assert {"description": example[0], "sql": example[1]} in listed


@pytest.mark.parametrize("example", ce.COMPOSED_EXAMPLES)
def test_rows_pinned_in_sql_suite(example: tuple[str, str]) -> None:
    assert example[1] in _SQL_TEST.read_text()
