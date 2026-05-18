"""paper_search/v2 YAML — discover-then-refine variant with ``web.*`` tools.

v2 is loaded when the MCP registry advertises ``web.search`` (open-webSearch).
It teaches the agent to use ``web.search`` / ``web.fetch`` for discovery on
short / vague / indirect queries, then round-trip through
``papers.search_semantic_scholar`` for a citable hit.
"""
from __future__ import annotations

from paperhub.llm.prompts.registry import PromptRegistry


def test_paper_search_v2_parses() -> None:
    prompt = PromptRegistry().get("paper_search/v2")
    assert prompt.system
    assert prompt.user_template
    assert "{user_message}" in prompt.user_template
    assert "{references_block}" in prompt.user_template
    assert "{n_refs}" in prompt.user_template


def test_paper_search_v2_uses_namespaced_papers_tool_names() -> None:
    system = PromptRegistry().get("paper_search/v2").system
    assert "papers.search_library" in system
    assert "papers.search_semantic_scholar" in system
    assert "papers.find_related_papers" in system


def test_paper_search_v2_mentions_both_web_tools() -> None:
    system = PromptRegistry().get("paper_search/v2").system
    assert "web.search" in system
    assert "web.fetch" in system


def test_paper_search_v2_states_web_results_not_citable() -> None:
    """The prompt MUST make clear that ``web.*`` results are discovery-only
    and cannot enter the ``json:candidates`` block directly. Look for either
    of the two markers we chose to express that rule.
    """
    system = PromptRegistry().get("paper_search/v2").system
    has_discovery_only = "discovery-only" in system or "discovery only" in system
    has_not_citable = "NOT citable" in system or "not citable" in system
    assert has_discovery_only or has_not_citable, (
        "v2 prompt must mark web.* as discovery-only / not citable"
    )


def test_paper_search_v2_has_no_bare_tool_names() -> None:
    """Every ``search_library`` / ``search_semantic_scholar`` /
    ``find_related_papers`` invocation in the prompt is namespaced."""
    system = PromptRegistry().get("paper_search/v2").system
    for tool in ("search_library", "search_semantic_scholar", "find_related_papers"):
        call_marker = f"{tool}("
        idx = 0
        while True:
            found = system.find(call_marker, idx)
            if found == -1:
                break
            prefix = system[max(0, found - len("papers.")) : found]
            assert prefix == "papers.", (
                f"v2 prompt has bare {call_marker} at offset {found} "
                f"(prefix={prefix!r}); expected papers."
            )
            idx = found + len(call_marker)


def test_paper_search_v2_mentions_discover_then_refine_flow() -> None:
    """The canonical-flow section should describe the discover-then-refine
    trajectory: web.search → papers.search_semantic_scholar → candidates."""
    system = PromptRegistry().get("paper_search/v2").system
    # The worked example must show web.search feeding into a papers.* refine.
    # Look for the two markers in that order.
    web_idx = system.find("web.search")
    refine_idx = system.find("papers.search_semantic_scholar", web_idx + 1)
    assert web_idx != -1
    assert refine_idx != -1
    assert refine_idx > web_idx
