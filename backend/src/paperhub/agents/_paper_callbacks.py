"""Per-paper callback helpers (list_sections / read_section / read_figure_block)
that are shared across F4.5's gather_context subagent and any other agent flow
that needs to read into a paper's structured asset.

Extracted from R1's sl_paper_brief.py in Phase 6 (F4.5) so the R1 file can be
deleted in Phase 14 without taking these helpers with it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from paperhub.pipelines.paper_asset import PaperAsset

__all__ = [
    "_read_section",
    "_resolve_source_dir",
    "_read_figure_block",
]


async def _read_section(
    *,
    paper_content_id: int,
    name: str,
    conn: aiosqlite.Connection,
) -> tuple[str, list[int]]:
    """Return every chunk in ``name`` as ``<chunk id="N">…</chunk>`` blocks
    + the list of chunk ids returned.
    """
    async with conn.execute(
        "SELECT id, text, section, page FROM chunks "
        "WHERE paper_content_id = ? AND section = ? "
        "ORDER BY char_start",
        (paper_content_id, name),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return (
            json.dumps({
                "error": f"unknown section: {name!r}. Call list_sections() first.",
            }),
            [],
        )
    chunk_ids: list[int] = []
    blocks: list[str] = []
    for cid, text, _section, page in rows:
        chunk_ids.append(int(cid))
        body = f'<chunk id="{int(cid)}">\n{text}\n</chunk>'
        if page is not None:
            body += f" (p.{int(page)})"
        blocks.append(body)
    return ("\n\n".join(blocks), chunk_ids)


async def _resolve_source_dir(
    *,
    paper_content_id: int,
    conn: aiosqlite.Connection,
) -> Path | None:
    """Return the paper's ``source_dir_path`` as a ``Path``, or ``None`` if
    the row is missing / has no source dir."""
    async with conn.execute(
        "SELECT source_dir_path FROM paper_content WHERE id = ?",
        (paper_content_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return None
    return Path(str(row[0]))


async def _read_figure_block(
    *,
    paper_content_id: int,
    figure_key: str,
    asset: PaperAsset | None,
    paper_idx: int,
    conn: aiosqlite.Connection,
) -> str:
    """Return a JSON block with the figure's caption + nearby chunk text.

    ``figure_key`` is a deck-inventory key (``p{idx}-{figure_id}``); we strip
    the ``p{idx}-`` prefix to look up the figure inside this paper's
    PaperAsset. The "nearby paragraph context" is one chunk from the figure's
    section, taken as a usable proxy without requiring per-figure paragraph
    extraction at ingest time.
    """
    if asset is None:
        return json.dumps({"error": "this paper has no PaperAsset (no figures available)"})

    expected_prefix = f"p{paper_idx}-"
    if figure_key.startswith(expected_prefix):
        local_id = figure_key[len(expected_prefix) :]
    else:
        # Tolerate the LLM dropping the deck-prefix when the brief is for a
        # single paper — fall back to a raw id match.
        local_id = figure_key

    match = next((f for f in asset.figures if f.id == local_id), None)
    if match is None:
        valid_keys = [f"{expected_prefix}{f.id}" for f in asset.figures]
        return json.dumps({
            "error": f"unknown figure_key: {figure_key!r}",
            "valid_keys": valid_keys,
        })

    context_chunk: str | None = None
    if match.section:
        async with conn.execute(
            "SELECT text FROM chunks "
            "WHERE paper_content_id = ? AND section = ? "
            "ORDER BY char_start LIMIT 1",
            (paper_content_id, match.section),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            context_chunk = str(row[0])

    payload: dict[str, Any] = {
        "figure_key": figure_key,
        "caption": match.caption,
        "page": match.page,
        "section": match.section,
    }
    if context_chunk is not None:
        payload["context"] = context_chunk
    return json.dumps(payload, ensure_ascii=False)
