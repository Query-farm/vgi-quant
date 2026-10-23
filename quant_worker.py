# /// script
# requires-python = ">=3.13"
# dependencies = [
#     # Floored at 0.46.1: the released signed vgi community extension speaks
#     # VGI protocol 2.x; older vgi-python lines fail ATTACH with a
#     # protocol_version mismatch. Keep in sync with pyproject.toml.
#     "vgi-python[http]>=0.46.1",
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
