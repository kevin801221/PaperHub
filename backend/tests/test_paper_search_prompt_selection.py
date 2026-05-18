"""Conditional dispatch of paper_search prompt v1 vs v2.

``get_paper_search_slot(mcp_registry)`` returns ``"paper_search/v2"`` when
the registry advertises ``web.search`` (open-webSearch), else
``"paper_search/v1"``.
"""
from __future__ import annotations

from typing import Any

import pytest

from paperhub.llm.prompts.registry import get_paper_search_slot

pytestmark = pytest.mark.asyncio


class _FakeMCPRegistry:
    def __init__(self, tool_names: list[str]) -> None:
        self._names = set(tool_names)

    async def has_tool(self, namespaced_name: str) -> bool:
        return namespaced_name in self._names


async def test_slot_is_v2_when_web_search_present() -> None:
    reg = _FakeMCPRegistry(
        tool_names=[
            "papers.search_library",
            "papers.search_semantic_scholar",
            "papers.find_related_papers",
            "web.search",
            "web.fetch",
        ],
    )
    slot = await get_paper_search_slot(reg)  # type: ignore[arg-type]
    assert slot == "paper_search/v2"


async def test_slot_is_v1_when_web_search_absent() -> None:
    reg = _FakeMCPRegistry(
        tool_names=[
            "papers.search_library",
            "papers.search_semantic_scholar",
            "papers.find_related_papers",
        ],
    )
    slot = await get_paper_search_slot(reg)  # type: ignore[arg-type]
    assert slot == "paper_search/v1"


async def test_slot_is_v1_when_only_web_fetch_present() -> None:
    """The selector hinges on ``web.search`` specifically (the discovery
    primitive). A registry advertising only ``web.fetch`` shouldn't promote
    the agent to v2 because the worked example assumes search-first."""
    reg = _FakeMCPRegistry(tool_names=["papers.search_library", "web.fetch"])
    slot = await get_paper_search_slot(reg)  # type: ignore[arg-type]
    assert slot == "paper_search/v1"


# ---------------------------------------------------------------------------
# End-to-end wiring: _build_paper_search_messages picks the right system prompt
# ---------------------------------------------------------------------------


async def test_build_paper_search_messages_uses_v2_with_web_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the MCP registry has ``web.search``, the messages should be seeded
    from the v2 prompt (system text mentions ``web.search``)."""
    from paperhub.agents import research

    captured: dict[str, Any] = {}

    async def _fake_refs_block(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
        return 0, ""

    monkeypatch.setattr(research, "_references_block", _fake_refs_block)

    reg = _FakeMCPRegistry(
        tool_names=["papers.search_library", "web.search", "web.fetch"],
    )
    state = {
        "run_id": 1,
        "branch": "",
        "session_id": 1,
        "user_message": "what's that diffusion paper everyone cites?",
    }
    messages = await research._build_paper_search_messages(
        state=state,  # type: ignore[arg-type]
        conn=captured,  # type: ignore[arg-type] — _references_block is stubbed
        mcp_registry=reg,  # type: ignore[arg-type]
    )
    system_msg = messages[0]
    assert system_msg["role"] == "system"
    assert "web.search" in system_msg["content"]


async def test_build_paper_search_messages_uses_v1_without_web_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paperhub.agents import research

    async def _fake_refs_block(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
        return 0, ""

    monkeypatch.setattr(research, "_references_block", _fake_refs_block)

    reg = _FakeMCPRegistry(tool_names=["papers.search_library"])
    state = {
        "run_id": 1,
        "branch": "",
        "session_id": 1,
        "user_message": "find me work on transformers",
    }
    messages = await research._build_paper_search_messages(
        state=state,  # type: ignore[arg-type]
        conn=None,  # type: ignore[arg-type] — _references_block is stubbed
        mcp_registry=reg,  # type: ignore[arg-type]
    )
    system_msg = messages[0]
    assert system_msg["role"] == "system"
    # v1 doesn't call web.search as a tool (no "web.search(" in system text).
    assert "web.search(query" not in system_msg["content"]
