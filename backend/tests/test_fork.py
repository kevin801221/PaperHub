from __future__ import annotations

from pathlib import Path

import aiosqlite

from paperhub.db.fork import fork_session
from paperhub.db.migrate import apply_schema


async def _seed_paper_content(conn: aiosqlite.Connection, *, title: str) -> int:
    cur = await conn.execute(
        "INSERT INTO paper_content "
        "(content_key, kind, arxiv_id, title, source_path, source_dir_path, html_path) "
        "VALUES (?, 'arxiv', ?, ?, '/x', '/x', '/x/h.html')",
        (f"arxiv:{title}", title, title),
    )
    await conn.commit()
    return int(cur.lastrowid)


async def _turn(conn: aiosqlite.Connection, sid: int, user: str, asst: str,
                *, routing: str | None = None, cards: str | None = None) -> int:
    """Create one run + a user message + an assistant message. Returns run_id."""
    cur = await conn.execute(
        "INSERT INTO runs (session_id, routing_decision_json, search_results_json, "
        "status) VALUES (?, ?, ?, 'ok')",
        (sid, routing, cards),
    )
    run_id = int(cur.lastrowid)
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) "
        "VALUES (?, 'user', ?, ?)", (sid, user, run_id))
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) "
        "VALUES (?, 'assistant', ?, ?)", (sid, asst, run_id))
    await conn.commit()
    return run_id


async def test_fork_copies_only_slice_above_point(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "first q", "first a", routing='{"intent":"chitchat"}')
        r2 = await _turn(conn, 1, "second q", "second a")  # <- fork point
        await _turn(conn, 1, "third q", "third a")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r2,
            workspace_dir=tmp_path,
        )

        assert res.new_session_id != 1
        assert res.forked_message == "second q"
        async with conn.execute(
            "SELECT title FROM chat_sessions WHERE id = ?", (res.new_session_id,)
        ) as cur:
            assert (await cur.fetchone())[0] == "Fork of Orig"

        async with conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (res.new_session_id,),
        ) as cur:
            rows = await cur.fetchall()
        assert rows == [("user", "first q"), ("assistant", "first a")]

        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 1") as cur:
            assert (await cur.fetchone())[0] == 6

        async with conn.execute(
            "SELECT DISTINCT run_id FROM messages WHERE session_id = ?",
            (res.new_session_id,),
        ) as cur:
            new_run_ids = {r[0] for r in await cur.fetchall()}
        assert new_run_ids and r1 not in new_run_ids
        async with conn.execute(
            "SELECT routing_decision_json FROM runs WHERE id = ?",
            (next(iter(new_run_ids)),),
        ) as cur:
            assert (await cur.fetchone())[0] == '{"intent":"chitchat"}'


async def test_fork_copies_papers_and_session_memories(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        pc1 = await _seed_paper_content(conn, title="P1")
        pc2 = await _seed_paper_content(conn, title="P2")
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled) VALUES (1, ?, 1)",
            (pc1,))
        await conn.execute(
            "INSERT INTO papers (session_id, paper_content_id, enabled) VALUES (1, ?, 0)",
            (pc2,))
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content) "
            "VALUES ('session', 1, 'reply in Japanese')")
        await conn.execute(
            "INSERT INTO memories (scope, session_id, content, status) "
            "VALUES ('session', 1, 'stale', 'superseded')")
        r1 = await _turn(conn, 1, "q", "a")
        await conn.commit()

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r1, workspace_dir=tmp_path)

        async with conn.execute(
            "SELECT paper_content_id, enabled FROM papers WHERE session_id = ? "
            "ORDER BY paper_content_id", (res.new_session_id,)) as cur:
            assert await cur.fetchall() == [(pc1, 1), (pc2, 0)]

        async with conn.execute(
            "SELECT content, scope, session_id, supersedes, superseded_by "
            "FROM memories WHERE session_id = ?", (res.new_session_id,)) as cur:
            mem = await cur.fetchall()
        assert mem == [("reply in Japanese", "session", res.new_session_id, None, None)]


async def test_fork_first_message_yields_empty_history(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        await conn.execute("INSERT INTO chat_sessions (title) VALUES ('Orig')")
        await conn.commit()
        r1 = await _turn(conn, 1, "only q", "only a")

        res = await fork_session(
            conn, source_session_id=1, fork_run_id=r1, workspace_dir=tmp_path)

        assert res.forked_message == "only q"
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (res.new_session_id,)) as cur:
            assert (await cur.fetchone())[0] == 0
