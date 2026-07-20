"""Shared helpers for the per-object discovery/description metadata.

The ``vgi-lint`` strict profile (0.26.0) expects these on **every** function and
table. Each function/table surfaces them in its ``Meta.tags``:

- ``vgi.title`` (VGI124)         -- human-friendly display name. Must NOT
  normalize-equal the machine name (lowercase + strip non-alphanumerics), so we
  always add an extra descriptive word (VGI125).
- ``vgi.doc_llm`` (VGI112)       -- a Markdown narrative aimed at an LLM/agent
  audience (what it does, when to use it, inputs/outputs, edge cases).
- ``vgi.doc_md`` (VGI113)        -- a Markdown narrative aimed at human docs
  (overview + usage + notes). Distinct content from ``vgi.doc_llm``.
- ``vgi.keywords`` (VGI126)      -- a JSON array of search terms / synonyms.

Per-object ``vgi.source_url`` is intentionally NOT emitted here: the linter
(VGI139) treats per-object source links as redundant and wants ``source_url``
only on the catalog object, which ``quant_worker.py`` already sets.
"""

from __future__ import annotations

import json


def example_queries(examples: list[tuple[str, str]]) -> str:
    """Serialize ``(description, sql)`` pairs into a ``vgi.example_queries`` value.

    VGI515 requires every schema- and function-level example to carry a
    non-empty description. The signed ``vgi`` community extension surfaces a
    function's native ``Meta.examples`` as a bare ``VARCHAR[]`` of SQL strings —
    the per-example descriptions are dropped on the wire — so described examples
    must travel in the ``vgi.example_queries`` tag instead, which is a JSON list
    of ``{"description", "sql"}`` objects.

    Args:
        examples: A list of ``(description, sql)`` pairs. Each ``description``
            must be non-empty and each ``sql`` a self-contained, catalog-
            qualified, re-runnable query.

    Returns:
        The JSON string to store under the ``vgi.example_queries`` tag.
    """
    return json.dumps([{"description": d, "sql": s} for d, s in examples])


def object_tags(
    *,
    title: str,
    doc_llm: str,
    doc_md: str,
    keywords: list[str],
    category: str,
    examples: list[tuple[str, str]] | None = None,
) -> dict[str, str]:
    """Build the standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (VGI124); must add a word over the
            machine name so it does not normalize-equal it (VGI125).
        doc_llm: Markdown narrative for an LLM/agent audience (VGI112).
        doc_md: Markdown narrative for human docs (VGI113); distinct from
            ``doc_llm``.
        keywords: Search terms / synonyms (VGI126), serialized as a JSON array
            of strings (VGI138).
        category: The primary ``vgi.category`` (VGI409/VGI411) — one of the
            names declared in the schema's ``vgi.categories`` registry
            (``options`` | ``bonds`` | ``conventions``).
        examples: Optional ``(description, sql)`` pairs surfaced as a described
            ``vgi.example_queries`` tag (VGI515). Prefer this over the native
            ``Meta.examples`` carrier, whose descriptions the extension drops.

    Returns:
        A tag dict suitable for spreading into a function's ``Meta.tags``.
    """
    tags = {
        "vgi.title": title,
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.keywords": json.dumps(keywords),
        "vgi.category": category,
    }
    if examples:
        tags["vgi.example_queries"] = example_queries(examples)
    return tags
