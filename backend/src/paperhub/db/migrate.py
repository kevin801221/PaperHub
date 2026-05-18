from importlib.resources import files

import aiosqlite


async def apply_schema(conn: aiosqlite.Connection) -> None:
    sql = (files("paperhub.db") / "schema.sql").read_text(encoding="utf-8")
    await conn.executescript(sql)
    # executescript auto-commits; no explicit commit needed here.

    # Rebuild the FTS index from paper_content if the index is empty
    # but the source table has rows (handles upgrades from pre-FTS schemas).
    async with conn.execute("SELECT COUNT(*) FROM paper_content") as cur:
        pc_row = await cur.fetchone()
    pc_count: int = int(pc_row[0]) if pc_row is not None else 0
    async with conn.execute("SELECT COUNT(*) FROM paper_content_fts") as cur:
        fts_row = await cur.fetchone()
    fts_count: int = int(fts_row[0]) if fts_row is not None else 0
    if pc_count > 0 and fts_count == 0:
        await conn.execute(
            "INSERT INTO paper_content_fts(paper_content_fts) VALUES ('rebuild')"
        )
        await conn.commit()
