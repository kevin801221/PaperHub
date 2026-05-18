"""Papers REST surface (SRS v2.3, FR-08). Backs the deterministic UI
gestures; the Research Agent uses research_tools dispatchers instead."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paperhub.agents.research_tools import _to_fts5_query
from paperhub.config import load_settings
from paperhub.db.connection import open_db
from paperhub.pipelines.paper_pipeline import IngestRequest, PaperPipeline
from paperhub.rag.chroma import ChromaStore

router = APIRouter(prefix="/papers", tags=["papers"])


class IngestBody(BaseModel):
    session_id: int
    arxiv_id: str


class IngestResponse(BaseModel):
    paper_content_id: int
    papers_id: int
    cache_hit: bool
    title: str


class FromLibraryBody(BaseModel):
    session_id: int
    paper_content_id: int


class PatchBody(BaseModel):
    enabled: bool


class LibraryItem(BaseModel):
    paper_content_id: int
    arxiv_id: str | None
    title: str
    abstract: str | None
    year: int | None


@router.post("", response_model=IngestResponse, status_code=201)
async def ingest_paper(body: IngestBody, request: Request) -> IngestResponse:
    """Ingest a paper from arXiv. Cache-aware: second call with the same
    arxiv_id returns cache_hit=True immediately."""
    settings = load_settings()
    chroma = getattr(request.app.state, "chroma", None) or ChromaStore(
        settings.chroma_dir
    )
    async with open_db(settings.db_path) as conn:
        pipeline = PaperPipeline(
            conn,
            papers_cache_dir=settings.papers_cache_dir,
            chroma=chroma,
        )
        result = await pipeline.ingest(
            IngestRequest(session_id=body.session_id, arxiv_id=body.arxiv_id)
        )
    return IngestResponse(
        paper_content_id=result.paper_content_id,
        papers_id=result.papers_id,
        cache_hit=result.cache_hit,
        title=result.title,
    )


@router.get("/library", response_model=list[LibraryItem])
async def list_library(
    session_id: int = Query(...),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LibraryItem]:
    """Indexed paper_content rows NOT already in `session_id`.

    Optional `q` filters on title and abstract using FTS5 MATCH — supports
    multi-word queries with Google-style AND semantics.
    """
    where = ["pc.id NOT IN (SELECT paper_content_id FROM papers WHERE session_id = ?)"]
    args: list[int | str] = [session_id]
    if q:
        fts_query = _to_fts5_query(q)
        if fts_query:
            where.append(
                "EXISTS (SELECT 1 FROM paper_content_fts fts "
                "WHERE fts.rowid = pc.id AND paper_content_fts MATCH ?)"
            )
            args.append(fts_query)
    sql = (
        "SELECT pc.id, pc.arxiv_id, pc.title, pc.abstract, pc.year "
        f"FROM paper_content pc WHERE {' AND '.join(where)} "
        "ORDER BY pc.year DESC NULLS LAST, pc.id DESC "
        "LIMIT ? OFFSET ?"
    )
    args.extend([limit, offset])
    settings = load_settings()
    async with open_db(settings.db_path) as conn, conn.execute(sql, args) as cur:
        rows = await cur.fetchall()
    return [
        LibraryItem(
            paper_content_id=int(r[0]),
            arxiv_id=r[1],
            title=r[2] or "",
            abstract=r[3],
            year=int(r[4]) if r[4] is not None else None,
        )
        for r in rows
    ]


@router.post("/from-library", response_model=IngestResponse)
async def attach_from_library(body: FromLibraryBody) -> IngestResponse:
    """Idempotent on UNIQUE(session_id, paper_content_id). Re-attach returns
    the existing `papers` row instead of erroring."""
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        # Confirm paper_content exists.
        async with conn.execute(
            "SELECT title FROM paper_content WHERE id = ?",
            (body.paper_content_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(
                404, f"paper_content {body.paper_content_id} not found"
            )
        title = row[0] or ""
        await conn.execute(
            "INSERT OR IGNORE INTO papers (session_id, paper_content_id) VALUES (?, ?)",
            (body.session_id, body.paper_content_id),
        )
        await conn.commit()
        async with conn.execute(
            "SELECT id FROM papers WHERE session_id = ? AND paper_content_id = ?",
            (body.session_id, body.paper_content_id),
        ) as cur:
            papers_row = await cur.fetchone()
        assert papers_row is not None
    return IngestResponse(
        paper_content_id=body.paper_content_id,
        papers_id=int(papers_row[0]),
        cache_hit=True,
        title=title,
    )


@router.patch("/{papers_id}", response_model=dict[str, bool])
async def toggle_enabled(papers_id: int, body: PatchBody) -> dict[str, bool]:
    """Toggle the `enabled` flag on a session↔paper membership row."""
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        cur = await conn.execute(
            "UPDATE papers SET enabled = ? WHERE id = ?",
            (1 if body.enabled else 0, papers_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"papers row {papers_id} not found")
        await conn.commit()
    return {"enabled": body.enabled}


@router.delete("/{papers_id}", status_code=204)
async def remove_from_session(papers_id: int) -> None:
    """Removes the membership row only — `paper_content` (and its chunks +
    Chroma vectors + cached on-disk artefacts) are untouched, so re-attaching
    later is a cache hit."""
    settings = load_settings()
    async with open_db(settings.db_path) as conn:
        cur = await conn.execute("DELETE FROM papers WHERE id = ?", (papers_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, f"papers row {papers_id} not found")
        await conn.commit()


@router.get("/content/{paper_content_id}/html")
async def serve_html(paper_content_id: int) -> FileResponse:
    """Served as a file to keep the Citation Canvas in Plan D simple
    (just point an iframe / fetch at this URL)."""
    settings = load_settings()
    async with (
        open_db(settings.db_path) as conn,
        conn.execute(
            "SELECT html_path FROM paper_content WHERE id = ?",
            (paper_content_id,),
        ) as cur,
    ):
        row = await cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(404, f"no html for paper_content {paper_content_id}")
    path = Path(row[0])
    # Sync stat is acceptable here: Plan D Citation Canvas serves cached on-disk HTML.
    # Wrapping in asyncio.to_thread is deferred (same scope decision as paper_pipeline.py).
    if not path.is_file():  # noqa: ASYNC240
        raise HTTPException(410, f"html_path on disk missing: {path}")
    return FileResponse(path, media_type="text/html")


# Re-export Pydantic models for test introspection (kept here for locality).
__all__ = [
    "router",
    "IngestBody",
    "IngestResponse",
    "FromLibraryBody",
    "PatchBody",
    "LibraryItem",
]
