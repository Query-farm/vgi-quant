"""Set-returning discovery table function for the quant worker.

``day_count_conventions`` expands to one row per supported convention string, so
it is exposed as a **table function** -- the form that accepts DuckDB
``name := value`` arguments (it takes none, but the table-function shape is the
right home for a set-returning result). The per-row, single-value quant
functions are *scalars* and live in :mod:`vgi_quant.scalars`.

    SELECT * FROM quant.day_count_conventions() ORDER BY name;
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

import pyarrow as pa
from vgi.catalog import Table
from vgi.table_function import (
    BindParams,
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from . import quant
from .meta import object_tags
from .schema_utils import field


@dataclass(kw_only=True)
class _NoArgs:
    """A discovery table function that takes no arguments."""


_CONVENTIONS_SCHEMA = pa.schema(
    [field("name", pa.string(), "A day-count convention string year_fraction() accepts.", nullable=False)]
)


@init_single_worker
@bind_fixed_schema
class DayCountConventionsFunction(TableFunctionGenerator[_NoArgs]):
    """The day-count convention strings ``year_fraction`` accepts, one per row.

    Each ``name`` is a value you can pass as the trailing ``convention`` argument
    to ``year_fraction(start, end, convention)``.
    """

    FIXED_SCHEMA: ClassVar[pa.Schema] = _CONVENTIONS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "day_count_conventions"
        description = "Every day-count convention string year_fraction() supports"
        categories = ["quant", "conventions"]
        tags = {
            **object_tags(
                category="conventions",
                title="Day-Count Conventions Catalog",
                doc_llm=(
                    "## day_count_conventions\n\n"
                    "A discovery **table function** listing every day-count "
                    "convention string accepted by `year_fraction`, one per "
                    "row.\n\n"
                    "**Signature:** `day_count_conventions()` -- takes no "
                    "arguments and returns a single `name` column.\n\n"
                    "Use it to discover the valid `convention` literals before "
                    "calling `quant.year_fraction(start, end, convention)`. Each "
                    "returned `name` (e.g. `ACT/360`, `30/360`) is a value you "
                    "can pass directly as that trailing argument."
                ),
                doc_md=(
                    "# Day-Count Conventions Catalog\n\n"
                    "Lists the day-count convention strings `year_fraction` "
                    "accepts, one per row.\n\n"
                    "## Usage\n\n"
                    "Scan the object (it takes no arguments) to enumerate the "
                    "accepted `convention` literals, then pass any returned "
                    "`name` as the trailing `convention` argument to "
                    "`year_fraction`. The object's example queries give "
                    "ready-to-run listings.\n\n"
                    "## Notes\n\n"
                    "- Set-returning table function (takes no arguments).\n"
                    "- Each `name` is valid as the `convention` argument to "
                    "`year_fraction`."
                ),
                keywords=[
                    "day count",
                    "conventions",
                    "discovery",
                    "list conventions",
                    "act/360",
                    "30/360",
                    "year fraction",
                    "day_count_conventions",
                ],
                examples=[
                    (
                        "List every supported day-count convention name, alphabetically.",
                        "SELECT name FROM quant.main.day_count_conventions() ORDER BY name",
                    ),
                    (
                        "Count how many day-count conventions the worker supports.",
                        "SELECT count(*) AS n FROM quant.main.day_count_conventions()",
                    ),
                ],
            ),
            # VGI414: the retired free-form vgi.result_columns_md is migrated to
            # the structured vgi.result_columns_schema (JSON array of
            # {name, type, description}). It matches the backing table's `name`
            # column (VGI324).
            "vgi.result_columns_schema": json.dumps(
                [
                    {
                        "name": "name",
                        "type": "VARCHAR",
                        "description": (
                            "A day-count convention string accepted as the trailing `convention` "
                            "argument to year_fraction(start, end, convention)."
                        ),
                    }
                ]
            ),
        }

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimated and maximum row count for the planner."""
        return TableCardinality(estimate=8, max=64)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit the discovery rows for this invocation."""
        out.emit(
            pa.RecordBatch.from_pydict(
                {"name": quant.day_count_conventions()},
                schema=params.output_schema,
            )
        )
        out.finish()


TABLE_FUNCTIONS: list[type] = [
    DayCountConventionsFunction,
]

# VGI311: a parameterless table function always yields the same rows, so it
# should also be reachable as a regular table — `SELECT * FROM
# quant.day_count_conventions` (no parentheses). This function-backed Table
# scans the same generator above; the parenthesized function form stays
# available too. It carries its own full discovery metadata (the rules treat a
# table as a first-class object).
DAY_COUNT_CONVENTIONS_TABLE = Table(
    name="day_count_conventions",
    function=DayCountConventionsFunction,
    comment="The day-count convention strings year_fraction() accepts, one per row",
    not_null=("name",),
    primary_key=(("name",),),
    tags={
        **object_tags(
            category="conventions",
            title="Day-Count Conventions Reference Table",
            doc_llm=(
                "## day_count_conventions (table)\n\n"
                "A reference **table** of every day-count convention string "
                "accepted by `year_fraction`, one per row, with a single `name` "
                "column.\n\n"
                "Scan it (no parentheses) to discover the valid `convention` "
                "literals before calling `year_fraction`. Each `name` (e.g. "
                "`ACT/360`, `30/360`) is a value you can pass directly as the "
                "trailing `convention` argument. The identical rows are also "
                "reachable via the `day_count_conventions` table function. The "
                "table's example queries give ready-to-run listings."
            ),
            doc_md=(
                "# Day-Count Conventions Reference Table\n\n"
                "Lists the day-count convention strings `year_fraction` accepts, "
                "one per row.\n\n"
                "## Usage\n\n"
                "Scan the table (no parentheses) to enumerate the accepted "
                "`convention` literals, then pass any returned `name` as the "
                "trailing `convention` argument to `year_fraction`. The table's "
                "example queries give ready-to-run listings.\n\n"
                "## Notes\n\n"
                "- One row per supported convention; `name` is the primary key.\n"
                "- Each `name` is valid as the `convention` argument to "
                "`year_fraction`."
            ),
            keywords=[
                "day count",
                "conventions",
                "discovery",
                "list conventions",
                "act/360",
                "30/360",
                "year fraction",
                "day_count_conventions",
            ],
        ),
        # VGI123 classifying tags use BARE keys (NOT vgi.-namespaced).
        "domain": "finance",
        "category": "quantitative-finance",
        "topic": "day-count-conventions",
        "vgi.example_queries": json.dumps(
            [
                {
                    "description": "List the supported day-count convention names, alphabetically.",
                    "sql": "SELECT name FROM quant.main.day_count_conventions ORDER BY name",
                },
                {
                    "description": "Count how many day-count conventions are supported.",
                    "sql": "SELECT count(*) AS n FROM quant.main.day_count_conventions",
                },
                {
                    "description": "Show only the actual/actual-family conventions.",
                    "sql": "SELECT name FROM quant.main.day_count_conventions WHERE name LIKE 'ACT%' ORDER BY name",
                },
            ]
        ),
        # VGI414: the column is documented by the backing schema's field comment
        # and the table function's vgi.result_columns_schema; the retired
        # free-form vgi.result_columns_md tag is dropped rather than carried.
    },
)

TABLES: list[Table] = [
    DAY_COUNT_CONVENTIONS_TABLE,
]
