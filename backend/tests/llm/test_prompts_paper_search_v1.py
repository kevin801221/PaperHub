"""Regression coverage: paper_search/v1 YAML parses + uses namespaced tools.

v2.5-4 renamed bare tool names (``search_library``, …) to namespaced
``papers.search_library`` etc. so the prompt matches what
:meth:`MCPRegistry.aggregate_tool_schemas` advertises. This test pins that
contract.
"""
from __future__ import annotations

from paperhub.llm.prompts.registry import PromptRegistry


def test_paper_search_v1_parses() -> None:
    prompt = PromptRegistry().get("paper_search/v1")
    assert prompt.system
    assert prompt.user_template
    assert "{user_message}" in prompt.user_template
    assert "{references_block}" in prompt.user_template
    assert "{n_refs}" in prompt.user_template


def test_paper_search_v1_uses_namespaced_tool_names() -> None:
    system = PromptRegistry().get("paper_search/v1").system
    assert "papers.search_library" in system
    assert "papers.search_semantic_scholar" in system
    assert "papers.find_related_papers" in system


def test_paper_search_v1_has_no_bare_tool_names() -> None:
    """No straggling bare references like ``search_library(...`` without the
    ``papers.`` namespace prefix. Allows mentions in plain prose so long as
    the named call sites are namespaced.
    """
    system = PromptRegistry().get("paper_search/v1").system
    # Crude but effective: every "search_library(" occurrence should be
    # immediately preceded by "papers." in the source.
    for tool in ("search_library", "search_semantic_scholar", "find_related_papers"):
        call_marker = f"{tool}("
        idx = 0
        while True:
            found = system.find(call_marker, idx)
            if found == -1:
                break
            prefix = system[max(0, found - len("papers.")) : found]
            assert prefix == "papers.", (
                f"v1 prompt has bare {call_marker} at offset {found} "
                f"(prefix={prefix!r}); expected papers."
            )
            idx = found + len(call_marker)


def test_paper_search_v1_does_not_mention_web_tools() -> None:
    """The v1 prompt is the daemon-down variant — no ``web.*`` references."""
    system = PromptRegistry().get("paper_search/v1").system
    # Allow mentions of "web.*" / "web.search" only in the negative ("may or
    # may not be available") sense; but the v1 prompt SHOULD NOT call web.fetch
    # or web.search as tools.
    assert "web.fetch(" not in system
    # web.search may appear in a comment about availability — but as a callable
    # marker (web.search(...) inside the canonical flow) it should NOT.
    assert "web.search(query" not in system
