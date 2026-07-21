# /// script
# requires-python = ">=3.13"
# dependencies = [
#     # Floored at 0.16.0: this worker exposes a browsable Table, and the
#     # released signed vgi community extension expects the current
#     # table-contents RPC schema (required_filters); 0.14.x fails ATTACH with an
#     # out-of-date Arrow schema. Keep in sync with pyproject.toml.
#     "vgi-python[http]>=0.16.0",
#     "QuantLib>=1.42",
#     "pyarrow",
# ]
# ///
"""Repo-root stdio entry point for the vgi-quant worker.

DuckDB (and the CI integration suite) spawn this script directly via ``uv run``::

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'quant' (TYPE vgi, LOCATION 'uv run quant_worker.py');

    SELECT quant.bs_price(100, 100, 0.05, 0.2, 1, 'call');   -- ~10.45
    SELECT quant.bond_price(100, 0.05, 0.05, 10, 2);         -- ~100 (par)
    SELECT * FROM quant.day_count_conventions();

The catalog assembly and the ``QuantWorker`` class live in
:mod:`vgi_quant.worker` so they ship inside the installed wheel and can be served
by the ``vgi-quant-worker`` console script and ``vgi-serve
vgi_quant.worker:QuantWorker`` (the paths the Docker image uses). This file is a
thin shim that re-exports them for the PEP 723 ``uv run`` entry point.
"""

from __future__ import annotations

from vgi_quant.worker import QuantWorker, main

__all__ = ["QuantWorker", "main"]


if __name__ == "__main__":
    main()
