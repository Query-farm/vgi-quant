"""Set-returning discovery table function for the quant worker.

``day_count_conventions`` expands to one row per supported convention string, so
it is exposed as a **table function** -- the form that accepts DuckDB
``name := value`` arguments (it takes none, but the table-function shape is the
right home for a set-returning result). The per-row, single-value quant
functions are *scalars* and live in :mod:`vgi_quant.scalars`.

    SELECT * FROM quant.day_count_conventions() ORDER BY name;
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pyarrow as pa
from vgi.metadata import FunctionExample
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
                    "accepts.\n\n"
                    "## Usage\n\n"
                    "```sql\n"
                    "SELECT * FROM quant.day_count_conventions() ORDER BY name;\n"
                    "```\n\n"
                    "## Notes\n\n"
                    "- Set-returning table function (takes no arguments).\n"
                    "- Each `name` is valid as the `convention` argument to "
                    "`year_fraction`."
                ),
                keywords=(
                    "day count, conventions, discovery, list conventions, act/360, 30/360, "
                    "year fraction, day_count_conventions"
                ),
                relative_path="vgi_quant/tables.py",
            ),
            "vgi.result_columns_md": (
                "| column | type | description |\n"
                "| --- | --- | --- |\n"
                "| `name` | VARCHAR | A day-count convention string accepted as the trailing "
                "`convention` argument to `year_fraction(start, end, convention)`. |\n"
            ),
        }
        examples = [
            FunctionExample(
                sql="SELECT count(*) FROM quant.day_count_conventions()",
                description="How many day-count conventions are supported",
            ),
            FunctionExample(
                sql="SELECT * FROM quant.day_count_conventions() ORDER BY name",
                description="List the supported day-count conventions",
            ),
        ]

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
