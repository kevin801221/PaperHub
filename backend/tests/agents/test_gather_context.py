"""Tests for the F4.5 Phase 6 ``gather_context`` per-paper subagent.

Covers:
- Happy path: LLM emits a final no-tool-calls JSON response; we get back a
  :class:`PaperContextBundle` with probed figure dimensions.
- Hard contract: a ``key_figures[*].key`` that is not in the deck-prefixed
  figure inventory is rejected at parse time (no hallucinated figures).

NOTE: The plan stub assumed a PaperAsset shape with ``source_dir`` /
``metadata`` / ``additional_tex`` keys. The real ``PaperAsset`` is the F2
ingestion dataclass (figures + equations + sections only). This test therefore
constructs the real dataclass and threads paper-row metadata + ADDITIONAL.tex
contents in as separate kwargs (matching how ``report_graph.py`` will call it).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from paperhub.agents.gather_context import run_gather_context
from paperhub.models.slide_domain import FigureDimensions
from paperhub.pipelines.paper_asset import (
    EquationAsset,
    FigureAsset,
    PaperAsset,
    SectionAsset,
    write_paper_asset,
)
from paperhub.tracing.tracer import Tracer


@pytest.fixture
def fake_asset(tmp_path: Path) -> tuple[PaperAsset, Path]:
    """Construct a minimal PaperAsset on disk + return (asset, source_dir).

    Writes one figure image so ``probe_figure_dimensions`` returns the real
    pixel size (1640x920) rather than the 1000x1000 fallback.
    """
    source_dir = tmp_path
    fig_dir = source_dir / "asset" / "figures"
    fig_dir.mkdir(parents=True)
    Image.new("RGB", (1640, 920)).save(fig_dir / "fig-001.png")
    asset = PaperAsset(
        figures=[
            FigureAsset(
                id="fig-001",
                caption="An overview of the method.",
                page=1,
                section="Method",
                image_path="figures/fig-001.png",
            ),
        ],
        equations=[
            EquationAsset(id="eq-001", latex=r"\Phi = \sum a", section="Method"),
        ],
        sections=[SectionAsset(name="Method", order=1)],
    )
    write_paper_asset(asset, source_dir)
    return asset, source_dir


def _bundle_payload(
    *,
    paper_id: int,
    paper_idx: int,
    figure_key: str = "p0-fig-001",
) -> dict[str, Any]:
    """Build a PaperContextBundle JSON payload the test LLM emits."""
    return {
        "paper_id": paper_id,
        "paper_idx": paper_idx,
        "title": "T",
        "authors": ["A"],
        "year": 2025,
        "narrative_summary": "Contribution: X. Method: Y. Results: 14% better.",
        "key_figures": [
            {
                "key": figure_key,
                "role": "overview",
                "one_line_interpretation": "An overview",
                "dimensions": {"width_px": 1640, "height_px": 920},
            }
        ],
        "key_equations": [
            {
                "latex": r"\Phi = \sum a",
                "role": "importance_score",
                "notation_legend": "Phi: score",
            }
        ],
        "section_excerpts": [],
        "paper_newcommands": ["\\newcommand{\\bm}{...}"],
    }


def _msg_no_tool_calls(content: str) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content, "tool_calls": []}}
        ]
    }


@pytest.mark.asyncio
async def test_gather_context_returns_bundle_with_probed_dimensions(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
) -> None:
    asset, source_dir = fake_asset
    payload = _bundle_payload(paper_id=42, paper_idx=0)
    llm = AsyncMock()
    llm.return_value = _msg_no_tool_calls(json.dumps(payload))

    bundle = await run_gather_context(
        paper_id=42,
        paper_idx=0,
        asset=asset,
        source_dir=source_dir,
        paper_title="T",
        paper_authors=["A"],
        paper_year=2025,
        paper_abstract="abs",
        paper_newcommands=["\\newcommand{\\bm}{...}"],
        conn=None,
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )

    assert bundle.paper_id == 42
    assert bundle.paper_idx == 0
    assert len(bundle.key_figures) == 1
    assert bundle.key_figures[0].dimensions == FigureDimensions(
        width_px=1640, height_px=920
    )


@pytest.mark.asyncio
async def test_gather_context_rejects_unknown_figure_key(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
) -> None:
    asset, source_dir = fake_asset
    payload = _bundle_payload(
        paper_id=42, paper_idx=0, figure_key="p0-fig-NOT-IN-INVENTORY"
    )
    llm = AsyncMock()
    llm.return_value = _msg_no_tool_calls(json.dumps(payload))

    with pytest.raises(ValueError, match="unknown figure key"):
        await run_gather_context(
            paper_id=42,
            paper_idx=0,
            asset=asset,
            source_dir=source_dir,
            paper_title="T",
            paper_authors=[],
            paper_year=2025,
            paper_abstract="abs",
            paper_newcommands=[],
            conn=None,
            tracer=fake_tracer,
            model="stub",
            llm_acompletion=llm,
        )


def _msg_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build a response message that emits a single tool_call."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_gather_context_budget_exhaustion_drops_tools_and_records_turn_log(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
    migrated_db,  # type: ignore[no-untyped-def]
) -> None:
    """When the LLM keeps calling tools and the budget is exhausted, the
    next acompletion call must NOT include ``tools`` (forcing the LLM to
    emit a final response). If it STILL emits no content, the function
    must raise RuntimeError + the tracer step must record the per-turn
    log so the failure is reconstruct-able from the DB alone (iron rule).
    """
    asset, source_dir = fake_asset
    llm = AsyncMock()
    # 3 tool calls burn the budget; the 4th call must omit tools, and the
    # LLM (mocked) emits empty content anyway → RuntimeError.
    llm.side_effect = [
        _msg_tool_call("list_sections", {}),
        _msg_tool_call("read_section", {"name": "Method"}),
        _msg_tool_call("read_section", {"name": "Results"}),
        _msg_no_tool_calls(""),
    ]

    with pytest.raises(RuntimeError, match="LLM never emitted"):
        await run_gather_context(
            paper_id=42,
            paper_idx=0,
            asset=asset,
            source_dir=source_dir,
            paper_title="T",
            paper_authors=["A"],
            paper_year=2025,
            paper_abstract="abs",
            paper_newcommands=[],
            conn=migrated_db,
            tracer=fake_tracer,
            model="stub",
            llm_acompletion=llm,
        )

    # The 4th call must NOT have offered tools (budget exhausted → no palette).
    assert llm.await_count == 4
    fourth_kwargs = llm.await_args_list[3].kwargs
    assert "tools" not in fourth_kwargs, (
        f"tools should be dropped on post-budget turn; got {fourth_kwargs!r}"
    )
    # The first 3 calls SHOULD have offered tools.
    for i in range(3):
        assert "tools" in llm.await_args_list[i].kwargs
        assert llm.await_args_list[i].kwargs["tool_choice"] == "auto"

    # The tracer step row must record per-turn state (iron rule: reconstruct
    # the failure from the DB alone, no re-run required).
    async with migrated_db.execute(
        "SELECT status, error, result_summary_json FROM tool_calls "
        "WHERE tool = ? ORDER BY step_index DESC LIMIT 1",
        ("report:gather_context",),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    status, error, result_json = row
    assert status == "error"
    # When the exception propagates out of the tracer step, the Tracer writes
    # str(exc) to the error column (overriding mark_error's forced_error). The
    # mark_error tag is still useful for callers that catch + don't re-raise.
    assert "LLM never emitted" in error
    result = json.loads(result_json)
    assert result["parse_error"] == "no_final_response_after_budget"
    assert result["callback_reads_count"] == 3
    assert result["max_callback_calls"] == 3
    assert result["turns_used"] == 4
    assert len(result["llm_turns"]) == 4
    # First three turns should have offered tools; the fourth should not.
    assert result["llm_turns"][0]["tools_offered"] is True
    assert result["llm_turns"][3]["tools_offered"] is False
    assert result["llm_turns"][3]["budget_exhausted"] is True


@pytest.mark.asyncio
async def test_gather_context_recovers_after_budget_when_llm_finally_emits(
    fake_asset: tuple[PaperAsset, Path],
    fake_tracer: Tracer,
    migrated_db,  # type: ignore[no-untyped-def]
) -> None:
    """LLM burns 3 callbacks then, on the no-tools turn, emits the final
    bundle JSON → run_gather_context returns a valid PaperContextBundle.
    """
    asset, source_dir = fake_asset
    payload = _bundle_payload(paper_id=42, paper_idx=0)
    llm = AsyncMock()
    llm.side_effect = [
        _msg_tool_call("list_sections", {}),
        _msg_tool_call("read_section", {"name": "Method"}),
        _msg_tool_call("read_section", {"name": "Method"}),
        _msg_no_tool_calls(json.dumps(payload)),
    ]

    bundle = await run_gather_context(
        paper_id=42,
        paper_idx=0,
        asset=asset,
        source_dir=source_dir,
        paper_title="T",
        paper_authors=["A"],
        paper_year=2025,
        paper_abstract="abs",
        paper_newcommands=[],
        conn=migrated_db,
        tracer=fake_tracer,
        model="stub",
        llm_acompletion=llm,
    )

    assert bundle.paper_id == 42
    assert bundle.paper_idx == 0
    assert llm.await_count == 4
    # Fourth call dropped tools.
    assert "tools" not in llm.await_args_list[3].kwargs
    # Success path also records the per-turn log.
    async with migrated_db.execute(
        "SELECT status, result_summary_json FROM tool_calls "
        "WHERE tool = ? ORDER BY step_index DESC LIMIT 1",
        ("report:gather_context",),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    status, result_json = row
    assert status == "ok"
    result = json.loads(result_json)
    assert len(result["llm_turns"]) == 4
