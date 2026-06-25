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


def object_tags(
    *,
    title: str,
    doc_llm: str,
    doc_md: str,
    keywords: list[str],
) -> dict[str, str]:
    """Build the four standard per-object discovery/description tags.

    Args:
        title: Human-friendly display name (VGI124); must add a word over the
            machine name so it does not normalize-equal it (VGI125).
        doc_llm: Markdown narrative for an LLM/agent audience (VGI112).
        doc_md: Markdown narrative for human docs (VGI113); distinct from
            ``doc_llm``.
        keywords: Search terms / synonyms (VGI126), serialized as a JSON array
            of strings (VGI138).

    Returns:
        A tag dict suitable for spreading into a function's ``Meta.tags``.
    """
    return {
        "vgi.title": title,
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.keywords": json.dumps(keywords),
    }
