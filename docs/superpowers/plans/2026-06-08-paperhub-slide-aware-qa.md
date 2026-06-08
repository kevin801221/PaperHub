# Slide-aware QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer a question about the on-screen slide ("explain this graph") with a grounded `[chunk:N]`-cited answer, never mutating the deck — fixing the two-layer misclassification in the session-244 trace. The on-screen slide is surfaced as a deterministic, toggleable composer **context chip** so the backend never has to *guess* whether a turn references the current slide.

**Architecture:** A composer **chip** (eye / eye-blind, sticky per session, content tracks the active slide) sends a deterministic `slide_attached` flag. When attached, the backend builds an **active-slide context block** that anchors the existing `paper_qa` subgraph's retrieval and deterministically scopes single-slide edits to the current page. The LLM keeps only the job it is reliable at — telling a *question* from a *command*; it no longer guesses the slide deixis. Two entry points feed the QA flow: the **router** ("deck question → `paper_qa`") and a deck-command **`action="qa"`** guard (`sl_qa` node delegating to `paper_qa`). The `report_graph._route` default-to-`edit_slides` fallback (which silently rewrote the slide in run 412) is removed.

**Tech Stack:** Backend — Python 3.11, `uv`, pytest-asyncio, LangGraph, aiosqlite, Pydantic (`uv run pytest -v`, `uv run ruff check src tests`, `uv run mypy src`, from `backend/`). Frontend — React + TypeScript + Zustand, Vitest + RTL (`npm test`, `npm run typecheck`, `npm run lint`, `npm run build`, from `frontend/`).

**SRS reference:** the "Slide-aware QA" Revision-History entry in [docs/superpowers/specs/2026-05-17-paperhub-srs.md](../specs/2026-05-17-paperhub-srs.md) (incl. the deterministic context-attachment chip refinement).

---

## File Structure

**Backend** (paths relative to `backend/`)

| File | Responsibility | Change |
| --- | --- | --- |
| `src/paperhub/models/domain.py` | `DeckCommand.action` += `"qa"`; `AgentState` += `slide_context`, `slide_attached` | Modify |
| `src/paperhub/agents/slide_context.py` | **NEW** — `build_slide_context()` + `slide_aware_query()` | Create |
| `src/paperhub/agents/research_graph.py` | `_pq_dispatch` / `_pq_finalize` use `slide_aware_query` | Modify |
| `src/paperhub/agents/router.py` | surface `slide_attached` to the classifier | Modify |
| `src/paperhub/llm/prompts/router_v1.yaml` | rule: `slide_attached` question → `paper_qa`, command → `slides` | Modify |
| `src/paperhub/llm/prompts/slides_deck_command_v1.yaml` | `qa` action; `slide_attached` → default scope `current` | Modify |
| `src/paperhub/agents/report_graph.py` | `ReportDeps.answer_slide_question`; `sl_qa` node; module-level `_route_deck_command`; pass `slide_attached` to classifier | Modify |
| `src/paperhub/agents/report_pipeline.py` | `classify_deck_command` takes `slide_attached` | Modify |
| `src/paperhub/api/chat.py` | `ChatRequest.slide_attached`; build+gate+thread `slide_context`/`slide_attached`; wire `answer_slide_question` | Modify |

**Frontend** (paths relative to `frontend/`)

| File | Responsibility | Change |
| --- | --- | --- |
| `src/store/slides.ts` | `slideAttachedBySession` + `setSlideAttached` (sticky toggle) | Modify |
| `src/components/chat/SlideContextChip.tsx` | **NEW** — eye/eye-blind chip showing the active slide | Create |
| `src/components/chat/Composer.tsx` | render the chip above the textarea | Modify |
| `src/pages/ChatPage.tsx` | compute chip props from slides store + active session, pass to Composer | Modify |
| `src/hooks/useChatStream.ts` | send `slide_attached` in the `/chat` body | Modify |

---

# Phase 1 — Backend

## Task 1: Models — `qa` action + `slide_context` / `slide_attached` state

**Files:**
- Modify: `src/paperhub/models/domain.py:102-108` (DeckCommand.action), `:142-205` (AgentState)
- Test: `tests/test_slide_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_slide_models.py`:

```python
def test_deck_command_accepts_qa_action() -> None:
    from paperhub.models.domain import DeckCommand
    cmd = DeckCommand(action="qa")
    assert cmd.action == "qa"
    assert cmd.target_scope == "all"  # default unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slide_models.py -k qa_action -v`
Expected: FAIL — `ValidationError` ("Input should be 'generate_notes', …").

- [ ] **Step 3: Write minimal implementation**

In `src/paperhub/models/domain.py`, extend the Literal (lines 102-105):

```python
    action: Literal[
        "generate_notes", "edit_notes", "edit_slides",
        "edit_title", "edit_preamble", "regenerate", "qa",
    ]
```

In `AgentState` (after the `current_view_page` line, ~line 196), add:

```python
    # v2.29 slide-aware QA. slide_attached: the composer chip's eye toggle —
    # deterministic "this turn references the on-screen slide". slide_context:
    # the active-slide block built by agents/slide_context.build_slide_context
    # (None when not attached / no deck → plain paper_qa, no regression).
    slide_attached: bool
    slide_context: str | None
```

- [ ] **Step 4: Run test + types**

Run: `uv run pytest tests/test_slide_models.py -v && uv run mypy src/paperhub/models/domain.py`
Expected: PASS; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/models/domain.py tests/test_slide_models.py
git commit -m "feat(slides): DeckCommand qa action + AgentState slide_context/slide_attached"
```

---

## Task 2: `slide_context.py` — build the active-slide block

**Files:**
- Create: `src/paperhub/agents/slide_context.py`
- Test: `tests/test_slide_context.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_slide_context.py`:

```python
import pytest

from paperhub.agents.slide_context import build_slide_context, slide_aware_query
from paperhub.db.connection import open_db
from paperhub.db.deck_slides import DeckSlideInput, replace_deck_slides
from paperhub.db.decks import get_deck, upsert_deck
from paperhub.db.migrate import apply_schema

pytestmark = pytest.mark.asyncio


async def _seed_deck(conn, *, page_count: int) -> int:
    await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await conn.commit()
    await upsert_deck(
        conn, session_id=1, run_id=None, tex_path="/x/deck.tex", pdf_path=None,
        speaker_notes={}, plan={}, page_count=page_count,
        contributing_paper_ids=[], status="ok",
    )
    deck = await get_deck(conn, session_id=1)
    return deck.id


async def test_no_deck_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.commit()
        assert await build_slide_context(conn, session_id=1, current_view_page=3) is None


async def test_page_zero_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}\\end{frame}",
                           page_start=1, page_end=1)])
        assert await build_slide_context(conn, session_id=1, current_view_page=0) is None


async def test_text_frame_yields_title_and_bullets(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=2)
        frame = (
            "\\begin{frame}{Coarse-to-fine RVQ}\n"
            "  \\begin{itemize}\n"
            "    \\item Action patchifier partitions sequences.\n"
            "    \\item RVQ stabilizes training.\n"
            "  \\end{itemize}\n\\end{frame}"
        )
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex=frame, page_start=1, page_end=1),
            DeckSlideInput(slide_index=1, frame_tex="\\begin{frame}{B}\\end{frame}",
                           page_start=2, page_end=2)])
        ctx = await build_slide_context(conn, session_id=1, current_view_page=1)
        assert ctx is not None
        assert "Coarse-to-fine RVQ" in ctx
        assert "Action patchifier partitions sequences" in ctx
        assert "RVQ stabilizes training" in ctx
        assert "Figure" not in ctx


async def test_page_out_of_range_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}\\end{frame}",
                           page_start=1, page_end=1)])
        assert await build_slide_context(conn, session_id=1, current_view_page=9) is None


async def test_figure_frame_resolves_caption(tmp_path, monkeypatch) -> None:
    from paperhub.pipelines.slide_pipeline.figure_inventory import InventoryFigure
    monkeypatch.setattr(
        "paperhub.agents.slide_context.build_inventory",
        lambda papers: [InventoryFigure(
            key="p0-fig-002", caption="Fig. 2. Coarse-to-fine residual VQ.",
            abs_path="/x/p0-fig-002.png", paper_id=7)],
    )
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        frame = ("\\begin{frame}{FASTerVQ Architecture}\n"
                 "  \\includegraphics[width=\\linewidth]{p0-fig-002}\n\\end{frame}")
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex=frame, page_start=1, page_end=1)])
        ctx = await build_slide_context(conn, session_id=1, current_view_page=1)
        assert ctx is not None
        assert "Fig. 2. Coarse-to-fine residual VQ." in ctx


def test_slide_aware_query_prepends_context_when_present() -> None:
    state = {"user_message": "explain this", "effective_query": "explain this graph",
             "slide_context": "Active slide (page 5) title: Architecture"}
    q = slide_aware_query(state)  # type: ignore[arg-type]
    assert q.startswith("Active slide (page 5) title: Architecture")
    assert "explain this graph" in q


def test_slide_aware_query_passthrough_when_absent() -> None:
    state = {"user_message": "explain this", "effective_query": "explain this graph"}
    assert slide_aware_query(state) == "explain this graph"  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slide_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paperhub.agents.slide_context'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/paperhub/agents/slide_context.py`:

```python
"""Active-slide context for slide-aware QA (SRS v2.29).

When the composer's slide chip is attached, ``build_slide_context`` produces a
compact block that anchors paper_qa's section navigation onto the right part of
the paper. Returns ``None`` (→ plain paper_qa, no regression) whenever there is
no deck / no on-screen page / no matching row. ``slide_aware_query`` prepends
the block to the resolved query for both the subagent and the finalizer.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import aiosqlite

from paperhub.agents.state import AgentState, effective_query
from paperhub.db.deck_slides import get_deck_slides
from paperhub.db.decks import get_deck
from paperhub.pipelines.slide_pipeline.figure_inventory import build_inventory

_FRAMETITLE_RE = re.compile(r"\\frametitle\{([^}]*)\}")
_BEGINFRAME_TITLE_RE = re.compile(r"\\begin\{frame\}\{([^}]*)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_ITEM_RE = re.compile(r"\\item\s+(.+)")


def _frame_title(frame_tex: str) -> str:
    m = _FRAMETITLE_RE.search(frame_tex) or _BEGINFRAME_TITLE_RE.search(frame_tex)
    return (m.group(1).strip() if m else "") or "(untitled slide)"


def _strip_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    s = s.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", s).strip()


def _frame_bullets(frame_tex: str) -> list[str]:
    return [b for b in (_strip_latex(m.group(1)) for m in _ITEM_RE.finditer(frame_tex)) if b]


def _frame_figure_keys(frame_tex: str) -> list[str]:
    return [Path(m.group(1)).stem for m in _GRAPHICS_RE.finditer(frame_tex)]


async def _enabled_paper_keys(
    conn: aiosqlite.Connection, session_id: int
) -> list[dict[str, object]]:
    # Same ordering (added_at) build_inventory used at deck-build time so the
    # p{idx}-{fig.id} keys reverse correctly.
    async with conn.execute(
        "SELECT pc.id, pc.source_dir_path FROM papers p "
        "JOIN paper_content pc ON pc.id = p.paper_content_id "
        "WHERE p.session_id = ? AND p.enabled = 1 ORDER BY p.added_at",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [{"id": r[0], "source_dir": r[1]} for r in rows]


async def build_slide_context(
    conn: aiosqlite.Connection, *, session_id: int, current_view_page: int | None
) -> str | None:
    """Return the active-slide context block, or ``None`` when not applicable.

    Caller gates on the chip's ``slide_attached`` flag BEFORE calling this; this
    function additionally returns None for the no-deck / no-page / no-row cases.
    """
    if current_view_page is None or current_view_page <= 0:
        return None
    deck = await get_deck(conn, session_id=session_id)
    if deck is None:
        return None
    rows = await get_deck_slides(conn, deck_id=deck.id)
    row = next((r for r in rows if r.page_start <= current_view_page <= r.page_end), None)
    if row is None:
        return None

    lines = [
        "The user is currently viewing a slide from a presentation deck "
        "generated from the reference paper(s). Use it to locate and explain "
        "the relevant part of the paper(s) that the slide is based on.",
        f"Active slide (page {current_view_page}) title: {_frame_title(row.frame_tex)}",
    ]
    bullets = _frame_bullets(row.frame_tex)
    if bullets:
        lines.append("Slide bullet points: " + " | ".join(bullets))

    fig_keys = _frame_figure_keys(row.frame_tex)
    if fig_keys:
        papers = await _enabled_paper_keys(conn, session_id)
        inventory = await asyncio.to_thread(build_inventory, papers)
        by_key = {f.key: f.caption for f in inventory}
        captions = [by_key[k] for k in fig_keys if k in by_key]
        if captions:
            lines.append("Figure(s) shown on this slide: " + " || ".join(captions))
    return "\n".join(lines)


def slide_aware_query(state: AgentState) -> str:
    """The QA query: the active-slide context (when present) prepended to the
    router's resolved query, so section navigation targets the right section.
    Falls back to ``effective_query`` when there is no slide context."""
    base = effective_query(state)
    ctx = state.get("slide_context")
    if not ctx:
        return base
    return f"{ctx}\n\nThe user's question: {base}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_slide_context.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/slide_context.py tests/test_slide_context.py
git commit -m "feat(slides): build_slide_context + slide_aware_query retrieval anchor"
```

---

## Task 3: paper_qa consumes the slide-aware query

**Files:**
- Modify: `src/paperhub/agents/research_graph.py` (import; `_pq_dispatch` ~482; `_pq_finalize` ~534)
- Test: `tests/test_research_paper_qa.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_research_paper_qa.py` (uses the file's existing `_StubAdapter`, `_make_session`, `migrated_db`, `fake_tracer`):

```python
async def test_slide_context_reaches_subagent_query(
    migrated_db: aiosqlite.Connection, fake_tracer: Tracer, monkeypatch,
) -> None:
    from paperhub.agents import research_graph as rg
    from paperhub.agents.paper_qa_subagent import PerPaperPicks

    session_id = await _make_session(migrated_db)
    captured: dict[str, str] = {}

    async def _fake_resolve(*_a, **_k):
        return [(15, "FASTerVQ")]

    async def _fake_subagent(*, user_message: str, **_k):
        captured["user_message"] = user_message
        return PerPaperPicks(paper_content_id=15, title="FASTerVQ",
                             picked_chunks=[], rationale="")

    monkeypatch.setattr(rg, "_resolve_enabled_papers", _fake_resolve)
    monkeypatch.setattr(rg, "run_paper_qa_subagent", _fake_subagent)

    deps = rg.ResearchDeps(adapter=_StubAdapter(["ok"]), tracer=fake_tracer,
                           paper_qa_model="m", conn=migrated_db)
    graph = rg.build_paper_qa_subgraph(deps)
    state = {"run_id": fake_tracer._run_id, "branch": "", "session_id": session_id,  # noqa: SLF001
             "user_message": "explain this graph",
             "effective_query": "explain the graph on the current slide",
             "slide_context": "Active slide (page 5) title: FASTerVQ Architecture"}
    async for _ in graph.astream(state, stream_mode=["values"]):
        pass
    assert captured["user_message"].startswith(
        "Active slide (page 5) title: FASTerVQ Architecture")
    assert "explain the graph on the current slide" in captured["user_message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_paper_qa.py -k slide_context_reaches -v`
Expected: FAIL — captured `user_message` is the raw query (no slide context prefix).

- [ ] **Step 3: Write minimal implementation**

In `src/paperhub/agents/research_graph.py`, add after line 72:

```python
from paperhub.agents.slide_context import slide_aware_query
```

In `_pq_dispatch` → `_one_with_emit`, change the subagent `user_message` (line ~482) to `user_message=slide_aware_query(state),`.

In `_pq_finalize`, change the `paper_qa_finalize(... user_message=...)` arg (line ~534) to `user_message=slide_aware_query(state),`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_research_paper_qa.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/research_graph.py tests/test_research_paper_qa.py
git commit -m "feat(slides): paper_qa subagent + finalizer use the slide-aware query"
```

---

## Task 4: `ChatRequest.slide_attached` + build/gate/thread in chat.py

**Files:**
- Modify: `src/paperhub/api/chat.py` (`ChatRequest` ~88-91; imports ~24; initial `state` ~530-535; after router ~558)
- Test: `tests/test_chat_sse.py` (regression) + a focused request-model test

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_sse.py` (or wherever `ChatRequest` is unit-tested):

```python
def test_chat_request_defaults_slide_attached_false() -> None:
    from paperhub.api.chat import ChatRequest
    req = ChatRequest(user_message="hi")
    assert req.slide_attached is False
    req2 = ChatRequest(user_message="hi", slide_attached=True, current_view_page=5)
    assert req2.slide_attached is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_sse.py -k slide_attached -v`
Expected: FAIL — `ValidationError`/`AttributeError` (`slide_attached` not a field).

- [ ] **Step 3: Implement the field + gating**

In `src/paperhub/api/chat.py`, add the import:

```python
from paperhub.agents.slide_context import build_slide_context
```

Add to `ChatRequest` (after `current_view_page: int = 0`, ~line 91):

```python
    slide_attached: bool = False
```

Set `slide_attached` in the initial state (lines 530-535):

```python
            state: AgentState = {
                "run_id": run_id, "branch": "", "session_id": session_id,
                "user_message": req.user_message,
                "history": [h.model_dump() for h in req.history],
                "current_view_page": req.current_view_page,
                "slide_attached": req.slide_attached,
            }
```

After the router runs + its drain loop (after line 558, before `decision = state["routing_decision"]`), build + thread the context, **gated on the chip flag**:

```python
                # Slide-aware QA: build the active-slide context ONLY when the
                # composer chip is attached (deterministic). Both the paper_qa
                # branch and the slides action="qa" guard read state.slide_context.
                state = {
                    **state,
                    "slide_context": (
                        await build_slide_context(
                            conn, session_id=session_id,
                            current_view_page=req.current_view_page,
                        )
                        if req.slide_attached
                        else None
                    ),
                }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_sse.py tests/test_chat_slides_sse.py -v`
Expected: PASS — existing flows unaffected (`slide_attached` defaults False → `slide_context` None).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/api/chat.py tests/test_chat_sse.py
git commit -m "feat(slides): ChatRequest.slide_attached gates + threads active-slide context"
```

---

## Task 5: Router routes deck questions to `paper_qa` (slide_attached signal)

**Files:**
- Modify: `src/paperhub/agents/router.py:39-53`, `src/paperhub/llm/prompts/router_v1.yaml`
- Test: `tests/test_router.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_router.py`:

```python
async def test_router_surfaces_slide_attached_variable(migrated_db, fake_tracer) -> None:
    from paperhub.agents.router import router_node
    captured: dict[str, object] = {}

    class _Cap:
        async def structured(self, *, slot, variables, response_model, model, **__):
            captured.update(variables)
            return response_model(
                intent="paper_qa", model_tier="flagship", confidence=1.0,
                reasoning="x", resolved_query="explain this graph",
                response_language="English")

    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.commit()
    state = {"run_id": fake_tracer._run_id, "branch": "", "session_id": 1,  # noqa: SLF001
             "user_message": "explain this graph", "history": [], "slide_attached": True}
    await router_node(state, adapter=_Cap(), tracer=fake_tracer, model="m",
                      conn=migrated_db)
    assert captured["slide_attached"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router.py -k slide_attached -v`
Expected: FAIL — `KeyError: 'slide_attached'`.

- [ ] **Step 3: Implement the router signal**

In `src/paperhub/agents/router.py`, read the flag from state (after line 37) and pass it through:

```python
    slide_attached = bool(state.get("slide_attached"))
```

Add `slide_attached` to the tracer args (line 41) and the slot variables (lines 45-48):

```python
        step.record_args(
            {"user_message": user_message, "enabled_refs_count": enabled_refs_count,
             "slide_attached": slide_attached},
        )
        decision = await adapter.structured(
            slot="router/v1",
            variables={
                "user_message": user_message,
                "enabled_refs_count": enabled_refs_count,
                "slide_attached": slide_attached,
            },
            ...
```

- [ ] **Step 4: Update the router prompt**

In `src/paperhub/llm/prompts/router_v1.yaml`, tighten the `slides` bullet (lines 15-22) to *commands only*:

```yaml
    - slides          user wants to CREATE, EDIT, or add SPEAKER NOTES to a
                      slide deck / talk / presentation — i.e. a COMMAND that
                      CHANGES or CREATES the deck: "把講稿變成繁體中文" (re-language
                      notes), "edit this slide / 改第三頁", "make the deck shorter",
                      "translate the slides to English", "redo the slides",
                      "generate speaker notes". Choose slides ONLY when the user
                      tells you to CHANGE or CREATE the deck — not when they ASK
                      a question about it.
```

After the `IMPORTANT — session-aware override:` block (after line 70), add:

```yaml
  IMPORTANT — slide question vs slide command:
    The user turn includes `slide_attached` (boolean) — true when the user is
    viewing a slide and has attached it as context. When `slide_attached == true`
    and the user ASKS A QUESTION about the slide / figure / its content rather
    than telling you to change the deck — "explain this graph", "可以幫我更詳細
    解釋這個圖嗎" ("can you explain this graph in more detail"), "what does this
    mean", "why did they choose X" — route to `paper_qa`, NOT `slides`. Only an
    instruction to modify / translate / recreate the deck is `slides`.
    Example: slide_attached=true, "可以幫我更詳細解釋這個圖嗎" → intent: paper_qa,
    resolved_query: "explain in more detail the graph shown on the current slide".
    Example: slide_attached=true, "把整份簡報換成英文" → intent: slides.
```

Add `slide_attached` to the user template (lines 87-92):

```yaml
user: |
  enabled_refs_count: {enabled_refs_count}
  slide_attached: {slide_attached}

  User message:
  {user_message}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paperhub/agents/router.py src/paperhub/llm/prompts/router_v1.yaml tests/test_router.py
git commit -m "feat(slides): router routes attached-slide questions to paper_qa"
```

---

## Task 6: Deck-command classifier — `qa` action + slide_attached default scope

**Files:**
- Modify: `src/paperhub/agents/report_pipeline.py:106-126` (`classify_deck_command`), `src/paperhub/llm/prompts/slides_deck_command_v1.yaml`
- Test: `tests/test_deck_command.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deck_command.py`:

```python
def test_deck_command_prompt_lists_qa_and_attached_rules() -> None:
    from paperhub.llm.prompts.registry import PromptRegistry
    p = PromptRegistry().get("slides_deck_command/v1")
    assert '"qa"' in p.system
    assert "explain" in p.system.lower()
    assert "SLIDE_ATTACHED" in p.system or "slide_attached" in p.system
    assert "{slide_attached}" in p.user_template
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_deck_command.py -k qa_and_attached -v`
Expected: FAIL — prompt lacks `"qa"` / the slide_attached rule / the template variable.

- [ ] **Step 3: Update `classify_deck_command` signature**

In `src/paperhub/agents/report_pipeline.py`, add a `slide_attached: bool = False` keyword to `classify_deck_command` (line 107-108) and pass it through:

```python
async def classify_deck_command(
    *, adapter: LlmAdapter, tracer: Tracer, model: str, instruction: str,
    current_view_page: int, deck_outline: str, slide_attached: bool = False,
) -> DeckCommand:
    async with tracer.step(agent="report", tool="report:deck_command", model=model) as step:
        step.record_args({"instruction": instruction,
                          "current_view_page": current_view_page,
                          "slide_attached": slide_attached})
        dec = await adapter.structured(
            slot="slides_deck_command/v1",
            variables={
                "instruction": instruction,
                "current_view_page": current_view_page,
                "deck_outline": deck_outline,
                "slide_attached": slide_attached,
            },
            response_model=DeckCommand,
            model=model,
        )
        step.record_result(dec.model_dump())
    return dec
```

- [ ] **Step 4: Update the classifier prompt**

In `src/paperhub/llm/prompts/slides_deck_command_v1.yaml`, extend the action enum (line 4) to include `|"qa"`. Add a `qa` rule at the TOP of `Rules:` (after line 7):

```yaml
   - "qa": the user is ASKING A QUESTION about the slide / a figure / the
     content rather than telling you to CHANGE the deck — "explain this graph",
     "可以幫我更詳細解釋這個圖嗎" ("can you explain this graph in more detail"),
     "what does this slide mean", "why did they pick X", "I don't understand
     this part". This is answered, NOT an edit: choose "qa" and do NOT choose
     edit_slides. Defaults (scope/page/lang) stay unset. Choose an
     edit/notes/regenerate action ONLY when the user instructs you to CHANGE,
     TRANSLATE, SHORTEN, or RECREATE something.
```

Add a `SLIDE_ATTACHED` scope rule near the `edit_slides` scope rules (after line 19):

```yaml
   - SLIDE_ATTACHED scope default: the turn includes SLIDE_ATTACHED (boolean).
     When SLIDE_ATTACHED is true and the user did NOT explicitly target the
     whole deck ("整份/所有投影片/the whole deck/all slides") or name a page,
     an edit_slides command defaults to target_scope="current" (the attached
     on-screen slide) — NOT "all". Explicit "whole deck" / "slide N" still wins.
```

Add the variable to the user template (after line 49 `CURRENT_VIEW_PAGE: {current_view_page}`):

```yaml
  SLIDE_ATTACHED: {slide_attached}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_deck_command.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paperhub/agents/report_pipeline.py src/paperhub/llm/prompts/slides_deck_command_v1.yaml tests/test_deck_command.py
git commit -m "feat(slides): deck-command classifier learns qa + attached-scope default"
```

---

## Task 7: report_graph — `sl_qa`, qa route, no default→edit_slides, pass slide_attached

**Files:**
- Modify: `src/paperhub/agents/report_graph.py` (`ReportDeps` ~211-230; `_resolve` classify call ~347-353; `_route` ~376-395 → module-level; node defs; wiring ~1358-1388)
- Test: `tests/test_report_qa_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_qa_route.py`:

```python
import pytest

from paperhub.models.domain import DeckCommand

pytestmark = pytest.mark.asyncio


def test_route_qa_goes_to_sl_qa(monkeypatch) -> None:
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: True)
    state = {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="qa")}
    assert rg._route_deck_command(state) == "qa"


def test_route_unknown_action_never_edits(monkeypatch) -> None:
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: True)
    assert rg._route_deck_command(
        {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="edit_slides")}
    ) == "edit_slides"
    assert rg._route_deck_command(
        {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="qa")}
    ) == "qa"


def test_route_qa_answered_even_without_latex(monkeypatch) -> None:
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: False)
    assert rg._route_deck_command(
        {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="qa")}
    ) == "qa"


async def test_sl_qa_delegates_to_answer_callback(fake_tracer, tmp_path) -> None:
    from pathlib import Path

    from paperhub.agents.report_graph import ReportDeps, build_report_subgraph
    from paperhub.db.connection import open_db
    from paperhub.db.deck_slides import (
        DeckSlideInput, get_deck_slides, replace_deck_slides,
    )
    from paperhub.db.decks import get_deck, upsert_deck
    from paperhub.db.migrate import apply_schema

    async def _answer(_state) -> str:
        return "The graph shows X [chunk:101]."

    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        await conn.execute(
            "INSERT INTO paper_content (id, title, source_dir_path, kind) "
            "VALUES (7, 'P', '/x', 'arxiv')")
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled) VALUES (1, 7, 1)")
        await conn.commit()
        await upsert_deck(conn, session_id=1, run_id=None, tex_path="/x.tex",
                          pdf_path=None, speaker_notes={}, plan={}, page_count=1,
                          contributing_paper_ids=[], status="ok")
        deck = await get_deck(conn, session_id=1)
        await replace_deck_slides(conn, deck_id=deck.id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}b\\end{frame}",
                           page_start=1, page_end=1)])

        deps = ReportDeps(
            adapter=object(), tracer=fake_tracer, conn=conn, workspace=Path(tmp_path),
            plan_model="m", section_model="m", notes_model="m", resolve_model="m",
            answer_slide_question=_answer)
        graph = build_report_subgraph(deps)
        state = {"run_id": fake_tracer._run_id, "branch": "", "session_id": 1,  # noqa: SLF001
                 "user_message": "explain this graph", "current_view_page": 1,
                 "report_command": DeckCommand(action="qa"),
                 "report_papers": [{"id": 7, "source_dir": "/x"}]}
        final = ""
        async for mode, payload in graph.astream(state, stream_mode=["values"]):
            if mode == "values" and isinstance(payload, dict) and "final_response" in payload:
                final = payload["final_response"]
        assert final == "The graph shows X [chunk:101]."
        rows = await get_deck_slides(conn, deck_id=deck.id)
        assert rows[0].frame_tex == "\\begin{frame}{A}b\\end{frame}"  # untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_qa_route.py -v`
Expected: FAIL — `_route_deck_command` / `answer_slide_question` field / `qa` route don't exist.

- [ ] **Step 3: Implement the report-graph changes**

In `src/paperhub/agents/report_graph.py`:

(a) Add near the top imports:

```python
from collections.abc import Awaitable, Callable
```

(b) Add to `ReportDeps` (after line 230, inside the dataclass):

```python
    # v2.29 slide-aware QA: a qa deck-command delegates here (wired in chat.py
    # to run the paper_qa subgraph with the active-slide context). None → a
    # graceful fallback message.
    answer_slide_question: Callable[[AgentState], Awaitable[str]] | None = field(
        default=None
    )
```

(c) Lift `_route` to a module-level pure function (single source of truth, directly testable). Delete the nested `def _route(state)` (lines 376-395) and add at module level:

```python
def _route_deck_command(state: AgentState) -> str:
    """Map a resolved deck-command state to a report-graph node name.

    qa is checked BEFORE the no_latex guard so a content question is answered
    even on a host without pdflatex. An unknown action is answered (qa), NEVER
    routed to edit_slides — that default fallback is what rewrote the slide in
    run 412.
    """
    if not state.get("report_papers"):
        return "empty"
    cmd = state.get("report_command")
    if cmd is None:
        return "create"
    if cmd.action == "qa":
        return "qa"
    if not _pdflatex_available():
        return "no_latex"
    if cmd.action == "regenerate":
        return "create"
    if cmd.action in ("generate_notes", "edit_notes"):
        return "notes"
    if cmd.action == "edit_title":
        return "edit_title"
    if cmd.action == "edit_preamble":
        return "edit_preamble"
    if cmd.action == "edit_slides":
        return "edit_slides"
    return "qa"  # unknown/unhandled action is answered, never silently edited
```

(d) Pass `slide_attached` into the classifier in `_resolve` (the `classify_deck_command(...)` call at lines 347-353):

```python
            classify_deck_command(
                adapter=deps.adapter,
                tracer=deps.tracer,
                model=deps.resolve_model,
                instruction=instruction,
                current_view_page=state.get("current_view_page") or 1,
                deck_outline=outline,
                slide_attached=bool(state.get("slide_attached")),
            ),
```

(e) Add the `_sl_qa` node (before the `g = StateGraph(...)` at line 1358):

```python
    _QA_UNAVAILABLE = (
        "I can answer questions about this slide, but the answerer isn't "
        "wired in this context. Please ask again as a normal question."
    )

    async def _sl_qa(state: AgentState) -> AgentState:
        """Answer a question about the on-screen slide via the shared paper_qa
        flow. NEVER recompiles and NEVER touches deck_slides."""
        if deps.answer_slide_question is None:
            return {**state, "final_response": _QA_UNAVAILABLE}
        return {**state, "final_response": await deps.answer_slide_question(state)}
```

(f) Wire the node + edges (graph assembly, lines 1358-1388): add `g.add_node("sl_qa", _sl_qa)`, reference the module-level function in the conditional edges (`g.add_conditional_edges("sl_resolve", _route_deck_command, { ... "qa": "sl_qa" })`), and `g.add_edge("sl_qa", END)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report_qa_route.py tests/test_report_pipeline.py tests/test_report_edit_fns.py -v`
Expected: PASS (new + existing report tests).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/report_graph.py tests/test_report_qa_route.py
git commit -m "feat(slides): sl_qa node answers deck questions; remove default->edit_slides"
```

---

## Task 8: chat.py wires the `answer_slide_question` closure

**Files:**
- Modify: `src/paperhub/api/chat.py` (`report_stream` ~448-491; `ReportDeps` construction ~465-476)
- Test: `tests/test_chat_slides_sse.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_slides_sse.py`:

```python
async def test_answer_slide_question_closure_joins_paper_qa(monkeypatch) -> None:
    from paperhub.api import chat as chatmod

    async def _fake_qa_stream(state, **_k):
        yield "The graph "
        yield "shows X [chunk:9]."

    monkeypatch.setattr(chatmod, "paper_qa_stream", _fake_qa_stream)
    closure = chatmod._build_slide_qa_answerer(
        adapter=object(), tracer=object(), model="m", conn=object())
    assert await closure({"session_id": 1}) == "The graph shows X [chunk:9]."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_slides_sse.py -k closure_joins -v`
Expected: FAIL — `AttributeError: module 'paperhub.api.chat' has no attribute '_build_slide_qa_answerer'`.

- [ ] **Step 3: Implement the closure + pass it to ReportDeps**

In `src/paperhub/api/chat.py`, add near `report_stream`:

```python
def _build_slide_qa_answerer(
    *, adapter: Any, tracer: Tracer, model: str, conn: aiosqlite.Connection
) -> Any:
    """Return an async callable answering a slide question via the shared
    paper_qa subgraph; returns the full text (FinalOnlyMessage content or the
    joined token stream). Trace steps land in tool_calls (drained end-of-turn)."""
    async def _answer(state: AgentState) -> str:
        chunks: list[str] = []
        async for item in paper_qa_stream(
            state, adapter=adapter, tracer=tracer, model=model, conn=conn,
        ):
            if isinstance(item, ToolStepYield):
                continue
            if isinstance(item, FinalOnlyMessage):
                return item.content
            chunks.append(item)
        return "".join(chunks)

    return _answer
```

In `report_stream`, pass it to `ReportDeps` (after `slide_style_profile_name=...`, ~line 475):

```python
        answer_slide_question=_build_slide_qa_answerer(
            adapter=adapter, tracer=tracer,
            model=settings.paper_qa_model, conn=conn,
        ),
```

(`paper_qa_stream`, `ToolStepYield`, `FinalOnlyMessage` already exist in `chat.py`.)

- [ ] **Step 4: Backend gate**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/api/chat.py tests/test_chat_slides_sse.py
git commit -m "feat(slides): wire paper_qa answerer into the slides qa guard"
```

---

# Phase 2 — Frontend

## Task 9: slides store — sticky `slideAttachedBySession`

**Files:**
- Modify: `src/store/slides.ts`
- Test: `src/store/slides.test.ts` (create if absent; follow the repo's Vitest store-test style)

- [ ] **Step 1: Write the failing test**

Add to `src/store/slides.test.ts`:

```ts
import { describe, expect, it, beforeEach } from "vitest";
import { useSlidesStore } from "./slides";

describe("slideAttached", () => {
  beforeEach(() => {
    useSlidesStore.setState({ slideAttachedBySession: {} });
  });

  it("defaults to attached (undefined) and toggles sticky per session", () => {
    const { setSlideAttached } = useSlidesStore.getState();
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBeUndefined();
    setSlideAttached(7, false);
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBe(false);
    setSlideAttached(7, true);
    expect(useSlidesStore.getState().slideAttachedBySession[7]).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- slides.test`
Expected: FAIL — `slideAttachedBySession` / `setSlideAttached` undefined.

- [ ] **Step 3: Implement the store slice**

In `src/store/slides.ts`, add to `SlidesState` (after `currentPageBySession`, line 27):

```ts
  /** Per-session "attach the on-screen slide as chat context" toggle (the
   *  composer chip's eye). Sticky per session: persists across slide changes;
   *  the attached CONTENT tracks the active slide via currentPageBySession.
   *  Undefined → attached (auto-on when a deck is open). Ephemeral (not
   *  persisted), like deck data. */
  slideAttachedBySession: Record<number, boolean>;
  setSlideAttached: (sid: number, attached: boolean) => void;
```

Add the initial value (after `currentPageBySession: {},`, line 63) `slideAttachedBySession: {},` and the setter (after `setCurrentPage`, line 85):

```ts
      setSlideAttached: (sid, attached) =>
        set((s) => ({
          slideAttachedBySession: { ...s.slideAttachedBySession, [sid]: attached },
        })),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- slides.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/store/slides.ts src/store/slides.test.ts
git commit -m "feat(slides): sticky per-session slide-attach toggle in slides store"
```

---

## Task 10: `SlideContextChip` component

**Files:**
- Create: `src/components/chat/SlideContextChip.tsx`
- Test: `src/components/chat/SlideContextChip.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/components/chat/SlideContextChip.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SlideContextChip } from "./SlideContextChip";

describe("SlideContextChip", () => {
  it("shows the active slide page and is attached by default (eye open)", () => {
    render(<SlideContextChip page={5} attached onToggle={() => {}} />);
    expect(screen.getByText(/Slide 5/)).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("calls onToggle when the eye is clicked", () => {
    const onToggle = vi.fn();
    render(<SlideContextChip page={3} attached={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalledOnce();
    // detached → aria-pressed false (still shows the slide content)
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/Slide 3/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- SlideContextChip`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `src/components/chat/SlideContextChip.tsx`:

```tsx
import { Eye, EyeOff } from "lucide-react";

interface Props {
  /** 1-based page of the on-screen slide (content tracks the active slide). */
  page: number;
  /** Whether the slide is attached as chat context (eye open). */
  attached: boolean;
  /** Toggle attachment. Does NOT change which slide is shown. */
  onToggle: () => void;
}

/** Composer context chip for the on-screen slide. Always rendered while a deck
 *  is in view (content tracks the active slide even when detached); the eye
 *  toggles whether the slide is attached as chat context. */
export function SlideContextChip({ page, attached, onToggle }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={attached}
      aria-label={attached ? "Slide attached as context — click to detach"
                           : "Slide detached — click to attach as context"}
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs " +
        "transition-colors " +
        (attached
          ? "border-ring bg-accent text-foreground"
          : "border-input bg-muted/40 text-muted-foreground hover:text-foreground")
      }
    >
      {attached ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
      <span>Slide {page}</span>
    </button>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- SlideContextChip`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/chat/SlideContextChip.tsx src/components/chat/SlideContextChip.test.tsx
git commit -m "feat(slides): SlideContextChip composer affordance (eye toggle)"
```

---

## Task 11: Composer renders the chip; ChatPage supplies its state

**Files:**
- Modify: `src/components/chat/Composer.tsx` (Props + render above the textarea), `src/pages/ChatPage.tsx` (compute props, pass to Composer)
- Test: `src/components/chat/Composer.test.tsx` (extend existing)

- [ ] **Step 1: Write the failing test**

Add to `src/components/chat/Composer.test.tsx`:

```tsx
it("renders the slide chip when slideChip prop is provided", () => {
  const onToggle = vi.fn();
  render(
    <Composer onSubmit={() => {}} disabled={false}
      slideChip={{ page: 5, attached: true, onToggle }} />,
  );
  expect(screen.getByText(/Slide 5/)).toBeInTheDocument();
});

it("omits the slide chip when slideChip is null", () => {
  render(<Composer onSubmit={() => {}} disabled={false} slideChip={null} />);
  expect(screen.queryByText(/Slide/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Composer`
Expected: FAIL — `slideChip` is not a Composer prop.

- [ ] **Step 3: Implement Composer prop + render**

In `src/components/chat/Composer.tsx`, import the chip and extend `Props`:

```tsx
import { SlideContextChip } from "@/components/chat/SlideContextChip";
```

```tsx
  /** When the session has a deck in view, the active-slide chip state; null
   *  hides the chip. Content (page) tracks the active slide; attached is the
   *  sticky toggle. */
  slideChip?: { page: number; attached: boolean; onToggle: () => void } | null;
```

Destructure `slideChip = null` in the component signature, then render it just inside the rounded container, above the `<textarea>` (after line 170's opening `<div className="rounded-2xl …">`):

```tsx
          {slideChip && (
            <div className="px-3 pt-2">
              <SlideContextChip
                page={slideChip.page}
                attached={slideChip.attached}
                onToggle={slideChip.onToggle}
              />
            </div>
          )}
```

- [ ] **Step 4: Wire ChatPage to compute the chip props**

In `src/pages/ChatPage.tsx`, near the existing slides-store reads (around lines 110-128), derive the chip props from the store + active backend session and pass to `<Composer>`:

```tsx
  const deckForChip = useSlidesStore((s) =>
    backendSessionId === null ? undefined : s.deckBySession[backendSessionId]);
  const currentPageForChip = useSlidesStore((s) =>
    backendSessionId === null ? 1 : (s.currentPageBySession[backendSessionId] ?? 1));
  const slideAttached = useSlidesStore((s) =>
    backendSessionId === null ? true
      : (s.slideAttachedBySession[backendSessionId] ?? true));
  const setSlideAttached = useSlidesStore((s) => s.setSlideAttached);

  const slideChip =
    backendSessionId !== null && deckForChip
      ? {
          page: currentPageForChip,
          attached: slideAttached,
          onToggle: () => setSlideAttached(backendSessionId, !slideAttached),
        }
      : null;
```

Pass `slideChip={slideChip}` to the `<Composer ... />` element. (If `useSlidesStore` is not already imported in ChatPage, add `import { useSlidesStore } from "@/store/slides";` — it is already used for `deckRevisionBySession`, so the import exists.)

- [ ] **Step 5: Run tests**

Run: `npm test -- Composer && npm run typecheck`
Expected: PASS; types clean.

- [ ] **Step 6: Commit**

```bash
git add src/components/chat/Composer.tsx src/pages/ChatPage.tsx src/components/chat/Composer.test.tsx
git commit -m "feat(slides): show the slide-context chip in the composer"
```

---

## Task 12: useChatStream sends `slide_attached`

**Files:**
- Modify: `src/hooks/useChatStream.ts:54-69`
- Test: `src/hooks/useChatStream.test.ts` (extend existing; or assert via the MSW request body)

- [ ] **Step 1: Write the failing test**

Add to the useChatStream test (follow the file's existing MSW/fetch-capture pattern; the key assertion is on the POSTed body):

```ts
it("sends slide_attached when a deck is open and the chip is attached", async () => {
  // arrange: a session with a backend id + a deck in the slides store, chip attached
  // (reuse the file's existing setup helpers), then send a message and capture
  // the /chat request body.
  // assert:
  expect(capturedBody.slide_attached).toBe(true);
  expect(capturedBody.current_view_page).toBe(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- useChatStream`
Expected: FAIL — body has no `slide_attached`.

- [ ] **Step 3: Implement the send**

In `src/hooks/useChatStream.ts`, alongside the existing `currentViewPage` computation (lines 57-60), read the sticky toggle and include it in the body (lines 66-69):

```ts
    const slides = useSlidesStore.getState();
    const hasDeck =
      backendSessionId !== null && !!slides.deckBySession[backendSessionId];
    const currentViewPage =
      hasDeck ? (slides.currentPageBySession[backendSessionId] ?? 1) : undefined;
    const slideAttached =
      hasDeck ? (slides.slideAttachedBySession[backendSessionId] ?? true) : false;
```

In the request body object (lines 66-70):

```ts
          session_id: backendSessionId,
          ...(currentViewPage !== undefined ? { current_view_page: currentViewPage } : {}),
          slide_attached: slideAttached,
```

- [ ] **Step 4: Run tests + full frontend gate**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useChatStream.ts src/hooks/useChatStream.test.ts
git commit -m "feat(slides): send slide_attached flag in the chat request"
```

---

# Phase 3 — Real-API + end-to-end gate

## Task 13: `:8000` + two-window gate (phase-end, manual)

**The correctness gate — pytest/Vitest prove wiring, not that the LLM obeys the new prompts or that the chip drives the flow end-to-end. Run ONCE, after Phases 1-2.** Do NOT boot your own backend; use the user's live `:8000`.

- [ ] **Step 1: Confirm the backend is live** — `curl -s -m 3 http://127.0.0.1:8000/health`. If unreachable, STOP and ask the user to start it.

- [ ] **Step 2: Reproduce the bug, router path (chip ON).** New session → add a figure-bearing paper → generate a deck → ask the slide question with `slide_attached:true`:

```bash
curl -s -N -X POST http://127.0.0.1:8000/chat -H 'content-type: application/json' \
  -d '{"session_id": <SID>, "user_message": "可以幫我更詳細解釋這個圖嗎", "current_view_page": 5, "slide_attached": true}'
```

- [ ] **Step 3: Verify the trace.** `uv run paperhub-replay --run-id <N>` (newest run). Assert: `intent == "paper_qa"` (NOT slides); steps `router:classify → research… → paper_qa:subagent → paper_qa:finalize`; **no `report:edit_frame`**; the subagent `user_message` contains the slide-context block (page + title + figure caption); the answer cites real `[chunk:N]` ids.

- [ ] **Step 4: Verify the deck is untouched.**

```sql
SELECT slide_index, length(frame_tex) FROM deck_slides
  WHERE deck_id = (SELECT id FROM decks WHERE session_id = <SID>) ORDER BY slide_index;
```

Assert identical to post-generation; `decks.updated_at` unchanged on the QA turn.

- [ ] **Step 5: Detached path (chip OFF).** Re-ask with `"slide_attached": false`. Assert the trace shows no `slide_context` in the subagent args (plain paper_qa) — confirms the gate.

- [ ] **Step 6: Layer-2 guard.** Force a misroute (e.g. `PAPERHUB_ROUTER_MOCK` returning a `slides` decision, or a borderline command-shaped question) with `slide_attached:true`. Confirm `report:deck_command` → `action="qa"` → `sl_qa` → grounded answer, no `report:edit_frame`/recompile.

- [ ] **Step 7: Deterministic edit scope.** With chip ON, send an ambiguous single-slide edit ("make this slide shorter"). Confirm `deck_command` returns `target_scope="current"` (not "all") and only the on-screen frame changes.

- [ ] **Step 8: Human sign-off (frontend).** Ask the user to: view a figure slide → confirm the chip shows "Slide N" (eye open) → ask "explain this graph" → confirm a grounded answer with working `[chunk:N]` citations and the deck unchanged → switch slides and confirm the chip's number updates while the eye state stays → eye-blind it, ask a general question, confirm no slide context leaks.

- [ ] **Step 9: Finalize.** Use `superpowers:finishing-a-development-branch` to decide merge/PR. The SRS entry stays as written.

---

## Self-Review

**Spec coverage:** ✅ deterministic chip (`slide_attached`) — store (Task 9), component (Task 10), Composer/ChatPage (Task 11), request (Task 12), backend gating (Task 4); active-slide context block + retrieval anchor (Tasks 2-3); router rule keyed on `slide_attached` (Task 5); `qa` action + attached-scope default (Task 6); `sl_qa` + removed default→edit_slides + slide_attached→classifier (Task 7); fully-answer shared QA path (Tasks 7-8); figure caption only when present (Task 2); deterministic current scope for edits (Tasks 6-7 + gate Task 13 Step 7); deck-byte-unchanged + grounded answer (Task 13). Out-of-scope (cross-slide, edit+answer, TTS) not implemented, as specified.

**Placeholder scan:** Tasks 12 Step 1 and (partially) the useChatStream/Composer test bodies reference "the file's existing setup/MSW pattern" rather than reproducing the harness — this is deliberate (the repo's frontend test scaffolding must be matched, not guessed) and the *assertions* are concrete. All backend steps carry runnable code; `_route_deck_command` is one module-level source of truth used by both graph and tests (no factory hack).

**Type consistency:** `build_slide_context(conn, *, session_id, current_view_page)` and `slide_aware_query(state)` consistent across Tasks 2/3/4. `slide_attached` is a `bool` everywhere: `ChatRequest` (Task 4) → `AgentState` (Task 1) → router var (Task 5) → `classify_deck_command(slide_attached=...)` (Tasks 6/7). `ReportDeps.answer_slide_question` (Task 7) matches the closure passed in Task 8. Frontend `slideChip: { page, attached, onToggle }` consistent across `SlideContextChip` (Task 10) and Composer/ChatPage (Task 11); `slideAttachedBySession` / `setSlideAttached` consistent across Tasks 9/11/12.
```
