"""Integration test for the day_count_conventions discovery table function.

Drives the function through the real bind -> init -> process lifecycle
in-process (no worker subprocess). The per-row functions are *scalars* and are
covered in ``test_scalars.py``.
"""

from __future__ import annotations

from vgi_quant.tables import DayCountConventionsFunction

from .harness import invoke_table_function


class TestDayCountConventions:
    def test_columns_and_nonempty(self) -> None:
        table = invoke_table_function(DayCountConventionsFunction)
        assert table.column_names == ["name"]
        assert table.num_rows > 0

    def test_known_conventions_present(self) -> None:
        table = invoke_table_function(DayCountConventionsFunction)
        names = table.column("name").to_pylist()
        assert "ACT/360" in names
        assert "ACT/365" in names
        assert "30/360" in names
        assert "ACT/ACT" in names
