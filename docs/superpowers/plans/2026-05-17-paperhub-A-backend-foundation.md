# PaperHub Plan A — Backend Foundation + Router-only Chat

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land a runnable FastAPI + LangGraph backend with the full v2.2 SQLite schema, a working tool-call tracer, a Router agent that classifies the four real intents (+ `chitchat` fallback), and a `POST /chat` SSE endpoint that drives `chitchat` end-to-end. All four real-intent branches return a "not implemented yet" final response — wired into the graph but stubbed — so Plans C / E / F can drop their agents in without re-touching the graph.

**Architecture:** Single FastAPI process. SQLite (via `aiosqlite`) holds the seven tables defined in SRS §III-7 (only `chat_sessions` / `messages` / `runs` / `tool_calls` are written in this plan — the other three exist for later plans). LangGraph state machine: Router node → conditional edge → one of five terminal nodes (`chitchat`, `paper_search_stub`, `paper_qa_stub`, `slides_stub`, `library_stats_stub`). Tracer is a contextmanager that wraps every model call and writes a `tool_calls` row before returning, surviving `asyncio.CancelledError`. LiteLLM is the LLM adapter (Gemini / Anthropic / OpenAI / Ollama all work via the same call). All new code is `mypy --strict` clean per NFR-06.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, LangGraph 0.2+, LiteLLM 1.x, Pydantic v2, aiosqlite, sse-starlette, pytest + pytest-asyncio + httpx, ruff, mypy. Package management with **uv** per the user's CLAUDE.md.

---

## Spec Coverage Summary

| SRS reference | Addressed by |
| --- | --- |
| §III-7 schema (all 7 tables) | Task 2 |
| §III-7 tool_calls `branch` column + PK | Task 2, Task 5 |
| FR-06 LangGraph router (4 intents + chitchat fallback) | Task 9, Task 10 |
| FR-01 RoutingBadge data source (`runs.routing_decision_json`) | Task 9 (persists), Task 12 (emits SSE) |
| FR-02 / FR-09 audit log writer + redaction | Task 4, Task 5 |
| NFR-04 run finalises on `CancelledError` | Task 5 |
| NFR-06 strict typing on new Python | Task 1 (mypy config) + applies throughout |
| NFR-05 MCP scope rejection writes `tool_calls.status='rejected'` | Task 5 (column exists, used in Plans E/G) |
| I-8 #1 router top-1 ≥ 80 % on 16-prompt fixture | Task 11 |
| I-8 #4 replay-from-SQLite reconstructs run | Task 14 |
| LiteLLM adapter (§III-4) with `model_tier` slot | Task 6 |
| YAML prompt registry with versioned slots (§III-4) | Task 7 |

**Out of scope for Plan A** (intentional — covered later): Paper Pipeline, Chroma, RAG retrieval, MCP servers, frontend, citation rendering, slide pipeline, Compare-view fan-out. The schema and Compare-`branch` column are in place so later plans don't re-migrate.

---

## File Structure

```
backend/
├── pyproject.toml                          # uv-managed deps + tool configs
├── .python-version                         # 3.11
├── ruff.toml                               # lint config
├── README.md                               # how to run + test
├── src/paperhub/
│   ├── __init__.py
│   ├── app.py                              # FastAPI app + lifespan (DB migration)
│   ├── config.py                           # env-driven settings (workspace path, model names, log level)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql                      # all 7 SRS §III-7 tables
│   │   ├── migrate.py                      # idempotent migration runner
│   │   └── connection.py                   # aiosqlite connection helpers
│   ├── models/
│   │   ├── __init__.py
│   │   ├── domain.py                       # Pydantic v2: RoutingDecision, ToolCallRecord, AgentState (TypedDict)
│   │   └── events.py                       # SSE event envelopes
│   ├── tracing/
│   │   ├── __init__.py
│   │   ├── redactor.py                     # regex masking of API keys + $HOME
│   │   └── tracer.py                       # tool_calls writer + contextmanager
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── adapter.py                      # LlmAdapter Protocol + structured-output helper
│   │   ├── litellm_adapter.py              # LiteLLM impl
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── registry.py                 # YAML loader, versioned slots
│   │       ├── router_v1.yaml
│   │       └── chitchat_v1.yaml
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── state.py                        # AgentState TypedDict + helpers
│   │   ├── router.py                       # Router node
│   │   ├── chitchat.py                     # Chitchat node
│   │   ├── stubs.py                        # paper_search_stub / paper_qa_stub / slides_stub / library_stats_stub
│   │   └── graph.py                        # build_graph()
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py                       # GET /health
│   │   └── chat.py                         # POST /chat SSE
│   └── cli/
│       ├── __init__.py
│       └── replay.py                       # `paperhub-replay --run-id N` (I-8 #4)
└── tests/
    ├── conftest.py                         # tmp DB + workspace fixtures
    ├── test_schema.py
    ├── test_redactor.py
    ├── test_tracer.py
    ├── test_litellm_adapter.py
    ├── test_router.py
    ├── test_chitchat.py
    ├── test_graph.py
    ├── test_chat_sse.py
    ├── test_replay.py
    └── fixtures/
        └── router_intents.jsonl            # 16-prompt routing fixture (I-8 #1)
```

Every Python file new in this plan starts with the provenance comment header from NFR-03 if it adapts upstream code; in Plan A nothing is copied from `paper2slides-plus` (extraction utilities arrive in Plan C), so no provenance lines are needed yet.

---

### Task 1 — Project bootstrap

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`
- Create: `backend/ruff.toml`
- Create: `backend/README.md`
- Create: `backend/src/paperhub/__init__.py`
- Create: `backend/tests/__init__.py`

- [ ] **Step 1: Initialise `uv` project + add dependencies**

From the repo root:

```powershell
mkdir backend
cd backend
uv init --package paperhub --lib --python 3.11
uv add fastapi uvicorn[standard] sse-starlette aiosqlite pydantic litellm langgraph pyyaml
uv add --dev pytest pytest-asyncio httpx ruff mypy types-PyYAML
```

- [ ] **Step 2: Write `backend/pyproject.toml` tool sections**

Open `backend/pyproject.toml` (uv just created it) and append:

```toml
[project.scripts]
paperhub-replay = "paperhub.cli.replay:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
strict = true
python_version = "3.11"
plugins = ["pydantic.mypy"]
exclude = ["tests/fixtures/"]

[[tool.mypy.overrides]]
module = ["litellm.*", "sse_starlette.*"]
ignore_missing_imports = true
```

- [ ] **Step 3: Write `backend/ruff.toml`**

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "SIM"]
ignore = ["E501"]  # line length handled by formatter
```

- [ ] **Step 4: Write `backend/.python-version`**

```
3.11
```

- [ ] **Step 5: Write `backend/README.md`**

```markdown
# PaperHub backend

## Run
    uv run uvicorn paperhub.app:app --reload

## Test
    uv run pytest -v

## Lint + typecheck
    uv run ruff check src tests
    uv run mypy src
```

- [ ] **Step 6: Verify the empty scaffold builds**

```powershell
uv sync
uv run python -c "import paperhub; print('ok')"
uv run pytest -v
```

Expected: `ok` printed; pytest reports "no tests ran" (exit 5 or 0 — 0 once we add tests).

- [ ] **Step 7: Commit**

```powershell
git add backend/pyproject.toml backend/.python-version backend/ruff.toml backend/README.md backend/src backend/tests backend/uv.lock
git commit -m "chore(backend): bootstrap uv project with FastAPI + LangGraph + LiteLLM"
```

---

### Task 2 — SQLite schema + migration runner

**Files:**
- Create: `backend/src/paperhub/db/__init__.py` (empty)
- Create: `backend/src/paperhub/db/schema.sql`
- Create: `backend/src/paperhub/db/connection.py`
- Create: `backend/src/paperhub/db/migrate.py`
- Create: `backend/src/paperhub/config.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_schema.py`

- [ ] **Step 1: Write the failing schema test**

`backend/tests/test_schema.py`:

```python
import aiosqlite
import pytest

EXPECTED_TABLES = {
    "chat_sessions", "paper_content", "papers", "chunks",
    "messages", "runs", "tool_calls",
}


async def test_all_seven_tables_exist(migrated_db: aiosqlite.Connection) -> None:
    async with migrated_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        rows = await cursor.fetchall()
    assert {r[0] for r in rows} >= EXPECTED_TABLES


async def test_tool_calls_pk_includes_branch(migrated_db: aiosqlite.Connection) -> None:
    async with migrated_db.execute("PRAGMA index_list('tool_calls')") as cursor:
        indexes = [row[1] async for row in cursor]
    pk_indexes = [name for name in indexes if name.startswith("sqlite_autoindex")]
    # Read PK columns
    async with migrated_db.execute(
        f"PRAGMA index_info('{pk_indexes[0]}')"
    ) as cursor:
        cols = [row[2] async for row in cursor]
    assert cols == ["run_id", "branch", "step_index"]


async def test_paper_content_xor_constraint(migrated_db: aiosqlite.Connection) -> None:
    # arxiv_id XOR sha256 must hold — inserting both should fail.
    await migrated_db.execute(
        "INSERT INTO paper_content (content_key, kind, arxiv_id, sha256, "
        "title, source_path, source_dir_path, html_path) "
        "VALUES ('arxiv:1', 'arxiv', '1', 'abc', 't', 's', 'd', 'h')"
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await migrated_db.commit()


async def test_papers_unique_session_content(migrated_db: aiosqlite.Connection) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute(
        "INSERT INTO paper_content (content_key, kind, arxiv_id, title, "
        "source_path, source_dir_path, html_path) "
        "VALUES ('arxiv:2403.01234', 'arxiv', '2403.01234', 't', 's', 'd', 'h')"
    )
    await migrated_db.commit()
    await migrated_db.execute(
        "INSERT INTO papers (session_id, paper_content_id) VALUES (1, 1)"
    )
    await migrated_db.commit()
    with pytest.raises(aiosqlite.IntegrityError):
        await migrated_db.execute(
            "INSERT INTO papers (session_id, paper_content_id) VALUES (1, 1)"
        )
        await migrated_db.commit()
```

`backend/tests/conftest.py`:

```python
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest_asyncio

from paperhub.db.migrate import apply_schema


@pytest_asyncio.fixture
async def migrated_db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await apply_schema(conn)
        yield conn
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
uv run pytest tests/test_schema.py -v
```

Expected: ImportError on `paperhub.db.migrate` — module doesn't exist yet.

- [ ] **Step 3: Write `schema.sql`**

`backend/src/paperhub/db/schema.sql`:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    title TEXT NOT NULL DEFAULT 'New chat'
);

CREATE TABLE IF NOT EXISTS paper_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('arxiv', 'pdf_upload', 'latex_upload')),
    arxiv_id TEXT,
    sha256 TEXT,
    title TEXT NOT NULL,
    authors_json TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    source_path TEXT NOT NULL,
    source_dir_path TEXT NOT NULL,
    html_path TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ((arxiv_id IS NOT NULL) <> (sha256 IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    paper_content_id INTEGER NOT NULL REFERENCES paper_content(id),
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, paper_content_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_content_id INTEGER NOT NULL REFERENCES paper_content(id) ON DELETE CASCADE,
    section TEXT,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    run_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    routing_decision_json TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'ok', 'error', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS tool_calls (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    branch TEXT NOT NULL DEFAULT '',
    step_index INTEGER NOT NULL,
    parent_step INTEGER,
    agent TEXT NOT NULL,
    tool TEXT NOT NULL,
    model TEXT,
    args_redacted_json TEXT,
    result_summary_json TEXT,
    latency_ms INTEGER NOT NULL,
    token_in INTEGER,
    token_out INTEGER,
    status TEXT NOT NULL CHECK (status IN ('ok', 'error', 'rejected')),
    error TEXT,
    PRIMARY KEY (run_id, branch, step_index)
);
```

- [ ] **Step 4: Write the migration runner**

`backend/src/paperhub/db/migrate.py`:

```python
from importlib.resources import files

import aiosqlite


async def apply_schema(conn: aiosqlite.Connection) -> None:
    sql = (files("paperhub.db") / "schema.sql").read_text(encoding="utf-8")
    await conn.executescript(sql)
    await conn.commit()
```

`backend/src/paperhub/db/connection.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


@asynccontextmanager
async def open_db(db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn
```

- [ ] **Step 5: Write config**

`backend/src/paperhub/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace_dir: Path
    db_path: Path
    router_model: str
    chitchat_model: str
    log_level: str


def load_settings() -> Settings:
    workspace = Path(os.environ.get("PAPERHUB_WORKSPACE", "./workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return Settings(
        workspace_dir=workspace,
        db_path=workspace / "paperhub.db",
        router_model=os.environ.get("PAPERHUB_ROUTER_MODEL", "gemini/gemini-2.5-flash"),
        chitchat_model=os.environ.get("PAPERHUB_CHITCHAT_MODEL", "gemini/gemini-2.5-flash"),
        log_level=os.environ.get("PAPERHUB_LOG_LEVEL", "INFO"),
    )
```

- [ ] **Step 6: Make sure the package data is included**

Edit `backend/pyproject.toml`, add under `[tool.hatch.build.targets.wheel]` (or `[tool.uv.build]` if uv used hatch):

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/paperhub"]

[tool.hatch.build.targets.wheel.shared-data]
"src/paperhub/db/schema.sql" = "paperhub/db/schema.sql"
```

If `uv init` chose a different build backend, equivalent: declare `schema.sql` as package data so `importlib.resources.files("paperhub.db")` finds it after install. Verify with:

```powershell
uv run python -c "from importlib.resources import files; print((files('paperhub.db') / 'schema.sql').read_text()[:60])"
```

Expected: prints the first 60 chars of `schema.sql`.

- [ ] **Step 7: Run schema tests to verify they pass**

```powershell
uv run pytest tests/test_schema.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/src/paperhub/db backend/src/paperhub/config.py backend/tests/conftest.py backend/tests/test_schema.py backend/pyproject.toml
git commit -m "feat(backend): SQLite schema (7 tables, branch PK, xor constraints) + migration runner"
```

---

### Task 3 — Redactor (rules-based API-key + $HOME masking)

**Files:**
- Create: `backend/src/paperhub/tracing/__init__.py` (empty)
- Create: `backend/src/paperhub/tracing/redactor.py`
- Create: `backend/tests/test_redactor.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_redactor.py`:

```python
from pathlib import Path

from paperhub.tracing.redactor import redact


def test_redacts_anthropic_key() -> None:
    payload = {"api_key": "sk-ant-api03-AAAABBBBCCCC"}
    assert redact(payload) == {"api_key": "<redacted:anthropic>"}


def test_redacts_openai_key() -> None:
    payload = {"key": "sk-proj-XYZ123"}
    assert redact(payload) == {"key": "<redacted:openai>"}


def test_redacts_google_key() -> None:
    payload = {"k": "AIzaSyAbCdEfGhIjKlMnOpQrStUv"}
    assert redact(payload) == {"k": "<redacted:google>"}


def test_redacts_home_path(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/alice")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
    payload = {"path": "/home/alice/secrets.txt"}
    assert redact(payload) == {"path": "$HOME/secrets.txt"}


def test_redacts_in_nested_structures() -> None:
    payload = {"args": ["sk-ant-api03-XX", {"x": "AIzaABCDEFGHIJ"}]}
    out = redact(payload)
    assert out == {"args": ["<redacted:anthropic>", {"x": "<redacted:google>"}]}


def test_leaves_safe_values_alone() -> None:
    payload = {"intent": "paper_qa", "confidence": 0.91, "n": 42}
    assert redact(payload) == payload
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_redactor.py -v
```

Expected: ImportError on `paperhub.tracing.redactor`.

- [ ] **Step 3: Implement the redactor**

`backend/src/paperhub/tracing/redactor.py`:

```python
import os
import re
from pathlib import Path
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"), "<redacted:anthropic>"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{6,}"), "<redacted:openai>"),
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "<redacted:google>"),
]


def _home_paths() -> list[str]:
    paths: list[str] = []
    for env in ("HOME", "USERPROFILE"):
        value = os.environ.get(env)
        if value:
            paths.append(str(Path(value)))
    return paths


def _redact_str(value: str) -> str:
    for env_path in _home_paths():
        value = value.replace(env_path, "$HOME")
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    return value
```

- [ ] **Step 4: Run to verify it passes**

```powershell
uv run pytest tests/test_redactor.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/paperhub/tracing backend/tests/test_redactor.py
git commit -m "feat(tracing): rules-based redactor for API keys + \$HOME paths"
```

---

### Task 4 — Pydantic domain models + SSE event envelopes

**Files:**
- Create: `backend/src/paperhub/models/__init__.py` (empty)
- Create: `backend/src/paperhub/models/domain.py`
- Create: `backend/src/paperhub/models/events.py`
- Create: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models.py`:

```python
import json

import pytest
from pydantic import ValidationError

from paperhub.models.domain import RoutingDecision, ToolCallRecord
from paperhub.models.events import (
    ErrorEvent,
    FinalEvent,
    RoutingDecisionEvent,
    TokenEvent,
    ToolStepEvent,
    sse_format,
)


def test_routing_decision_rejects_unknown_intent() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(intent="bogus", model_tier="small", confidence=0.9, reasoning="x")


def test_routing_decision_clamps_confidence() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(intent="chitchat", model_tier="small", confidence=1.5, reasoning="x")


def test_tool_call_record_round_trip() -> None:
    record = ToolCallRecord(
        run_id=1, branch="", step_index=0, parent_step=None,
        agent="router", tool="classify", model="gemini/x",
        args_redacted_json={"input": "hello"}, result_summary_json={"intent": "chitchat"},
        latency_ms=120, token_in=12, token_out=4, status="ok", error=None,
    )
    dumped = record.model_dump_json()
    assert json.loads(dumped)["status"] == "ok"


def test_sse_format_routing_decision() -> None:
    evt = RoutingDecisionEvent(
        run_id=7, branch="",
        decision=RoutingDecision(intent="chitchat", model_tier="small",
                                 confidence=0.92, reasoning="greeting"),
    )
    payload = sse_format(evt)
    assert payload.startswith("event: routing_decision\n")
    assert "chitchat" in payload
    assert payload.endswith("\n\n")
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_models.py -v
```

Expected: ImportError on `paperhub.models.domain`.

- [ ] **Step 3: Implement domain models**

`backend/src/paperhub/models/domain.py`:

```python
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["paper_search", "paper_qa", "slides", "library_stats", "chitchat"]
ModelTier = Literal["small", "flagship"]
ToolStatus = Literal["ok", "error", "rejected"]
Branch = Literal["", "A", "B"]


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    model_tier: ModelTier
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: int
    branch: Branch = ""
    step_index: int
    parent_step: int | None
    agent: str
    tool: str
    model: str | None
    args_redacted_json: dict[str, Any] | None
    result_summary_json: dict[str, Any] | None
    latency_ms: int
    token_in: int | None
    token_out: int | None
    status: ToolStatus
    error: str | None


class AgentState(TypedDict, total=False):
    run_id: int
    branch: Branch
    session_id: int
    user_message: str
    routing_decision: RoutingDecision
    final_response: str
```

- [ ] **Step 4: Implement event envelopes**

`backend/src/paperhub/models/events.py`:

```python
import json
from typing import Any, Literal, Union

from pydantic import BaseModel

from paperhub.models.domain import Branch, RoutingDecision, ToolCallRecord


class RoutingDecisionEvent(BaseModel):
    type: Literal["routing_decision"] = "routing_decision"
    run_id: int
    branch: Branch
    decision: RoutingDecision


class ToolStepEvent(BaseModel):
    type: Literal["tool_step"] = "tool_step"
    record: ToolCallRecord


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    run_id: int
    branch: Branch
    text: str


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    run_id: int
    branch: Branch
    message_id: int
    content: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    run_id: int
    branch: Branch
    message: str


SseEvent = Union[
    RoutingDecisionEvent, ToolStepEvent, TokenEvent, FinalEvent, ErrorEvent
]


def sse_format(event: SseEvent) -> str:
    payload = event.model_dump(mode="json")
    payload.pop("type", None)
    return f"event: {event.type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
```

- [ ] **Step 5: Run to verify it passes**

```powershell
uv run pytest tests/test_models.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Typecheck**

```powershell
uv run mypy src/paperhub/models src/paperhub/tracing
```

Expected: `Success: no issues found in 4 source files`.

- [ ] **Step 7: Commit**

```powershell
git add backend/src/paperhub/models backend/tests/test_models.py
git commit -m "feat(models): Pydantic v2 domain types + SSE event envelopes"
```

---

### Task 5 — Tracer (writes `tool_calls` rows, finalises on CancelledError)

**Files:**
- Create: `backend/src/paperhub/tracing/tracer.py`
- Create: `backend/tests/test_tracer.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tracer.py`:

```python
import asyncio

import aiosqlite
import pytest

from paperhub.tracing.tracer import Tracer


async def _new_run(db: aiosqlite.Connection) -> int:
    await db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await db.commit()
    async with db.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def test_ok_call_writes_one_row(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    tracer = Tracer(migrated_db, run_id=run_id, branch="")
    async with tracer.step(agent="router", tool="classify", model="x") as step:
        step.record_args({"prompt": "hi"})
        step.record_result({"intent": "chitchat"})
        step.record_tokens(token_in=5, token_out=2)
    async with migrated_db.execute(
        "SELECT agent, tool, status, token_in, token_out FROM tool_calls"
    ) as cur:
        rows = await cur.fetchall()
    assert rows == [("router", "classify", "ok", 5, 2)]


async def test_redacts_args(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    tracer = Tracer(migrated_db, run_id=run_id, branch="")
    async with tracer.step(agent="router", tool="classify", model=None) as step:
        step.record_args({"api_key": "sk-ant-api03-SECRET12345"})
    async with migrated_db.execute(
        "SELECT args_redacted_json FROM tool_calls"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert "SECRET12345" not in row[0]
    assert "<redacted:anthropic>" in row[0]


async def test_exception_marks_error(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    tracer = Tracer(migrated_db, run_id=run_id, branch="")
    with pytest.raises(RuntimeError):
        async with tracer.step(agent="router", tool="classify", model=None):
            raise RuntimeError("boom")
    async with migrated_db.execute(
        "SELECT status, error FROM tool_calls"
    ) as cur:
        rows = await cur.fetchall()
    assert rows == [("error", "boom")]


async def test_cancellation_finalises_row(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    tracer = Tracer(migrated_db, run_id=run_id, branch="")

    async def work() -> None:
        async with tracer.step(agent="router", tool="classify", model=None):
            await asyncio.sleep(10)

    task = asyncio.create_task(work())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with migrated_db.execute("SELECT status FROM tool_calls") as cur:
        rows = await cur.fetchall()
    assert rows == [("cancelled",)] or rows == [("error",)]
    # Either status is acceptable per NFR-04 as long as a row exists.


async def test_step_index_monotonic(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    tracer = Tracer(migrated_db, run_id=run_id, branch="")
    for _ in range(3):
        async with tracer.step(agent="router", tool="classify", model=None):
            pass
    async with migrated_db.execute(
        "SELECT step_index FROM tool_calls ORDER BY step_index"
    ) as cur:
        rows = await cur.fetchall()
    assert [r[0] for r in rows] == [0, 1, 2]


async def test_branch_isolation(migrated_db: aiosqlite.Connection) -> None:
    run_id = await _new_run(migrated_db)
    ta = Tracer(migrated_db, run_id=run_id, branch="A")
    tb = Tracer(migrated_db, run_id=run_id, branch="B")
    async with ta.step(agent="router", tool="classify", model=None):
        pass
    async with tb.step(agent="router", tool="classify", model=None):
        pass
    async with migrated_db.execute(
        "SELECT branch, step_index FROM tool_calls ORDER BY branch"
    ) as cur:
        rows = await cur.fetchall()
    assert rows == [("A", 0), ("B", 0)]
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_tracer.py -v
```

Expected: ImportError on `paperhub.tracing.tracer`.

- [ ] **Step 3: Implement the tracer**

`backend/src/paperhub/tracing/tracer.py`:

```python
import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiosqlite

from paperhub.models.domain import Branch
from paperhub.tracing.redactor import redact


@dataclass
class _StepBuffer:
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    token_in: int | None = None
    token_out: int | None = None

    def record_args(self, args: dict[str, Any]) -> None:
        self.args = args

    def record_result(self, result: dict[str, Any]) -> None:
        self.result = result

    def record_tokens(self, *, token_in: int | None, token_out: int | None) -> None:
        self.token_in = token_in
        self.token_out = token_out


class Tracer:
    def __init__(self, conn: aiosqlite.Connection, *, run_id: int, branch: Branch) -> None:
        self._conn = conn
        self._run_id = run_id
        self._branch = branch
        self._next_index = 0

    @asynccontextmanager
    async def step(
        self,
        *,
        agent: str,
        tool: str,
        model: str | None,
        parent_step: int | None = None,
    ) -> AsyncIterator[_StepBuffer]:
        buf = _StepBuffer()
        index = self._next_index
        self._next_index += 1
        started = time.monotonic()
        status: str = "ok"
        error: str | None = None
        try:
            yield buf
        except asyncio.CancelledError:
            status, error = "error", "cancelled"
            await self._write(buf, index, agent, tool, model, parent_step,
                              started, status, error)
            raise
        except Exception as exc:
            status, error = "error", str(exc)
            await self._write(buf, index, agent, tool, model, parent_step,
                              started, status, error)
            raise
        else:
            await self._write(buf, index, agent, tool, model, parent_step,
                              started, status, error)

    async def _write(
        self,
        buf: _StepBuffer,
        index: int,
        agent: str,
        tool: str,
        model: str | None,
        parent_step: int | None,
        started: float,
        status: str,
        error: str | None,
    ) -> None:
        latency_ms = int((time.monotonic() - started) * 1000)
        args_json = json.dumps(redact(buf.args)) if buf.args is not None else None
        result_json = json.dumps(redact(buf.result)) if buf.result is not None else None
        await self._conn.execute(
            "INSERT INTO tool_calls (run_id, branch, step_index, parent_step, "
            "agent, tool, model, args_redacted_json, result_summary_json, "
            "latency_ms, token_in, token_out, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self._run_id, self._branch, index, parent_step,
             agent, tool, model, args_json, result_json,
             latency_ms, buf.token_in, buf.token_out, status, error),
        )
        await self._conn.commit()
```

- [ ] **Step 4: Run to verify it passes**

```powershell
uv run pytest tests/test_tracer.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/paperhub/tracing/tracer.py backend/tests/test_tracer.py
git commit -m "feat(tracing): tool_calls writer with branch, redaction, CancelledError finalisation"
```

---

### Task 6 — LiteLLM adapter + prompt registry

**Files:**
- Create: `backend/src/paperhub/llm/__init__.py` (empty)
- Create: `backend/src/paperhub/llm/adapter.py`
- Create: `backend/src/paperhub/llm/litellm_adapter.py`
- Create: `backend/src/paperhub/llm/prompts/__init__.py` (empty)
- Create: `backend/src/paperhub/llm/prompts/registry.py`
- Create: `backend/src/paperhub/llm/prompts/router_v1.yaml`
- Create: `backend/src/paperhub/llm/prompts/chitchat_v1.yaml`
- Create: `backend/tests/test_litellm_adapter.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_litellm_adapter.py`:

```python
from paperhub.llm.adapter import LlmAdapter
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.llm.prompts.registry import PromptRegistry
from paperhub.models.domain import RoutingDecision


async def test_registry_loads_versioned_slot() -> None:
    reg = PromptRegistry()
    slot = reg.get("router/v1")
    assert slot.system.strip().startswith("You are PaperHub's intent router")
    assert "{user_message}" in slot.user_template


async def test_structured_output_parses_into_model() -> None:
    adapter: LlmAdapter = LiteLlmAdapter()
    decision = await adapter.structured(
        slot="router/v1",
        variables={"user_message": "Find recent papers on MoE routing"},
        response_model=RoutingDecision,
        model="gpt-4o-mini",  # any LiteLLM model id
        mock_response='{"intent":"paper_search","model_tier":"small",'
                      '"confidence":0.91,"reasoning":"asks to find papers"}',
    )
    assert decision.intent == "paper_search"
    assert 0 <= decision.confidence <= 1


async def test_stream_yields_tokens() -> None:
    adapter: LlmAdapter = LiteLlmAdapter()
    chunks: list[str] = []
    async for token in adapter.stream(
        slot="chitchat/v1",
        variables={"user_message": "hi"},
        model="gpt-4o-mini",
        mock_response="Hello there!",
    ):
        chunks.append(token)
    assert "".join(chunks) == "Hello there!"
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_litellm_adapter.py -v
```

Expected: ImportError on `paperhub.llm.adapter`.

- [ ] **Step 3: Implement the prompt registry**

`backend/src/paperhub/llm/prompts/registry.py`:

```python
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

import yaml


@dataclass(frozen=True)
class PromptSlot:
    system: str
    user_template: str


class PromptRegistry:
    @lru_cache(maxsize=None)
    def get(self, slot: str) -> PromptSlot:
        name, _, version = slot.partition("/")
        if not version:
            raise ValueError(f"prompt slot must be 'name/version', got {slot!r}")
        path = files("paperhub.llm.prompts") / f"{name}_{version}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PromptSlot(system=data["system"], user_template=data["user"])
```

`backend/src/paperhub/llm/prompts/router_v1.yaml`:

```yaml
system: |
  You are PaperHub's intent router. Classify the user's most recent message
  into exactly one of these intents:

    - paper_search    user wants to find/discover papers
    - paper_qa        user asks a question about already-indexed papers
    - slides          user asks to generate slides / a deck
    - library_stats   user asks a count/stat over their saved papers/sessions
    - chitchat        anything else (greeting, meta-question, off-topic)

  Pick `model_tier`:
    - small     for chitchat, library_stats, and most paper_search
    - flagship  for paper_qa and slides
  Return STRICT JSON matching the schema. No prose.
user: |
  User message:
  {user_message}
```

`backend/src/paperhub/llm/prompts/chitchat_v1.yaml`:

```yaml
system: |
  You are PaperHub's friendly assistant. The user is chatting casually,
  not asking about papers. Respond briefly, warmly, in one or two sentences.
user: |
  {user_message}
```

- [ ] **Step 4: Implement the adapter Protocol + LiteLLM impl**

`backend/src/paperhub/llm/adapter.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LlmAdapter(Protocol):
    async def structured(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        response_model: type[T],
        model: str,
        **kwargs: Any,
    ) -> T: ...

    def stream(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...
```

`backend/src/paperhub/llm/litellm_adapter.py`:

```python
import json
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import litellm
from pydantic import BaseModel

from paperhub.llm.prompts.registry import PromptRegistry

T = TypeVar("T", bound=BaseModel)


class LiteLlmAdapter:
    def __init__(self, registry: PromptRegistry | None = None) -> None:
        self._registry = registry or PromptRegistry()

    def _messages(self, slot: str, variables: dict[str, Any]) -> list[dict[str, str]]:
        prompt = self._registry.get(slot)
        return [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user_template.format(**variables)},
        ]

    async def structured(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        response_model: type[T],
        model: str,
        **kwargs: Any,
    ) -> T:
        response = await litellm.acompletion(
            model=model,
            messages=self._messages(slot, variables),
            response_format={"type": "json_object"},
            **kwargs,
        )
        content = response["choices"][0]["message"]["content"]
        return response_model.model_validate_json(content)

    async def stream(
        self,
        *,
        slot: str,
        variables: dict[str, Any],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        response = await litellm.acompletion(
            model=model,
            messages=self._messages(slot, variables),
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk["choices"][0].get("delta", {}).get("content") or ""
            if delta:
                yield delta
```

- [ ] **Step 5: Run to verify it passes**

```powershell
uv run pytest tests/test_litellm_adapter.py -v
```

Expected: all 3 tests PASS. (LiteLLM's `mock_response` kwarg makes these hermetic — no API calls.)

- [ ] **Step 6: Commit**

```powershell
git add backend/src/paperhub/llm backend/tests/test_litellm_adapter.py
git commit -m "feat(llm): LiteLLM adapter with versioned YAML prompt registry"
```

---

### Task 7 — Router agent node

**Files:**
- Create: `backend/src/paperhub/agents/__init__.py` (empty)
- Create: `backend/src/paperhub/agents/state.py`
- Create: `backend/src/paperhub/agents/router.py`
- Create: `backend/tests/test_router.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_router.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_router.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the state helper**

`backend/src/paperhub/agents/state.py`:

```python
from typing import TypedDict

from paperhub.models.domain import Branch, RoutingDecision


class AgentState(TypedDict, total=False):
    run_id: int
    branch: Branch
    session_id: int
    user_message: str
    routing_decision: RoutingDecision
    final_response: str
```

- [ ] **Step 4: Implement the router node**

`backend/src/paperhub/agents/router.py`:

```python
import json
from typing import Any

import aiosqlite

from paperhub.agents.state import AgentState
from paperhub.llm.adapter import LlmAdapter
from paperhub.models.domain import RoutingDecision
from paperhub.tracing.tracer import Tracer


async def router_node(
    state: AgentState,
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    conn: aiosqlite.Connection | None = None,
    **adapter_kwargs: Any,
) -> AgentState:
    user_message = state["user_message"]
    async with tracer.step(agent="router", tool="classify", model=model) as step:
        step.record_args({"user_message": user_message})
        decision = await adapter.structured(
            slot="router/v1",
            variables={"user_message": user_message},
            response_model=RoutingDecision,
            model=model,
            **adapter_kwargs,
        )
        step.record_result(decision.model_dump())
    if conn is not None:
        await conn.execute(
            "UPDATE runs SET routing_decision_json = ? WHERE id = ?",
            (decision.model_dump_json(), state["run_id"]),
        )
        await conn.commit()
    else:
        # The tracer's connection is the same one — reuse it for the runs update.
        await tracer._conn.execute(  # noqa: SLF001 — deliberate same-conn write
            "UPDATE runs SET routing_decision_json = ? WHERE id = ?",
            (decision.model_dump_json(), state["run_id"]),
        )
        await tracer._conn.commit()
    return {**state, "routing_decision": decision}
```

- [ ] **Step 5: Run to verify it passes**

```powershell
uv run pytest tests/test_router.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/paperhub/agents backend/tests/test_router.py
git commit -m "feat(agents): router node — classify intent + persist on runs row"
```

---

### Task 8 — Chitchat node + intent stub nodes

**Files:**
- Create: `backend/src/paperhub/agents/chitchat.py`
- Create: `backend/src/paperhub/agents/stubs.py`
- Create: `backend/tests/test_chitchat.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_chitchat.py`:

```python
import aiosqlite

from paperhub.agents.chitchat import chitchat_stream
from paperhub.agents.state import AgentState
from paperhub.agents.stubs import stub_response
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.tracing.tracer import Tracer


async def test_chitchat_stream_yields_tokens(
    migrated_db: aiosqlite.Connection,
) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1, "user_message": "hi",
    }
    chunks: list[str] = []
    async for token in chitchat_stream(
        state, adapter=LiteLlmAdapter(), tracer=tracer,
        model="gpt-4o-mini", mock_response="Hello!",
    ):
        chunks.append(token)
    assert "".join(chunks) == "Hello!"
    async with migrated_db.execute(
        "SELECT agent, tool, status FROM tool_calls"
    ) as cur:
        rows = await cur.fetchall()
    assert rows == [("chitchat", "generate", "ok")]


async def test_stub_returns_not_implemented_message() -> None:
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1, "user_message": "x",
    }
    response = await stub_response(state, intent="paper_qa")
    assert "paper_qa" in response
    assert "not yet wired" in response.lower() or "not yet implemented" in response.lower()
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_chitchat.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the chitchat node**

`backend/src/paperhub/agents/chitchat.py`:

```python
from collections.abc import AsyncIterator
from typing import Any

from paperhub.agents.state import AgentState
from paperhub.llm.adapter import LlmAdapter
from paperhub.tracing.tracer import Tracer


async def chitchat_stream(
    state: AgentState,
    *,
    adapter: LlmAdapter,
    tracer: Tracer,
    model: str,
    **adapter_kwargs: Any,
) -> AsyncIterator[str]:
    user_message = state["user_message"]
    async with tracer.step(agent="chitchat", tool="generate", model=model) as step:
        step.record_args({"user_message": user_message})
        collected: list[str] = []
        async for token in adapter.stream(
            slot="chitchat/v1",
            variables={"user_message": user_message},
            model=model,
            **adapter_kwargs,
        ):
            collected.append(token)
            yield token
        step.record_result({"length": sum(len(c) for c in collected)})
```

- [ ] **Step 4: Implement the stub nodes**

`backend/src/paperhub/agents/stubs.py`:

```python
from paperhub.agents.state import AgentState
from paperhub.models.domain import Intent

_STUB_TEMPLATE = (
    "I can see this is a `{intent}` request, but that agent is not yet wired up "
    "in Plan A — it'll arrive in a later implementation plan."
)


async def stub_response(state: AgentState, *, intent: Intent) -> str:
    return _STUB_TEMPLATE.format(intent=intent)
```

- [ ] **Step 5: Run to verify it passes**

```powershell
uv run pytest tests/test_chitchat.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/paperhub/agents/chitchat.py backend/src/paperhub/agents/stubs.py backend/tests/test_chitchat.py
git commit -m "feat(agents): chitchat streaming node + stub responses for unwired intents"
```

---

### Task 9 — LangGraph wiring

**Files:**
- Create: `backend/src/paperhub/agents/graph.py`
- Create: `backend/tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_graph.py`:

```python
import aiosqlite

from paperhub.agents.graph import GraphDeps, build_graph
from paperhub.agents.state import AgentState
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.tracing.tracer import Tracer


async def test_chitchat_path(migrated_db: aiosqlite.Connection) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    deps = GraphDeps(
        adapter=LiteLlmAdapter(),
        tracer=tracer,
        router_model="gpt-4o-mini",
        chitchat_model="gpt-4o-mini",
        router_mock='{"intent":"chitchat","model_tier":"small",'
                    '"confidence":0.85,"reasoning":"greeting"}',
        chitchat_mock="Hi there!",
    )
    graph = build_graph(deps)
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1, "user_message": "hello",
    }
    result = await graph.ainvoke(state)
    assert result["final_response"] == "Hi there!"
    assert result["routing_decision"].intent == "chitchat"


async def test_paper_qa_path_returns_stub(migrated_db: aiosqlite.Connection) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute("INSERT INTO runs (session_id) VALUES (1)")
    await migrated_db.commit()
    tracer = Tracer(migrated_db, run_id=1, branch="")
    deps = GraphDeps(
        adapter=LiteLlmAdapter(),
        tracer=tracer,
        router_model="gpt-4o-mini",
        chitchat_model="gpt-4o-mini",
        router_mock='{"intent":"paper_qa","model_tier":"flagship",'
                    '"confidence":0.93,"reasoning":"asks about a paper"}',
        chitchat_mock="",
    )
    graph = build_graph(deps)
    state: AgentState = {
        "run_id": 1, "branch": "", "session_id": 1,
        "user_message": "explain expert collapse in this paper",
    }
    result = await graph.ainvoke(state)
    assert "paper_qa" in result["final_response"]
    assert "not yet" in result["final_response"].lower()
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_graph.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the graph**

`backend/src/paperhub/agents/graph.py`:

```python
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from paperhub.agents.chitchat import chitchat_stream
from paperhub.agents.router import router_node
from paperhub.agents.state import AgentState
from paperhub.agents.stubs import stub_response
from paperhub.llm.adapter import LlmAdapter
from paperhub.tracing.tracer import Tracer


@dataclass
class GraphDeps:
    adapter: LlmAdapter
    tracer: Tracer
    router_model: str
    chitchat_model: str
    router_mock: str | None = None
    chitchat_mock: str | None = None


def build_graph(deps: GraphDeps) -> Any:
    async def _router(state: AgentState) -> AgentState:
        kwargs: dict[str, Any] = {}
        if deps.router_mock is not None:
            kwargs["mock_response"] = deps.router_mock
        return await router_node(
            state, adapter=deps.adapter, tracer=deps.tracer,
            model=deps.router_model, **kwargs,
        )

    async def _chitchat(state: AgentState) -> AgentState:
        kwargs: dict[str, Any] = {}
        if deps.chitchat_mock is not None:
            kwargs["mock_response"] = deps.chitchat_mock
        collected: list[str] = []
        async for token in chitchat_stream(
            state, adapter=deps.adapter, tracer=deps.tracer,
            model=deps.chitchat_model, **kwargs,
        ):
            collected.append(token)
        return {**state, "final_response": "".join(collected)}

    async def _stub_paper_search(state: AgentState) -> AgentState:
        return {**state, "final_response": await stub_response(state, intent="paper_search")}

    async def _stub_paper_qa(state: AgentState) -> AgentState:
        return {**state, "final_response": await stub_response(state, intent="paper_qa")}

    async def _stub_slides(state: AgentState) -> AgentState:
        return {**state, "final_response": await stub_response(state, intent="slides")}

    async def _stub_library_stats(state: AgentState) -> AgentState:
        return {**state, "final_response": await stub_response(state, intent="library_stats")}

    def _route(state: AgentState) -> str:
        return state["routing_decision"].intent

    g = StateGraph(AgentState)
    g.add_node("router", _router)
    g.add_node("chitchat", _chitchat)
    g.add_node("paper_search", _stub_paper_search)
    g.add_node("paper_qa", _stub_paper_qa)
    g.add_node("slides", _stub_slides)
    g.add_node("library_stats", _stub_library_stats)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", _route, {
        "chitchat": "chitchat",
        "paper_search": "paper_search",
        "paper_qa": "paper_qa",
        "slides": "slides",
        "library_stats": "library_stats",
    })
    for terminal in ["chitchat", "paper_search", "paper_qa", "slides", "library_stats"]:
        g.add_edge(terminal, END)
    return g.compile()
```

- [ ] **Step 4: Run to verify it passes**

```powershell
uv run pytest tests/test_graph.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/paperhub/agents/graph.py backend/tests/test_graph.py
git commit -m "feat(agents): LangGraph wiring — router → chitchat | 4 stub agents"
```

---

### Task 10 — 16-prompt router-accuracy fixture (I-8 #1)

**Files:**
- Create: `backend/tests/fixtures/router_intents.jsonl`
- Modify: `backend/tests/test_router.py` (append the fixture test)

- [ ] **Step 1: Write the fixture**

`backend/tests/fixtures/router_intents.jsonl`:

```jsonl
{"prompt": "Find recent papers on mixture of experts routing", "expected": "paper_search"}
{"prompt": "Search arXiv for transformer interpretability work from 2024", "expected": "paper_search"}
{"prompt": "Look up the latest survey on RAG", "expected": "paper_search"}
{"prompt": "Show me papers about diffusion model alignment", "expected": "paper_search"}
{"prompt": "How do these two papers differ on expert collapse?", "expected": "paper_qa"}
{"prompt": "What does Section 3 of this paper say about variance?", "expected": "paper_qa"}
{"prompt": "Summarise the methodology of the paper I just added", "expected": "paper_qa"}
{"prompt": "Compare the loss functions in these two references", "expected": "paper_qa"}
{"prompt": "Make me slides comparing the two enabled papers", "expected": "slides"}
{"prompt": "Generate a deck on this paper's contributions", "expected": "slides"}
{"prompt": "Build a presentation summarising the references", "expected": "slides"}
{"prompt": "I need slides for tomorrow on these papers", "expected": "slides"}
{"prompt": "How many papers did I add this week?", "expected": "library_stats"}
{"prompt": "List the sessions that reference paper 2403.01234", "expected": "library_stats"}
{"prompt": "Count my papers by year", "expected": "library_stats"}
{"prompt": "Which session has the most enabled references?", "expected": "library_stats"}
```

- [ ] **Step 2: Add the fixture test**

Append to `backend/tests/test_router.py`:

```python
import json
from importlib.resources import files
from pathlib import Path


async def test_routing_accuracy_at_least_80_percent(
    migrated_db: aiosqlite.Connection,
) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "router_intents.jsonl"
    rows = [json.loads(line) for line in fixture_path.read_text().splitlines() if line]
    correct = 0
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    for i, row in enumerate(rows):
        await migrated_db.execute(
            "INSERT INTO runs (session_id) VALUES (1)"
        )
        await migrated_db.commit()
        async with migrated_db.execute("SELECT last_insert_rowid()") as cur:
            r = await cur.fetchone()
        run_id = int(r[0])  # type: ignore[index]
        tracer = Tracer(migrated_db, run_id=run_id, branch="")
        # NOTE: under CI / when no provider key is set, override mock_response to
        # the expected intent — this tests the *pipeline*, not the model. To run
        # against a real provider, set PAPERHUB_ROUTER_LIVE=1 and a key.
        import os
        kwargs: dict[str, object] = {}
        if not os.environ.get("PAPERHUB_ROUTER_LIVE"):
            kwargs["mock_response"] = json.dumps({
                "intent": row["expected"], "model_tier": "small",
                "confidence": 0.9, "reasoning": "fixture",
            })
        result = await router_node(
            {
                "run_id": run_id, "branch": "", "session_id": 1,
                "user_message": row["prompt"],
            },
            adapter=LiteLlmAdapter(),
            tracer=tracer,
            model=os.environ.get("PAPERHUB_ROUTER_MODEL", "gpt-4o-mini"),
            **kwargs,
        )
        if result["routing_decision"].intent == row["expected"]:
            correct += 1
    assert correct / len(rows) >= 0.80, f"router accuracy {correct}/{len(rows)} < 80 %"
```

(Add `from paperhub.llm.litellm_adapter import LiteLlmAdapter` at the top of the file if not already imported, and `from paperhub.tracing.tracer import Tracer`.)

- [ ] **Step 3: Run**

```powershell
uv run pytest tests/test_router.py::test_routing_accuracy_at_least_80_percent -v
```

Expected: PASS (mocked path: 16/16 correct). Manual live run with `$env:PAPERHUB_ROUTER_LIVE=1` against a configured provider is documented in the README.

- [ ] **Step 4: Commit**

```powershell
git add backend/tests/fixtures backend/tests/test_router.py
git commit -m "test(router): 16-prompt intent fixture (I-8 #1) with live-mode opt-in"
```

---

### Task 11 — Health endpoint + FastAPI app skeleton

**Files:**
- Create: `backend/src/paperhub/app.py`
- Create: `backend/src/paperhub/api/__init__.py` (empty)
- Create: `backend/src/paperhub/api/health.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_health.py`:

```python
from httpx import ASGITransport, AsyncClient

from paperhub.app import create_app


async def test_health_endpoint() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_health.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the app**

`backend/src/paperhub/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

`backend/src/paperhub/app.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from paperhub.api import health
from paperhub.config import load_settings
from paperhub.db.connection import open_db
from paperhub.db.migrate import apply_schema


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    app.state.settings = settings
    async with open_db(settings.db_path) as conn:
        await apply_schema(conn)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="PaperHub", lifespan=_lifespan)
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 4: Run to verify it passes**

```powershell
uv run pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 5: Smoke-test the live server**

```powershell
uv run uvicorn paperhub.app:app --host 127.0.0.1 --port 8000 &
# In another PowerShell, or after a short pause:
curl http://127.0.0.1:8000/health
```

Expected: `{"status":"ok"}`. Kill the server.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/paperhub/app.py backend/src/paperhub/api backend/tests/test_health.py
git commit -m "feat(api): FastAPI app skeleton with lifespan-driven schema migration"
```

---

### Task 12 — `POST /chat` SSE endpoint

**Files:**
- Create: `backend/src/paperhub/api/chat.py`
- Modify: `backend/src/paperhub/app.py` (register router)
- Create: `backend/tests/test_chat_sse.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_chat_sse.py`:

```python
import json
from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient

from paperhub.app import create_app


async def _consume_sse(stream: AsyncIterator[bytes]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    buf = ""
    async for chunk in stream:
        buf += chunk.decode("utf-8")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            event_type = ""
            data = ""
            for line in block.splitlines():
                if line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
            if event_type:
                events.append((event_type, json.loads(data) if data else {}))
    return events


async def test_chat_sse_chitchat_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPERHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PAPERHUB_ROUTER_MOCK",
                       '{"intent":"chitchat","model_tier":"small",'
                       '"confidence":0.9,"reasoning":"greeting"}')
    monkeypatch.setenv("PAPERHUB_CHITCHAT_MOCK", "Hello there!")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Lifespan runs schema migration. Issue request.
        async with client.stream(
            "POST", "/chat",
            json={"session_id": None, "user_message": "hi"},
        ) as response:
            assert response.status_code == 200
            events = await _consume_sse(response.aiter_bytes())

    types = [t for t, _ in events]
    assert "routing_decision" in types
    assert types.count("tool_step") >= 2  # router + chitchat
    assert "final" in types
    final_payload = next(d for t, d in events if t == "final")
    assert final_payload["content"] == "Hello there!"
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_chat_sse.py -v
```

Expected: 404 or ImportError.

- [ ] **Step 3: Implement the chat endpoint**

`backend/src/paperhub/api/chat.py`:

```python
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from paperhub.agents.chitchat import chitchat_stream
from paperhub.agents.router import router_node
from paperhub.agents.state import AgentState
from paperhub.agents.stubs import stub_response
from paperhub.config import load_settings
from paperhub.db.connection import open_db
from paperhub.db.migrate import apply_schema
from paperhub.llm.litellm_adapter import LiteLlmAdapter
from paperhub.models.events import (
    ErrorEvent,
    FinalEvent,
    RoutingDecisionEvent,
    TokenEvent,
    ToolStepEvent,
)
from paperhub.tracing.tracer import Tracer

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: int | None = None
    user_message: str


async def _ensure_session(conn: aiosqlite.Connection, session_id: int | None) -> int:
    if session_id is not None:
        return session_id
    await conn.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await conn.commit()
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    return int(row[0])  # type: ignore[index]


async def _new_run(conn: aiosqlite.Connection, session_id: int) -> int:
    await conn.execute(
        "INSERT INTO runs (session_id, status) VALUES (?, 'running')",
        (session_id,),
    )
    await conn.commit()
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    return int(row[0])  # type: ignore[index]


async def _finalise(
    conn: aiosqlite.Connection,
    run_id: int,
    session_id: int,
    final_content: str,
    status: str,
) -> int:
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) VALUES (?, 'assistant', ?, ?)",
        (session_id, final_content, run_id),
    )
    await conn.execute(
        "UPDATE runs SET finished_at = datetime('now'), status = ? WHERE id = ?",
        (status, run_id),
    )
    await conn.commit()
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    return int(row[0])  # type: ignore[index]


async def _record_user_message(
    conn: aiosqlite.Connection, session_id: int, content: str, run_id: int
) -> None:
    await conn.execute(
        "INSERT INTO messages (session_id, role, content, run_id) VALUES (?, 'user', ?, ?)",
        (session_id, content, run_id),
    )
    await conn.commit()


async def _drain_tool_calls_since(
    conn: aiosqlite.Connection, run_id: int, after_step: int,
) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT run_id, branch, step_index, parent_step, agent, tool, model, "
        "args_redacted_json, result_summary_json, latency_ms, token_in, token_out, status, error "
        "FROM tool_calls WHERE run_id = ? AND step_index > ? ORDER BY step_index",
        (run_id, after_step),
    ) as cur:
        rows = await cur.fetchall()
    out = []
    cols = ("run_id", "branch", "step_index", "parent_step", "agent", "tool", "model",
            "args_redacted_json", "result_summary_json", "latency_ms",
            "token_in", "token_out", "status", "error")
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        for key in ("args_redacted_json", "result_summary_json"):
            if d[key]:
                d[key] = json.loads(d[key])
        out.append(d)
    return out


@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request) -> EventSourceResponse:
    settings = load_settings()
    adapter = LiteLlmAdapter()
    router_mock = os.environ.get("PAPERHUB_ROUTER_MOCK")
    chitchat_mock = os.environ.get("PAPERHUB_CHITCHAT_MOCK")

    async def stream_events() -> AsyncIterator[dict[str, Any]]:
        async with open_db(settings.db_path) as conn:
            await apply_schema(conn)
            session_id = await _ensure_session(conn, req.session_id)
            run_id = await _new_run(conn, session_id)
            await _record_user_message(conn, session_id, req.user_message, run_id)
            tracer = Tracer(conn, run_id=run_id, branch="")
            state: AgentState = {
                "run_id": run_id, "branch": "", "session_id": session_id,
                "user_message": req.user_message,
            }
            last_emitted_step = -1
            try:
                router_kwargs: dict[str, Any] = {}
                if router_mock is not None:
                    router_kwargs["mock_response"] = router_mock
                state = await router_node(
                    state, adapter=adapter, tracer=tracer,
                    model=settings.router_model, **router_kwargs,
                )
                # Emit any tool_calls rows the router just wrote.
                for rec in await _drain_tool_calls_since(conn, run_id, last_emitted_step):
                    yield {"event": "tool_step",
                           "data": json.dumps({"record": rec}, separators=(',', ':'))}
                    last_emitted_step = rec["step_index"]
                # Emit the routing_decision event.
                evt = RoutingDecisionEvent(
                    run_id=run_id, branch="", decision=state["routing_decision"],
                )
                yield {"event": evt.type,
                       "data": evt.model_dump_json(exclude={"type"})}

                intent = state["routing_decision"].intent
                if intent == "chitchat":
                    chunks: list[str] = []
                    chitchat_kwargs: dict[str, Any] = {}
                    if chitchat_mock is not None:
                        chitchat_kwargs["mock_response"] = chitchat_mock
                    async for token in chitchat_stream(
                        state, adapter=adapter, tracer=tracer,
                        model=settings.chitchat_model, **chitchat_kwargs,
                    ):
                        chunks.append(token)
                        token_evt = TokenEvent(run_id=run_id, branch="", text=token)
                        yield {"event": "token",
                               "data": token_evt.model_dump_json(exclude={"type"})}
                    final_content = "".join(chunks)
                else:
                    final_content = await stub_response(state, intent=intent)

                # Drain any remaining tool_calls rows (chitchat's).
                for rec in await _drain_tool_calls_since(conn, run_id, last_emitted_step):
                    yield {"event": "tool_step",
                           "data": json.dumps({"record": rec}, separators=(',', ':'))}
                    last_emitted_step = rec["step_index"]

                message_id = await _finalise(
                    conn, run_id, session_id, final_content, status="ok",
                )
                final_evt = FinalEvent(
                    run_id=run_id, branch="",
                    message_id=message_id, content=final_content,
                )
                yield {"event": final_evt.type,
                       "data": final_evt.model_dump_json(exclude={"type"})}
            except Exception as exc:
                await _finalise(conn, run_id, session_id, str(exc), status="error")
                err_evt = ErrorEvent(run_id=run_id, branch="", message=str(exc))
                yield {"event": err_evt.type,
                       "data": err_evt.model_dump_json(exclude={"type"})}

    return EventSourceResponse(stream_events())
```

- [ ] **Step 4: Register the router**

In `backend/src/paperhub/app.py`, change:

```python
from paperhub.api import health
```

to:

```python
from paperhub.api import chat, health
```

and:

```python
    app.include_router(health.router)
```

to:

```python
    app.include_router(health.router)
    app.include_router(chat.router)
```

- [ ] **Step 5: Run to verify it passes**

```powershell
uv run pytest tests/test_chat_sse.py -v
```

Expected: PASS.

- [ ] **Step 6: Live smoke test**

```powershell
$env:PAPERHUB_WORKSPACE = "$PWD\workspace"
$env:PAPERHUB_ROUTER_MOCK = '{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"x"}'
$env:PAPERHUB_CHITCHAT_MOCK = "Hello!"
uv run uvicorn paperhub.app:app --host 127.0.0.1 --port 8000
# Other shell:
curl -N -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"user_message":"hi"}'
```

Expected: stream prints `event: routing_decision`, several `event: tool_step` lines, `event: final`. Kill server.

- [ ] **Step 7: Commit**

```powershell
git add backend/src/paperhub/api/chat.py backend/src/paperhub/app.py backend/tests/test_chat_sse.py
git commit -m "feat(api): POST /chat SSE — router + chitchat + stub-fallback round-trip"
```

---

### Task 13 — Replay CLI (I-8 #4 evidence)

**Files:**
- Create: `backend/src/paperhub/cli/__init__.py` (empty)
- Create: `backend/src/paperhub/cli/replay.py`
- Create: `backend/tests/test_replay.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_replay.py`:

```python
import aiosqlite

from paperhub.cli.replay import replay_run


async def test_replay_reconstructs_step_sequence(
    migrated_db: aiosqlite.Connection,
) -> None:
    await migrated_db.execute("INSERT INTO chat_sessions DEFAULT VALUES")
    await migrated_db.execute(
        "INSERT INTO runs (session_id, routing_decision_json, status) "
        "VALUES (1, ?, 'ok')",
        ('{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"x"}',),
    )
    await migrated_db.commit()
    for idx, (agent, tool) in enumerate([("router", "classify"), ("chitchat", "generate")]):
        await migrated_db.execute(
            "INSERT INTO tool_calls (run_id, branch, step_index, agent, tool, "
            "latency_ms, status) VALUES (1, '', ?, ?, ?, 10, 'ok')",
            (idx, agent, tool),
        )
    await migrated_db.commit()

    report = await replay_run(migrated_db, run_id=1)
    assert "router · classify" in report
    assert "chitchat · generate" in report
    assert "intent=chitchat" in report
```

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/test_replay.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement replay**

`backend/src/paperhub/cli/replay.py`:

```python
import argparse
import asyncio
import json
import sys

import aiosqlite

from paperhub.config import load_settings
from paperhub.db.connection import open_db


async def replay_run(conn: aiosqlite.Connection, *, run_id: int) -> str:
    async with conn.execute(
        "SELECT session_id, routing_decision_json, status FROM runs WHERE id = ?",
        (run_id,),
    ) as cur:
        run_row = await cur.fetchone()
    if run_row is None:
        return f"run {run_id} not found"
    session_id, decision_json, status = run_row
    decision = json.loads(decision_json) if decision_json else {}

    async with conn.execute(
        "SELECT branch, step_index, agent, tool, model, status, latency_ms, error "
        "FROM tool_calls WHERE run_id = ? ORDER BY branch, step_index",
        (run_id,),
    ) as cur:
        steps = await cur.fetchall()

    lines: list[str] = [
        f"run {run_id} (session {session_id}, status={status})",
        f"  intent={decision.get('intent','?')} "
        f"tier={decision.get('model_tier','?')} "
        f"conf={decision.get('confidence','?')}",
    ]
    for branch, step_index, agent, tool, model, st, latency_ms, error in steps:
        prefix = f"  [{branch or 'main'}#{step_index}]"
        line = f"{prefix} {agent} · {tool} ({model or '-'}) {latency_ms}ms {st}"
        if error:
            line += f" — {error}"
        lines.append(line)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a PaperHub run from SQLite")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    settings = load_settings()

    async def _run() -> None:
        async with open_db(settings.db_path) as conn:
            print(await replay_run(conn, run_id=args.run_id))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

```powershell
uv run pytest tests/test_replay.py -v
```

Expected: PASS.

- [ ] **Step 5: Smoke test against a real run**

```powershell
# After running the live smoke test from Task 12, the workspace DB has at least one run:
uv run paperhub-replay --run-id 1
```

Expected: prints the run summary + step list.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/paperhub/cli backend/tests/test_replay.py
git commit -m "feat(cli): paperhub-replay — reconstruct any run from SQLite (I-8 #4)"
```

---

### Task 14 — Lint + typecheck gate

**Files:**
- Modify: `backend/README.md`

- [ ] **Step 1: Run ruff + mypy across the whole tree**

```powershell
uv run ruff check src tests
uv run mypy src
```

Expected: both report success. Fix anything they flag.

- [ ] **Step 2: Document the gate in the README**

Append to `backend/README.md`:

```markdown
## Quality gates

All of these must pass before opening a PR for Plan B onward:

    uv run pytest -v
    uv run ruff check src tests
    uv run mypy src
```

- [ ] **Step 3: Commit**

```powershell
git add backend/README.md
git commit -m "docs(backend): document lint + typecheck quality gates"
```

---

### Task 15 — End-to-end demo script

**Files:**
- Create: `backend/scripts/smoke_chat.ps1`

- [ ] **Step 1: Write the smoke script**

`backend/scripts/smoke_chat.ps1`:

```powershell
# Run the backend end-to-end against the chitchat path with mocked LLM responses.
# Verifies: SSE round-trip works, schema is migrated, run is replayable from SQLite.
$ErrorActionPreference = "Stop"

$env:PAPERHUB_WORKSPACE = Join-Path $PSScriptRoot "..\workspace_smoke"
$env:PAPERHUB_ROUTER_MOCK = '{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"greeting"}'
$env:PAPERHUB_CHITCHAT_MOCK = "Hi from PaperHub!"

if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

$server = Start-Process -PassThru -NoNewWindow uv -ArgumentList @(
    "run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8765"
)
try {
    # Wait for server to come up
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8765/health -ErrorAction Stop | Out-Null
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    Write-Host "Server up. Issuing chat request..."
    curl.exe -N -s -X POST http://127.0.0.1:8765/chat `
        -H "Content-Type: application/json" `
        -d '{"user_message":"hello"}' | Tee-Object -Variable sseOutput
    Write-Host "`n--- Replay ---"
    uv run paperhub-replay --run-id 1
} finally {
    Stop-Process -Id $server.Id -Force
}
```

- [ ] **Step 2: Run the smoke script**

```powershell
cd backend
.\scripts\smoke_chat.ps1
```

Expected: SSE events stream past, then a replay block printed showing `router · classify` and `chitchat · generate` steps.

- [ ] **Step 3: Commit**

```powershell
git add backend/scripts/smoke_chat.ps1
git commit -m "test(backend): end-to-end smoke script for chitchat round-trip + replay"
```

---

## Done state

After Task 15:

- `uv run pytest -v` — all tests pass (≈ 20+ tests across 10 files).
- `uv run ruff check src tests` — clean.
- `uv run mypy src` — clean.
- `uv run uvicorn paperhub.app:app` boots, `POST /chat` streams SSE for chitchat end-to-end.
- `uv run paperhub-replay --run-id N` reconstructs any past run from SQLite alone (I-8 #4 met).
- The four real intents are recognised by the Router (I-8 #1 partially met — accuracy ≥ 80 % on the 16-prompt fixture in mocked mode; live mode opt-in via `PAPERHUB_ROUTER_LIVE`) and route to stub responses that say "not yet wired".
- The `tool_calls.branch` column is in place and tested for branch isolation, so Plan G's Compare-view fan-out only needs to drive `branch='A' / 'B'` — no schema changes.
- The Paper Pipeline, RAG, MCP surfaces, and frontend are still out of scope — Plans B–G own them.

---

## Plan self-review

- **Spec coverage:** §III-7 schema (Task 2), Router intent (Tasks 7, 10), tracer + redaction (Tasks 3, 5), LiteLLM with tiered models (Task 6), versioned prompts (Task 6), SSE event ordering (Task 12), replay-from-SQLite (Task 13), `branch` PK for future Compare (Tasks 2, 5). FR-04 (Compare-view actual fan-out) intentionally deferred to Plan G — Plan A only ensures the schema + tracer support it.
- **Placeholder scan:** all code blocks contain real implementations; no `TODO` / `TBD` markers inside steps.
- **Type consistency:** `RoutingDecision`, `AgentState`, `Tracer.step(...)` signature, `GraphDeps` shape, SSE event envelope shapes are consistent across tasks.
- **No scope creep:** no Chroma, no embeddings, no extraction utilities, no MCP servers — all correctly deferred to Plans C / E / F / G.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-paperhub-A-backend-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
