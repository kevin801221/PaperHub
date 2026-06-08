# Slide-aware QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer a question about the on-screen slide (e.g. "explain this graph") with a grounded `[chunk:N]`-cited answer, without ever mutating the deck — fixing the two-layer misclassification recorded in the session-244 trace.

**Architecture:** One slide-aware QA flow = the existing `paper_qa` subgraph + an injected **active-slide context block** that anchors retrieval. Two entry points both feed it: (1) the **router** sends deck-open *questions* to `paper_qa`; (2) a new deck-command **`action="qa"`** routes to the same flow via a `sl_qa` node that delegates to `paper_qa` through an injected callback — never editing or recompiling. The `report_graph._route` default-to-`edit_slides` fallback (which silently rewrote the slide in run 412) is removed.

**Tech Stack:** Python 3.11, `uv`, pytest (asyncio), LangGraph, aiosqlite, Pydantic. Backend gates: `uv run pytest -v`, `uv run ruff check src tests`, `uv run mypy src`. All paths below are relative to `backend/`.

**SRS reference:** the "Slide-aware QA" Revision-History entry in [docs/superpowers/specs/2026-05-17-paperhub-srs.md](../specs/2026-05-17-paperhub-srs.md) (prioritized ahead of the i18n entry).

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `src/paperhub/models/domain.py` | `DeckCommand.action` gains `"qa"`; `AgentState` gains `slide_context` | Modify |
| `src/paperhub/agents/slide_context.py` | **NEW** — `build_slide_context()` + `slide_aware_query()` | Create |
| `src/paperhub/agents/research_graph.py` | `_pq_dispatch` / `_pq_finalize` use `slide_aware_query` | Modify |
| `src/paperhub/agents/router.py` | surface `has_deck` to the classifier | Modify |
| `src/paperhub/llm/prompts/router_v1.yaml` | rule + few-shot: deck question → `paper_qa`, deck command → `slides` | Modify |
| `src/paperhub/llm/prompts/slides_deck_command_v1.yaml` | rule + few-shot: question → `qa` | Modify |
| `src/paperhub/agents/report_graph.py` | `ReportDeps.answer_slide_question`; `sl_qa` node; `_route` qa branch; remove default→`edit_slides` | Modify |
| `src/paperhub/api/chat.py` | build+thread `slide_context`; wire `answer_slide_question` closure | Modify |
| `tests/test_slide_context.py` | **NEW** — `build_slide_context` / `slide_aware_query` | Create |
| `tests/test_research_paper_qa.py` | slide-aware query reaches the subagent | Modify |
| `tests/test_router.py` | deck question vs command routing | Modify |
| `tests/test_deck_command.py` | question → `qa` | Modify |
| `tests/test_report_qa_route.py` | **NEW** — `_route` qa branch + no default→edit_slides + sl_qa delegates | Create |

---

## Task 1: Models — `qa` action + `slide_context` state field

**Files:**
- Modify: `src/paperhub/models/domain.py:102-108` (DeckCommand.action), `src/paperhub/models/domain.py:142-205` (AgentState)
- Test: `tests/test_slide_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_slide_models.py`:

```python
def test_deck_command_accepts_qa_action() -> None:
    from paperhub.models.domain import DeckCommand
    cmd = DeckCommand(action="qa")
    assert cmd.action == "qa"
    assert cmd.target_scope == "all"  # default unchanged


def test_agent_state_allows_slide_context() -> None:
    from paperhub.models.domain import AgentState
    state: AgentState = {"slide_context": "viewing slide 5"}  # type: ignore[typeddict-item]
    assert state["slide_context"] == "viewing slide 5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slide_models.py -k "qa_action or slide_context" -v`
Expected: FAIL — `ValidationError` ("Input should be 'generate_notes', …") for the first; the second fails mypy/typeddict check only at type-check time, so it passes at runtime but `mypy` in Step 4 will flag it until the field exists.

- [ ] **Step 3: Write minimal implementation**

In `src/paperhub/models/domain.py`, extend the Literal (line 102-105):

```python
    action: Literal[
        "generate_notes", "edit_notes", "edit_slides",
        "edit_title", "edit_preamble", "regenerate", "qa",
    ]
```

In `AgentState` (after the `current_view_page` line, ~line 196), add:

```python
    # v2.30 (slide-aware QA): the active-slide context block built by
    # agents/slide_context.build_slide_context from current_view_page. None
    # when no deck / page<=0 / no spanning row → plain paper_qa, no regression.
    slide_context: str | None
```

- [ ] **Step 4: Run test + types to verify they pass**

Run: `uv run pytest tests/test_slide_models.py -v && uv run mypy src/paperhub/models/domain.py`
Expected: PASS; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/models/domain.py tests/test_slide_models.py
git commit -m "feat(slides): add DeckCommand qa action + AgentState.slide_context"
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
                           page_start=1, page_end=1),
        ])
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
                           page_start=2, page_end=2),
        ])
        ctx = await build_slide_context(conn, session_id=1, current_view_page=1)
        assert ctx is not None
        assert "Coarse-to-fine RVQ" in ctx
        assert "Action patchifier partitions sequences" in ctx
        assert "RVQ stabilizes training" in ctx
        assert "Figure" not in ctx  # no \includegraphics in this frame


async def test_page_out_of_range_returns_none(tmp_path) -> None:
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex="\\begin{frame}{A}\\end{frame}",
                           page_start=1, page_end=1),
        ])
        assert await build_slide_context(conn, session_id=1, current_view_page=9) is None


async def test_figure_frame_resolves_caption(tmp_path, monkeypatch) -> None:
    from paperhub.pipelines.slide_pipeline.figure_inventory import InventoryFigure
    monkeypatch.setattr(
        "paperhub.agents.slide_context.build_inventory",
        lambda papers: [InventoryFigure(
            key="p0-fig-002", caption="Fig. 2. Coarse-to-fine residual VQ.",
            abs_path="/x/p0-fig-002.png", paper_id=7,
        )],
    )
    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        deck_id = await _seed_deck(conn, page_count=1)
        frame = (
            "\\begin{frame}{FASTerVQ Architecture}\n"
            "  \\includegraphics[width=\\linewidth]{p0-fig-002}\n\\end{frame}"
        )
        await replace_deck_slides(conn, deck_id=deck_id, slides=[
            DeckSlideInput(slide_index=0, frame_tex=frame, page_start=1, page_end=1),
        ])
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
"""Active-slide context for slide-aware QA (SRS v2.30).

When the user is viewing a generated slide deck and asks a question about
the on-screen slide, ``build_slide_context`` produces a compact block that
anchors paper_qa's section navigation onto the right part of the paper. It
is the single retrieval anchor shared by both the router→paper_qa path and
the slides ``action="qa"`` guard. Returns ``None`` (→ plain paper_qa, no
regression) whenever there is no deck / no on-screen page / no matching row.
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
    out = [_strip_latex(m.group(1)) for m in _ITEM_RE.finditer(frame_tex)]
    return [b for b in out if b]


def _frame_figure_keys(frame_tex: str) -> list[str]:
    return [Path(m.group(1)).stem for m in _GRAPHICS_RE.finditer(frame_tex)]


async def _enabled_paper_keys(
    conn: aiosqlite.Connection, session_id: int
) -> list[dict[str, object]]:
    # Same ordering (added_at) build_inventory used at deck-build time, so the
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
    """Return the active-slide context block, or ``None`` when not applicable."""
    if current_view_page is None or current_view_page <= 0:
        return None
    deck = await get_deck(conn, session_id=session_id)
    if deck is None:
        return None
    rows = await get_deck_slides(conn, deck_id=deck.id)
    row = next(
        (r for r in rows if r.page_start <= current_view_page <= r.page_end), None
    )
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
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/slide_context.py tests/test_slide_context.py
git commit -m "feat(slides): build_slide_context + slide_aware_query retrieval anchor"
```

---

## Task 3: paper_qa consumes the slide-aware query

**Files:**
- Modify: `src/paperhub/agents/research_graph.py` (`_pq_dispatch` ~487, `_pq_finalize` ~509-544)
- Test: `tests/test_research_paper_qa.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_research_paper_qa.py`:

```python
async def test_slide_context_reaches_subagent_query(
    migrated_db: aiosqlite.Connection,
    fake_tracer: Tracer,
    monkeypatch,
) -> None:
    """When state carries slide_context, the per-paper subagent is called with
    the augmented query (slide context prepended)."""
    from paperhub.agents import research_graph as rg
    from paperhub.agents.paper_qa_subagent import PerPaperPicks

    session_id = await _make_session(migrated_db)
    captured: dict[str, str] = {}

    async def _fake_resolve(*_args, **_kwargs):
        return [(15, "FASTerVQ")]

    async def _fake_subagent(*, user_message: str, **_kwargs):
        captured["user_message"] = user_message
        return PerPaperPicks(
            paper_content_id=15, title="FASTerVQ", picked_chunks=[], rationale="",
        )

    monkeypatch.setattr(rg, "_resolve_enabled_papers", _fake_resolve)
    monkeypatch.setattr(rg, "run_paper_qa_subagent", _fake_subagent)

    deps = rg.ResearchDeps(
        adapter=_StubAdapter(["ok"]), tracer=fake_tracer, paper_qa_model="m",
        conn=migrated_db,
    )
    graph = rg.build_paper_qa_subgraph(deps)
    state = {
        "run_id": fake_tracer._run_id,  # noqa: SLF001
        "branch": "", "session_id": session_id,
        "user_message": "explain this graph",
        "effective_query": "explain the graph on the current slide",
        "slide_context": "Active slide (page 5) title: FASTerVQ Architecture",
    }
    async for _ in graph.astream(state, stream_mode=["values"]):
        pass
    assert captured["user_message"].startswith("Active slide (page 5) title: FASTerVQ Architecture")
    assert "explain the graph on the current slide" in captured["user_message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_paper_qa.py -k slide_context_reaches -v`
Expected: FAIL — `captured["user_message"]` starts with the raw query (no slide context prepended), so the `startswith` assert fails.

- [ ] **Step 3: Write minimal implementation**

In `src/paperhub/agents/research_graph.py`, add the import near the other agent imports (after line 72):

```python
from paperhub.agents.slide_context import slide_aware_query
```

In `_pq_dispatch`, inside `_one_with_emit`, change the `user_message` argument (line ~482):

```python
            picks = await run_paper_qa_subagent(
                paper_content_id=pid,
                title=title,
                user_message=slide_aware_query(state),
                tracer=deps.tracer,
                model=subagent_model,
                conn=deps.conn,
                max_section_reads=max_reads,
                **_kwargs(deps),
            )
```

In `_pq_finalize`, change the `user_message` passed to `paper_qa_finalize` (line ~534):

```python
            user_message=slide_aware_query(state),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_research_paper_qa.py -v`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/research_graph.py tests/test_research_paper_qa.py
git commit -m "feat(slides): paper_qa subagent + finalizer use the slide-aware query"
```

---

## Task 4: chat.py builds + threads `slide_context`

**Files:**
- Modify: `src/paperhub/api/chat.py` (imports near line 24; state after `router_node`, ~line 554)

- [ ] **Step 1: Add the import**

In `src/paperhub/api/chat.py`, add to the agent imports:

```python
from paperhub.agents.slide_context import build_slide_context
```

- [ ] **Step 2: Thread slide_context into state after routing**

Immediately after the router runs and before `decision = state["routing_decision"]` (i.e. after line 558's drain loop, before line 559), insert:

```python
                # Slide-aware QA: build the active-slide context once so both
                # the paper_qa branch and the slides action="qa" guard read it.
                state = {
                    **state,
                    "slide_context": await build_slide_context(
                        conn,
                        session_id=session_id,
                        current_view_page=req.current_view_page,
                    ),
                }
```

- [ ] **Step 3: Verify no regression**

Run: `uv run pytest tests/test_chat_sse.py tests/test_chat_slides_sse.py -v`
Expected: PASS — existing SSE flows unaffected (`slide_context` is `None` for every non-deck test session, so behaviour is unchanged). The functional effect is proven by Task 3's subgraph test and the Task 9 real-API gate.

- [ ] **Step 4: Commit**

```bash
git add src/paperhub/api/chat.py
git commit -m "feat(slides): thread active-slide context into chat state after routing"
```

---

## Task 5: Router distinguishes deck question vs deck command

**Files:**
- Modify: `src/paperhub/agents/router.py:28-53`, `src/paperhub/llm/prompts/router_v1.yaml`
- Test: `tests/test_router.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_router.py` (follow the file's existing stub-adapter / `router_node` harness — reuse whatever `_StubAdapter`/fixture the file already defines; the assertion is on the variables the router passes to the prompt slot):

```python
async def test_router_surfaces_has_deck_variable(migrated_db, fake_tracer) -> None:
    """When the session has a deck, the router prompt receives has_deck=True."""
    from paperhub.agents.router import router_node
    from paperhub.db.decks import upsert_deck

    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.commit()
    await upsert_deck(
        migrated_db, session_id=1, run_id=None, tex_path="/x.tex", pdf_path=None,
        speaker_notes={}, plan={}, page_count=1, contributing_paper_ids=[], status="ok",
    )
    captured: dict[str, object] = {}

    class _Cap:
        async def structured(self, *, slot, variables, response_model, model, **__):
            captured.update(variables)
            return response_model(
                intent="paper_qa", model_tier="flagship", confidence=1.0,
                reasoning="x", resolved_query="explain this graph",
                response_language="English",
            )

    state = {"run_id": fake_tracer._run_id, "branch": "", "session_id": 1,  # noqa: SLF001
             "user_message": "explain this graph", "history": []}
    await router_node(state, adapter=_Cap(), tracer=fake_tracer, model="m",
                      conn=migrated_db)
    assert captured["has_deck"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router.py -k has_deck -v`
Expected: FAIL — `KeyError: 'has_deck'` (router does not pass that variable yet).

- [ ] **Step 3: Implement the router signal**

In `src/paperhub/agents/router.py`, after computing `enabled_refs_count` (after line 37), add:

```python
    has_deck = False
    if session_id is not None:
        async with target_conn.execute(
            "SELECT 1 FROM decks WHERE session_id = ? LIMIT 1", (session_id,),
        ) as cur:
            has_deck = (await cur.fetchone()) is not None
```

Add `has_deck` to both the tracer args (line 41) and the slot variables (line 45-48):

```python
        step.record_args(
            {"user_message": user_message, "enabled_refs_count": enabled_refs_count,
             "has_deck": has_deck},
        )
        decision = await adapter.structured(
            slot="router/v1",
            variables={
                "user_message": user_message,
                "enabled_refs_count": enabled_refs_count,
                "has_deck": has_deck,
            },
            ...
```

- [ ] **Step 4: Update the router prompt**

In `src/paperhub/llm/prompts/router_v1.yaml`, replace the `slides` bullet (lines 15-22) with a version that distinguishes command from question:

```yaml
    - slides          user wants to CREATE, EDIT, or add SPEAKER NOTES to a
                      slide deck / talk / presentation — i.e. a COMMAND that
                      CHANGES the deck: "把講稿變成繁體中文" (re-language notes),
                      "edit this slide / 改第三頁", "make the deck shorter",
                      "translate the slides to English", "redo the slides",
                      "generate speaker notes". Choose slides ONLY when the
                      user is telling you to CHANGE or CREATE the deck.
```

After the existing `IMPORTANT — session-aware override:` block (after line 70), add a second override block:

```yaml
  IMPORTANT — deck question vs deck command:
    The user turn includes `has_deck` (boolean). When `has_deck == true` and
    the user ASKS A QUESTION about the slide / figure / content rather than
    telling you to change the deck — "explain this graph", "what does this
    slide mean", "可以幫我更詳細解釋這個圖嗎" ("can you explain this graph in
    more detail"), "why did they choose X", "I don't understand this part" —
    route to `paper_qa`, NOT `slides`. A question is answered (paper_qa);
    only an instruction to modify/translate/recreate the deck is `slides`.
    Example: has_deck=true, "可以幫我更詳細解釋這個圖嗎" → intent: paper_qa,
    resolved_query: "explain in more detail the graph shown on the current
    slide". Example: has_deck=true, "把整份簡報換成英文" → intent: slides.
```

Add `has_deck` to the user template (lines 87-92):

```yaml
user: |
  enabled_refs_count: {enabled_refs_count}
  has_deck: {has_deck}

  User message:
  {user_message}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paperhub/agents/router.py src/paperhub/llm/prompts/router_v1.yaml tests/test_router.py
git commit -m "feat(slides): router routes deck questions to paper_qa, commands to slides"
```

---

## Task 6: Deck-command classifier — `qa` action

**Files:**
- Modify: `src/paperhub/llm/prompts/slides_deck_command_v1.yaml`
- Test: `tests/test_deck_command.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deck_command.py` (reuse the file's existing adapter stub / `classify_deck_command` harness; the stub must return whatever JSON the prompt would — for a *real* prompt-contract test, prefer the file's existing pattern of asserting the prompt rules. If the file mocks the adapter, assert that a question maps to `qa` via a fixture stub that echoes a fixed DeckCommand; otherwise add a prompt-text assertion):

```python
def test_deck_command_prompt_lists_qa_action() -> None:
    """The classifier prompt documents the qa action so the LLM can pick it."""
    from paperhub.llm.prompts.registry import PromptRegistry
    p = PromptRegistry().get("slides_deck_command/v1")
    assert '"qa"' in p.system
    # The few-shot covers a figure-explanation question.
    assert "explain" in p.system.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_deck_command.py -k qa_action -v`
Expected: FAIL — the prompt does not mention `"qa"`.

- [ ] **Step 3: Update the classifier prompt**

In `src/paperhub/llm/prompts/slides_deck_command_v1.yaml`, extend the action enum (line 4):

```yaml
  {"action": "generate_notes"|"edit_notes"|"edit_slides"|"edit_title"|"edit_preamble"|"regenerate"|"qa",
```

Add a `qa` rule at the TOP of the `Rules:` list (after line 7), so a question is caught before any edit rule:

```yaml
   - "qa": the user is ASKING A QUESTION about the slide / a figure / the
     content rather than telling you to CHANGE the deck — "explain this
     graph", "可以幫我更詳細解釋這個圖嗎" ("can you explain this graph in more
     detail"), "what does this slide mean", "why did they pick X", "I don't
     understand this part". This is answered, NOT an edit: choose "qa" and do
     NOT choose edit_slides. target_scope/target_page/note_language stay default.
     Only choose an edit/notes/regenerate action when the user instructs you to
     CHANGE, TRANSLATE, SHORTEN, or RECREATE something.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_deck_command.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/llm/prompts/slides_deck_command_v1.yaml tests/test_deck_command.py
git commit -m "feat(slides): deck-command classifier recognizes content questions (qa)"
```

---

## Task 7: report_graph — `sl_qa` node, qa route, no default→edit_slides

**Files:**
- Modify: `src/paperhub/agents/report_graph.py` (`ReportDeps` ~211-230; `_route` ~376-395; node defs; wiring ~1358-1388)
- Test: `tests/test_report_qa_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_qa_route.py`:

```python
import pytest

from paperhub.models.domain import DeckCommand

pytestmark = pytest.mark.asyncio


def test_route_qa_goes_to_sl_qa(monkeypatch) -> None:
    """A qa command routes to the sl_qa node, never to an edit."""
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: True)
    state = {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="qa")}
    assert rg._route_deck_command(state) == "qa"


def test_route_unknown_action_never_edits(monkeypatch) -> None:
    """An unrecognised action must NOT fall through to edit_slides (run-412 bug)."""
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: True)
    # explicit edit still works…
    state_edit = {"report_papers": [{"id": 1}],
                  "report_command": DeckCommand(action="edit_slides")}
    assert rg._route_deck_command(state_edit) == "edit_slides"
    # …but qa is answered, never edited.
    state_qa = {"report_papers": [{"id": 1}],
                "report_command": DeckCommand(action="qa")}
    assert rg._route_deck_command(state_qa) == "qa"


def test_route_qa_answered_even_without_latex(monkeypatch) -> None:
    """qa is checked before the no_latex guard — a question is answerable on a
    host without pdflatex."""
    from paperhub.agents import report_graph as rg
    monkeypatch.setattr(rg, "_pdflatex_available", lambda: False)
    state = {"report_papers": [{"id": 1}], "report_command": DeckCommand(action="qa")}
    assert rg._route_deck_command(state) == "qa"


async def test_sl_qa_delegates_to_answer_callback(fake_tracer, tmp_path) -> None:
    """sl_qa calls deps.answer_slide_question and sets final_response without
    touching the deck."""
    from pathlib import Path

    from paperhub.agents.report_graph import ReportDeps, build_report_subgraph
    from paperhub.db.connection import open_db
    from paperhub.db.decks import get_deck, upsert_deck
    from paperhub.db.deck_slides import (
        DeckSlideInput, get_deck_slides, replace_deck_slides,
    )
    from paperhub.db.migrate import apply_schema

    async def _answer(_state) -> str:
        return "The graph shows X [chunk:101]."

    async with open_db(str(tmp_path / "t.db")) as conn:
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
        # enable one paper so the empty-guard passes
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
            answer_slide_question=_answer,
        )
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
        # deck frames untouched by the qa path
        rows = await get_deck_slides(conn, deck_id=deck.id)
        assert rows[0].frame_tex == "\\begin{frame}{A}b\\end{frame}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report_qa_route.py -v`
Expected: FAIL — `ImportError` for `_make_route_for_test` / `answer_slide_question` not a `ReportDeps` field / no `qa` route.

- [ ] **Step 3: Implement the report-graph changes**

In `src/paperhub/agents/report_graph.py`:

(a) Add the import near the top:

```python
from collections.abc import Awaitable, Callable
```

(b) Add the optional callback to `ReportDeps` (after line 230, inside the dataclass):

```python
    # v2.30 slide-aware QA: when a deck-command classifies as action="qa",
    # sl_qa delegates to this callback (wired in chat.py to run the paper_qa
    # subgraph with the active-slide context). None → a graceful fallback msg.
    answer_slide_question: Callable[[AgentState], Awaitable[str]] | None = field(
        default=None
    )
```

(c) Lift `_route` OUT of `build_report_subgraph` to a **module-level pure function** `_route_deck_command` (single source of truth, directly unit-testable), so `qa` routes to `qa` and the **default no longer falls through to `edit_slides`** — every action maps explicitly. Delete the nested `def _route(state)` (lines 376-395) and add at module level (near the other module helpers):

```python
def _route_deck_command(state: AgentState) -> str:
    """Map a resolved deck-command state to a report-graph node name.

    qa is checked BEFORE the no_latex guard so a content question is answered
    even on a host without pdflatex (a deck existing implies LaTeX was present
    at generation time, but the QA path must not depend on it). An unknown
    action is answered (qa), NEVER silently routed to edit_slides — that
    default fallback is what rewrote the slide in run 412.
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

In `build_report_subgraph`, the conditional-edges call now references the module-level function directly: `g.add_conditional_edges("sl_resolve", _route_deck_command, { ... })`.

(d) Add the `_sl_qa` node (place near the other node defs, before the `g = StateGraph(...)` at line 1358):

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
        answer = await deps.answer_slide_question(state)
        return {**state, "final_response": answer}
```

(e) Wire the node + edge (in the `build_report_subgraph` graph assembly, lines 1358-1388):

```python
    g.add_node("sl_qa", _sl_qa)
```

Add `"qa": "sl_qa"` to the `add_conditional_edges` route map (line 1371-1379) and `g.add_edge("sl_qa", END)` with the other terminal edges. (The route map's callable is now the module-level `_route_deck_command` from step (c), not a nested `_route`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report_qa_route.py -v`
Expected: PASS. Also run the existing report tests: `uv run pytest tests/test_report_pipeline.py tests/test_report_edit_fns.py -v` — PASS (no regression; the route map gained a branch but every prior action still maps to its node).

- [ ] **Step 5: Commit**

```bash
git add src/paperhub/agents/report_graph.py tests/test_report_qa_route.py
git commit -m "feat(slides): sl_qa node answers deck questions; remove default->edit_slides"
```

---

## Task 8: chat.py wires the `answer_slide_question` closure

**Files:**
- Modify: `src/paperhub/api/chat.py` (`report_stream` ~448-491 / `ReportDeps` construction ~465-476)
- Test: `tests/test_chat_slides_sse.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_slides_sse.py` (reuse the file's existing SSE-driving harness; the key is to drive a `slides` turn whose deck-command classifies as `qa` and assert the QA answer is the final content). If the file already monkeypatches `report_stream`, instead add a focused unit on the closure builder you extract in Step 3:

```python
async def test_answer_slide_question_closure_joins_paper_qa(monkeypatch) -> None:
    """The closure passed into ReportDeps runs paper_qa and returns joined text."""
    from paperhub.api import chat as chatmod
    from paperhub.agents.research import FinalOnlyMessage

    async def _fake_qa_stream(state, **_kwargs):
        yield "The graph "
        yield "shows X [chunk:9]."

    monkeypatch.setattr(chatmod, "paper_qa_stream", _fake_qa_stream)
    closure = chatmod._build_slide_qa_answerer(  # see Step 3
        adapter=object(), tracer=object(), model="m", conn=object(),
    )
    text = await closure({"session_id": 1})
    assert text == "The graph shows X [chunk:9]."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_slides_sse.py -k closure_joins -v`
Expected: FAIL — `AttributeError: module 'paperhub.api.chat' has no attribute '_build_slide_qa_answerer'`.

- [ ] **Step 3: Implement the closure + pass it to ReportDeps**

In `src/paperhub/api/chat.py`, add a module-level helper (near `report_stream`):

```python
def _build_slide_qa_answerer(
    *, adapter: Any, tracer: Tracer, model: str, conn: aiosqlite.Connection
) -> Any:
    """Return an async callable that answers a slide question via the shared
    paper_qa subgraph and returns the full text (FinalOnlyMessage content or the
    joined token stream). Trace steps land in tool_calls (drained end-of-turn).
    """
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

In `report_stream`, pass the closure into `ReportDeps` (after line 476's `slide_style_profile_name=...`):

```python
        answer_slide_question=_build_slide_qa_answerer(
            adapter=adapter, tracer=tracer,
            model=settings.paper_qa_model, conn=conn,
        ),
```

(`paper_qa_stream`, `ToolStepYield`, `FinalOnlyMessage` are already imported/defined in `chat.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chat_slides_sse.py -v`
Expected: PASS.

- [ ] **Step 5: Full backend gate**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/paperhub/api/chat.py tests/test_chat_slides_sse.py
git commit -m "feat(slides): wire paper_qa answerer into the slides qa guard"
```

---

## Task 9: Real-API `:8000` gate (phase-end, manual)

**This is the correctness gate — pytest proves wiring, not that the LLM obeys the new prompts. Run ONCE, after Tasks 1-8 are merged-ready.** Do NOT boot your own backend; use the user's live `:8000` (ask them to start it if `curl -s -m 3 http://127.0.0.1:8000/health` is unreachable).

- [ ] **Step 1: Confirm the backend is live**

Run: `curl -s -m 3 http://127.0.0.1:8000/health`
Expected: healthy response. If not, STOP and ask the user to start it.

- [ ] **Step 2: Reproduce the failing scenario (router path)**

Create a session, attach a paper, generate a deck, then ask the slide question:

```bash
# 1) new session
curl -s -X POST http://127.0.0.1:8000/sessions
# 2) add a paper (use one with a figure-bearing slide, e.g. an arXiv id)
curl -s -X POST http://127.0.0.1:8000/papers -H 'content-type: application/json' \
  -d '{"session_id": <SID>, "arxiv_id": "<ID>"}'
# 3) generate a deck
curl -s -N -X POST http://127.0.0.1:8000/chat -H 'content-type: application/json' \
  -d '{"session_id": <SID>, "user_message": "Make a 10-minute talk on this paper."}'
# 4) ask the slide question, with current_view_page set to a figure slide
curl -s -N -X POST http://127.0.0.1:8000/chat -H 'content-type: application/json' \
  -d '{"session_id": <SID>, "user_message": "可以幫我更詳細解釋這個圖嗎", "current_view_page": 5}'
```

- [ ] **Step 3: Verify the trace (router path)**

```powershell
# newest run for the session
uv run paperhub-replay --run-id <N>
```

Assert: `routing_decision.intent == "paper_qa"` (NOT `slides`); steps are `router:classify → research… → paper_qa:subagent → paper_qa:finalize`; **no `report:edit_frame` step**; the `paper_qa:subagent` `args_redacted_json.user_message` (or the dispatch record) contains the slide-context block (page + title + figure caption); the final answer cites real `[chunk:N]` ids.

- [ ] **Step 4: Verify the deck is untouched**

```sql
-- via sqlite3 backend/workspace/paperhub.db
SELECT slide_index, length(frame_tex) FROM deck_slides
  WHERE deck_id = (SELECT id FROM decks WHERE session_id = <SID>) ORDER BY slide_index;
```

Assert: identical to the values right after Step 2.3 (no frame rewritten). Confirm `decks.updated_at` did not change on the QA turn.

- [ ] **Step 5: Exercise the layer-2 guard**

Force the misroute by re-asking in a form the router may still send to `slides` (or temporarily set `PAPERHUB_ROUTER_MOCK` to a `slides` decision). Confirm the run shows `report:deck_command` with `action="qa"`, then `sl_qa`, a grounded answer, and **no** `report:edit_frame` / recompile.

- [ ] **Step 6: Human sign-off**

Ask the user to open the frontend, view the figure slide, ask "explain this graph", and confirm: (a) a grounded answer appears in chat with working `[chunk:N]` citations that open the Citation Canvas, and (b) the deck/Slides panel is unchanged.

- [ ] **Step 7: Finalize**

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR. The SRS entry stays as written (design recorded); no further SRS edit needed unless the gate surfaces a contract change.

---

## Self-Review

**Spec coverage:** ✅ active-slide context block (Task 2); retrieval anchor into paper_qa (Task 3); router rule + few-shot (Task 5); `action="qa"` + classifier few-shot (Task 6); `sl_qa` + removed default→edit_slides (Task 7); shared QA path / fully-answer guard (Tasks 7-8); `slide_context` threading (Task 4); figure-caption-only-when-present (Task 2 `_frame_figure_keys` branch); trace recording of resolved context (Task 3 via subagent `record_args`; Task 9 verifies); deck-byte-unchanged + grounded answer (Task 9). Out-of-scope items (cross-slide, edit+answer, TTS) are not implemented, as specified.

**Placeholder scan:** No placeholders. `_route` is lifted to a single module-level `_route_deck_command` (Task 7 Step 3c) that both the graph and the unit tests call — one source of truth, no test-only factory. Every step carries runnable code.

**Type consistency:** `build_slide_context(conn, *, session_id, current_view_page)` and `slide_aware_query(state)` signatures match across Tasks 2/3/4. `DeckCommand.action` Literal includes `"qa"` (Task 1) before it is produced (Task 6) or routed (Task 7). `ReportDeps.answer_slide_question` (Task 7) is the same name the closure is passed to (Task 8). `AgentState.slide_context` (Task 1) is written in Task 4 and read in Tasks 2/3.
