import aiosqlite

from paperhub.agents.router import router_node
from paperhub.agents.state import AgentState
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.tracing.tracer import Tracer


async def test_router_node_returns_routing_decision(
    migrated_db: aiosqlite.Connection,
) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1,
        "user_message": "Find recent papers on MoE routing",
    }
    adapter = LiteLlmAdapter()
    updated = await router_node(
        state,
        adapter=adapter,
        tracer=tracer,
        model="gpt-4o-mini",
        mock_response='{"intent":"paper_search","model_tier":"small",'
                      '"confidence":0.91,"reasoning":"asks to find"}',
    )
    assert updated["routing_decision"].intent == "paper_search"


async def test_router_persists_decision_on_run(
    migrated_db: aiosqlite.Connection,
) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1, "user_message": "hi",
    }
    adapter = LiteLlmAdapter()
    await router_node(
        state, adapter=adapter, tracer=tracer, model="gpt-4o-mini",
        mock_response='{"intent":"chitchat","model_tier":"small",'
                      '"confidence":0.8,"reasoning":"greeting"}',
    )
    async with migrated_db.execute(
        "SELECT routing_decision_json FROM runs WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert "chitchat" in row[0]


async def test_router_writes_tool_call_row(
    migrated_db: aiosqlite.Connection,
) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1, "user_message": "hi",
    }
    await router_node(
        state, adapter=LiteLlmAdapter(), tracer=tracer, model="gpt-4o-mini",
        mock_response='{"intent":"chitchat","model_tier":"small",'
                      '"confidence":0.8,"reasoning":"greeting"}',
    )
    async with migrated_db.execute(
        "SELECT agent, tool, status FROM tool_calls"
    ) as cur:
        rows = await cur.fetchall()
    assert rows == [("router", "classify", "ok")]
