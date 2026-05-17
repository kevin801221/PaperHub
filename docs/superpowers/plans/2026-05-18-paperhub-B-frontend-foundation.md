# PaperHub Plan B — Frontend Foundation + End-to-End Chitchat

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a React + Vite + Tailwind + Zustand chat shell that consumes `POST /chat` SSE end-to-end against the Plan-A backend, with visible routing badge + trace panel + all four NFR-02 states. Single chat view; no Citation Canvas, no Compare, no Reference Sources panel, no Slide preview — those land in Plans D / F / G.

**Architecture:** Vite + React 18 + TypeScript strict. Tailwind for styling, **shadcn/ui** as the primitive layer (copy-pasted Radix components into `src/components/ui/`). Zustand for state (`chat` + `theme` stores). **@microsoft/fetch-event-source** for the POST SSE call (native `EventSource` doesn't support POST). Theme: light + dark with `prefers-color-scheme` default and a sidebar toggle. Tests: Vitest + React Testing Library + MSW (for SSE stubbing).

**Tech Stack:** Node 20+, npm (consistency with `reference/Intro2GenAI-hw1`), Vite 5, React 18, TypeScript 5, Tailwind 3, shadcn/ui (Radix + cva), Zustand 4, @microsoft/fetch-event-source 2.x, Vitest 2, React Testing Library, MSW 2. ESLint + Prettier.

---

## Spec Coverage Summary

| SRS reference | Addressed by |
| --- | --- |
| §III-2 ChatShell / LeftSidebar / ChatThread / MessageBubble / Composer | Tasks 7, 8, 12, 13, 14 |
| §III-2 RoutingBadge (FR-01 surface) | Task 9 |
| §III-2 TraceInline (FR-02 / FR-09 surface) | Task 10 |
| §III-2 EmptyState / LoadingDots / RejectionPill / ErrorToast (NFR-02) | Task 12 (inline) + Task 14 toast wiring |
| FR-01 Routing badge — intent / tier / confidence | Task 9 |
| FR-02 Trace panel — per-step rows | Task 10 |
| NFR-02 no silent failure — visible states for loading / error / rejection / empty | Tasks 12, 14 |
| NFR-06 strict typing | Task 1 (tsconfig strict) + applies throughout |
| Browser-verifiable chitchat round-trip | Task 14 (ChatPage) + Task 16 (smoke) |

**Out of scope for Plan B** (intentional): Citation Canvas, Reference Sources panel, Search Results list, Compare-split view, Slide preview chip, paper-upload UI, authentication. Each is owned by a later plan.

---

## File Structure

```
frontend/
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── components.json                  # shadcn/ui config
├── index.html
├── .gitignore
├── .eslintrc.cjs
├── .prettierrc
├── README.md
└── src/
    ├── main.tsx                     # React entry
    ├── App.tsx                      # shell + theme provider + toaster
    ├── index.css                    # tailwind directives + shadcn CSS vars
    ├── lib/
    │   ├── api.ts                   # base URL, fetch wrappers
    │   ├── sse.ts                   # POST SSE consumer (fetch-event-source)
    │   └── utils.ts                 # shadcn cn() helper
    ├── types/
    │   └── domain.ts                # mirrors backend Pydantic models
    ├── store/
    │   ├── chat.ts                  # Zustand chat store (sessions, messages, trace)
    │   └── theme.ts                 # Zustand theme store
    ├── hooks/
    │   └── useChatStream.ts         # imperative POST /chat → events → store updates
    ├── components/
    │   ├── ui/                      # shadcn-generated primitives (button, tooltip, …)
    │   ├── layout/
    │   │   ├── Shell.tsx            # sidebar + main grid
    │   │   ├── Sidebar.tsx          # session list + new chat + theme toggle
    │   │   └── ThemeToggle.tsx
    │   ├── chat/
    │   │   ├── ChatThread.tsx       # message list + auto-scroll + 4 NFR-02 states
    │   │   ├── MessageBubble.tsx
    │   │   ├── Composer.tsx
    │   │   ├── RoutingBadge.tsx
    │   │   └── TraceInline.tsx
    │   └── states/
    │       ├── EmptyState.tsx
    │       ├── LoadingDots.tsx
    │       ├── RejectionPill.tsx
    │       └── ErrorToast.tsx       # uses shadcn toast
    └── pages/
        └── ChatPage.tsx             # one route for Plan B; React Router defers to later
└── tests/
    ├── setup.ts
    ├── stubs/
    │   └── sse.ts                   # MSW handler streaming canned SSE
    ├── components/
    │   ├── MessageBubble.test.tsx
    │   ├── RoutingBadge.test.tsx
    │   ├── TraceInline.test.tsx
    │   └── Composer.test.tsx
    └── hooks/
        └── useChatStream.test.ts
```

---

## Task 1 — Vite + TypeScript + ESLint + Prettier bootstrap

**Files:**
- Create: `frontend/` (whole tree per Vite scaffold + overrides)

- [ ] **Step 1: Scaffold the Vite project.**

From repo root:

```powershell
cd $PWD
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

This produces a starter React-TS scaffold. Most files we'll keep; some get overwritten in later steps.

- [ ] **Step 2: Replace `frontend/tsconfig.json` to enable strict + path aliases.**

```jsonc
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src", "tests"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Replace `frontend/vite.config.ts` to register the `@/` alias.**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: { port: 5173 },
});
```

- [ ] **Step 4: Add ESLint + Prettier.**

```powershell
npm install --save-dev eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin eslint-plugin-react-hooks eslint-plugin-react-refresh prettier eslint-config-prettier
```

`frontend/.eslintrc.cjs`:

```js
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module", project: "./tsconfig.json" },
  plugins: ["@typescript-eslint", "react-hooks", "react-refresh"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended-type-checked",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
  },
  ignorePatterns: ["dist", "node_modules", "*.cjs"],
};
```

`frontend/.prettierrc`:

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}
```

- [ ] **Step 5: Write `frontend/README.md`.**

```markdown
# PaperHub frontend

## Dev
    npm install
    npm run dev               # Vite on http://localhost:5173

## Test
    npm test
    npm run test:watch

## Lint + typecheck
    npm run lint
    npm run typecheck
```

- [ ] **Step 6: Add scripts to `frontend/package.json`.**

Edit `package.json` `scripts`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src tests --max-warnings=0",
    "typecheck": "tsc -b --noEmit",
    "format": "prettier --write src tests"
  }
}
```

- [ ] **Step 7: Verify the scaffold builds.**

```powershell
npm run typecheck
npm run lint
npm run build
```

Expected: all three succeed.

- [ ] **Step 8: Commit.**

```powershell
git add frontend/
git commit -m "chore(frontend): scaffold Vite + React + TypeScript strict + ESLint + Prettier"
```

---

## Task 2 — Tailwind + shadcn/ui + first primitives

**Files:**
- Modify: `frontend/package.json`, `frontend/index.html`, `frontend/src/index.css`, `frontend/src/main.tsx`
- Create: `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/components.json`, `frontend/src/lib/utils.ts`
- Create (via shadcn CLI): `frontend/src/components/ui/button.tsx`, `tooltip.tsx`, `toast.tsx`, `toaster.tsx`, `use-toast.ts`

- [ ] **Step 1: Install Tailwind + PostCSS.**

```powershell
cd frontend
npm install --save-dev tailwindcss postcss autoprefixer tailwindcss-animate
npx tailwindcss init -p
```

- [ ] **Step 2: Write `frontend/tailwind.config.js`.**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem" },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up":   { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
      animation: { "accordion-down": "accordion-down 0.2s ease-out", "accordion-up": "accordion-up 0.2s ease-out" },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
```

- [ ] **Step 3: Overwrite `frontend/src/index.css` with shadcn theme tokens.**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 240 10% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 240 10% 3.9%;
    --primary: 240 5.9% 10%;
    --primary-foreground: 0 0% 98%;
    --secondary: 240 4.8% 95.9%;
    --secondary-foreground: 240 5.9% 10%;
    --muted: 240 4.8% 95.9%;
    --muted-foreground: 240 3.8% 46.1%;
    --accent: 240 4.8% 95.9%;
    --accent-foreground: 240 5.9% 10%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 5.9% 90%;
    --input: 240 5.9% 90%;
    --ring: 240 5.9% 10%;
    --radius: 0.5rem;
  }
  .dark {
    --background: 240 10% 3.9%;
    --foreground: 0 0% 98%;
    --card: 240 10% 3.9%;
    --card-foreground: 0 0% 98%;
    --primary: 0 0% 98%;
    --primary-foreground: 240 5.9% 10%;
    --secondary: 240 3.7% 15.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 240 3.7% 15.9%;
    --muted-foreground: 240 5% 64.9%;
    --accent: 240 3.7% 15.9%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 3.7% 15.9%;
    --input: 240 3.7% 15.9%;
    --ring: 240 4.9% 83.9%;
  }
  body { @apply bg-background text-foreground antialiased; }
}
```

- [ ] **Step 4: Initialise shadcn/ui.**

```powershell
npx shadcn@latest init -d
```

When prompted: TypeScript yes, default style "default", base color "Slate", CSS variables yes, `tailwind.config.js`, components alias `@/components`, utils alias `@/lib/utils`, RSC no.

This creates `components.json` and `src/lib/utils.ts`.

- [ ] **Step 5: Add four primitive components we'll use immediately.**

```powershell
npx shadcn@latest add button tooltip toast scroll-area
```

This drops `src/components/ui/{button,tooltip,toast,toaster,use-toast,scroll-area}.tsx` into the tree.

- [ ] **Step 6: Wire `<Toaster />` into the app root.**

Edit `frontend/src/App.tsx`:

```tsx
import { Toaster } from "@/components/ui/toaster";

function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="container py-10">
        <h1 className="text-2xl font-semibold">PaperHub</h1>
        <p className="text-muted-foreground mt-2">Plan B in progress.</p>
      </main>
      <Toaster />
    </div>
  );
}

export default App;
```

- [ ] **Step 7: Verify visually.**

```powershell
npm run dev
```

Visit `http://localhost:5173`. Expected: "PaperHub" title rendered with Tailwind styling + muted subtitle. Kill the server.

- [ ] **Step 8: Verify the gates.**

```powershell
npm run typecheck
npm run lint
npm run build
```

All pass.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): Tailwind + shadcn/ui (button, tooltip, toast, scroll-area)"
```

---

## Task 3 — Backend CORS retrofit

**Files:**
- Modify: `backend/src/paperhub/app.py`
- Modify: `backend/tests/test_health.py` (add CORS preflight test)

This is a small Plan-A retrofit: the FastAPI app needs to allow the Vite dev server origin (`http://localhost:5173`).

- [ ] **Step 1: Write the failing test.**

Append to `backend/tests/test_health.py`:

```python
async def test_cors_allows_vite_dev_origin() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
```

Run from `backend/`:

```powershell
uv run pytest tests/test_health.py::test_cors_allows_vite_dev_origin -v
```

Expected: FAIL (no CORS middleware yet).

- [ ] **Step 2: Add CORS middleware to `app.py`.**

`backend/src/paperhub/app.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paperhub.api import chat, health
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
```

- [ ] **Step 3: Run.**

```powershell
uv run pytest tests/test_health.py -v
```

Expected: 2 PASSED.

- [ ] **Step 4: Run the full backend suite to confirm nothing else broke.**

```powershell
uv run pytest -v
uv run ruff check src tests
uv run mypy src
```

All clean.

- [ ] **Step 5: Commit.**

```powershell
cd ..
git add backend/src/paperhub/app.py backend/tests/test_health.py
git commit -m "feat(api): allow CORS from Vite dev origin (http://localhost:5173)"
```

---

## Task 4 — Domain types + Zustand stores

**Files:**
- Create: `frontend/src/types/domain.ts`
- Create: `frontend/src/store/chat.ts`
- Create: `frontend/src/store/theme.ts`
- Create: `frontend/tests/setup.ts`
- Modify: `frontend/vite.config.ts` (add Vitest config) OR create `frontend/vitest.config.ts`

- [ ] **Step 1: Install Vitest + RTL + MSW.**

```powershell
cd frontend
npm install --save-dev vitest @vitest/ui jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw zustand
```

- [ ] **Step 2: Configure Vitest.**

Edit `frontend/vite.config.ts` to add a `test` section:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { port: 5173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: false,
  },
});
```

(Suppress the TS error about `test` being unknown on `UserConfig` by adding `/// <reference types="vitest" />` at the top.)

- [ ] **Step 3: Write `frontend/tests/setup.ts`.**

```ts
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());
```

- [ ] **Step 4: Write `frontend/src/types/domain.ts` — mirror backend Pydantic models.**

```ts
export type Intent =
  | "paper_search"
  | "paper_qa"
  | "slides"
  | "library_stats"
  | "chitchat";

export type ModelTier = "small" | "flagship";
export type ToolStatus = "ok" | "error" | "rejected";
export type Branch = "" | "A" | "B";

export interface RoutingDecision {
  intent: Intent;
  model_tier: ModelTier;
  confidence: number;
  reasoning: string;
}

export interface ToolCallRecord {
  run_id: number;
  branch: Branch;
  step_index: number;
  parent_step: number | null;
  agent: string;
  tool: string;
  model: string | null;
  args_redacted_json: Record<string, unknown> | null;
  result_summary_json: Record<string, unknown> | null;
  latency_ms: number;
  token_in: number | null;
  token_out: number | null;
  status: ToolStatus;
  error: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  run_id: number | null;
  routing_decision?: RoutingDecision;
  trace?: ToolCallRecord[];
  status?: "streaming" | "ok" | "error";
  error?: string;
}

export interface ChatSession {
  id: number;
  title: string;
  messages: ChatMessage[];
}
```

- [ ] **Step 5: Write the failing test.**

`frontend/tests/store/chat.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { useChatStore } from "@/store/chat";

describe("chat store", () => {
  it("starts with no active session", () => {
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  it("creates a new session and selects it", () => {
    const id = useChatStore.getState().newSession();
    expect(id).toBeGreaterThan(0);
    expect(useChatStore.getState().activeSessionId).toBe(id);
  });

  it("appends a user message to the active session", () => {
    useChatStore.getState().reset();
    const id = useChatStore.getState().newSession();
    useChatStore.getState().appendMessage(id, {
      role: "user", content: "hello", run_id: null,
    });
    const session = useChatStore.getState().sessions.find((s) => s.id === id)!;
    expect(session.messages).toHaveLength(1);
    expect(session.messages[0].content).toBe("hello");
  });
});
```

Run:

```powershell
npm test
```

Expected: FAIL (store doesn't exist).

- [ ] **Step 6: Implement `frontend/src/store/chat.ts`.**

```ts
import { create } from "zustand";
import type {
  ChatMessage,
  ChatSession,
  RoutingDecision,
  ToolCallRecord,
} from "@/types/domain";

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: number | null;
  newSession: () => number;
  selectSession: (id: number) => void;
  appendMessage: (sessionId: number, message: ChatMessage) => void;
  setRouting: (sessionId: number, run_id: number, decision: RoutingDecision) => void;
  appendToken: (sessionId: number, run_id: number, text: string) => void;
  appendTrace: (sessionId: number, run_id: number, record: ToolCallRecord) => void;
  finaliseMessage: (sessionId: number, run_id: number, content: string) => void;
  errorMessage: (sessionId: number, run_id: number, error: string) => void;
  reset: () => void;
}

const nextId = (() => {
  let n = 0;
  return () => ++n;
})();

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeSessionId: null,

  newSession: () => {
    const id = nextId();
    set((s) => ({
      sessions: [...s.sessions, { id, title: "New chat", messages: [] }],
      activeSessionId: id,
    }));
    return id;
  },

  selectSession: (id) => set({ activeSessionId: id }),

  appendMessage: (sessionId, message) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? { ...sess, messages: [...sess.messages, message] }
          : sess,
      ),
    })),

  setRouting: (sessionId, run_id, decision) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, routing_decision: decision }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendToken: (sessionId, run_id, text) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content: m.content + text }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendTrace: (sessionId, run_id, record) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, trace: [...(m.trace ?? []), record] }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  finaliseMessage: (sessionId, run_id, content) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content, status: "ok" }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  errorMessage: (sessionId, run_id, error) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, status: "error", error }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  reset: () => set({ sessions: [], activeSessionId: null }),
}));
```

- [ ] **Step 7: Implement `frontend/src/store/theme.ts`.**

```ts
import { create } from "zustand";

type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

function systemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: systemTheme(),
  setTheme: (t) => {
    document.documentElement.classList.toggle("dark", t === "dark");
    set({ theme: t });
  },
  toggleTheme: () =>
    set((s) => {
      const next: Theme = s.theme === "light" ? "dark" : "light";
      document.documentElement.classList.toggle("dark", next === "dark");
      return { theme: next };
    }),
}));
```

- [ ] **Step 8: Run.**

```powershell
npm test
npm run typecheck
npm run lint
```

Expected: 3 tests pass, typecheck + lint clean.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): domain types + Zustand chat/theme stores + Vitest setup"
```

---

## Task 5 — SSE consumer (lib + hook)

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/sse.ts`
- Create: `frontend/src/hooks/useChatStream.ts`
- Create: `frontend/tests/hooks/useChatStream.test.ts`
- Create: `frontend/tests/stubs/sse.ts`

- [ ] **Step 1: Install fetch-event-source.**

```powershell
npm install @microsoft/fetch-event-source
```

- [ ] **Step 2: Write the MSW SSE stub.**

`frontend/tests/stubs/sse.ts`:

```ts
import { http, HttpResponse } from "msw";

const enc = new TextEncoder();

function sseChunk(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

export const chitchatHappyPath = http.post("http://localhost:8000/chat", () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        sseChunk("tool_step", {
          record: {
            run_id: 1, branch: "", step_index: 0, agent: "router", tool: "classify",
            model: "x", latency_ms: 12, status: "ok",
            parent_step: null, args_redacted_json: null, result_summary_json: null,
            token_in: null, token_out: null, error: null,
          },
        }),
      );
      controller.enqueue(
        sseChunk("routing_decision", {
          run_id: 1, branch: "",
          decision: {
            intent: "chitchat", model_tier: "small",
            confidence: 0.9, reasoning: "greeting",
          },
        }),
      );
      controller.enqueue(sseChunk("token", { run_id: 1, branch: "", text: "Hi " }));
      controller.enqueue(sseChunk("token", { run_id: 1, branch: "", text: "there!" }));
      controller.enqueue(
        sseChunk("final", {
          run_id: 1, branch: "", message_id: 2, content: "Hi there!",
        }),
      );
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream" },
  });
});
```

- [ ] **Step 3: Write the failing hook test.**

`frontend/tests/hooks/useChatStream.test.ts`:

```ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";
import { useChatStore } from "@/store/chat";
import { chitchatHappyPath } from "../stubs/sse";

const server = setupServer(chitchatHappyPath);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  server.resetHandlers(chitchatHappyPath);
  useChatStore.getState().reset();
});

describe("useChatStream", () => {
  it("runs a chitchat round-trip and updates the store", async () => {
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.send(sessionId, "hello");
    });

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId)!;
      const assistant = session.messages.find((m) => m.role === "assistant")!;
      expect(assistant.status).toBe("ok");
      expect(assistant.content).toBe("Hi there!");
      expect(assistant.routing_decision?.intent).toBe("chitchat");
      expect(assistant.trace).toHaveLength(1);
    });
  });
});
```

Run:

```powershell
npm test
```

Expected: FAIL (hook doesn't exist).

- [ ] **Step 4: Write `frontend/src/lib/api.ts`.**

```ts
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
```

- [ ] **Step 5: Write `frontend/src/lib/sse.ts`.**

```ts
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { API_BASE_URL } from "@/lib/api";

export interface SseHandlers {
  onEvent: (event: string, data: unknown) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

export async function streamChat(
  body: { session_id: number | null; user_message: string },
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await fetchEventSource(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        throw new Error(`POST /chat failed: ${response.status} ${response.statusText}`);
      }
    },
    onmessage(msg) {
      if (msg.event) {
        try {
          handlers.onEvent(msg.event, JSON.parse(msg.data));
        } catch (e) {
          handlers.onError?.(e);
        }
      }
    },
    onerror(err) {
      handlers.onError?.(err);
      throw err;
    },
    onclose() {
      handlers.onClose?.();
    },
  });
}
```

- [ ] **Step 6: Write `frontend/src/hooks/useChatStream.ts`.**

```ts
import { useCallback, useRef } from "react";
import type { RoutingDecision, ToolCallRecord } from "@/types/domain";
import { streamChat } from "@/lib/sse";
import { useChatStore } from "@/store/chat";

interface ToolStepData { record: ToolCallRecord; }
interface RoutingData { run_id: number; branch: string; decision: RoutingDecision; }
interface TokenData { run_id: number; branch: string; text: string; }
interface FinalData { run_id: number; branch: string; message_id: number; content: string; }
interface ErrorData { run_id: number; branch: string; message: string; }

export function useChatStream() {
  const abortRef = useRef<AbortController | null>(null);
  const store = useChatStore;

  const send = useCallback(async (sessionId: number, userMessage: string) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    store.getState().appendMessage(sessionId, {
      role: "user", content: userMessage, run_id: null,
    });
    // run_id is filled after the first tool_step / routing_decision arrives.
    let runId: number | null = null;
    const placeholder = {
      role: "assistant" as const,
      content: "",
      run_id: null,
      status: "streaming" as const,
    };
    store.getState().appendMessage(sessionId, placeholder);

    await streamChat(
      { session_id: null, user_message: userMessage },
      {
        onEvent: (event, data) => {
          if (event === "tool_step") {
            const rec = (data as ToolStepData).record;
            if (runId === null) {
              runId = rec.run_id;
              // Patch the placeholder with the run_id so subsequent updates find it.
              const sess = store.getState().sessions.find((s) => s.id === sessionId);
              const last = sess?.messages[sess.messages.length - 1];
              if (last && last.role === "assistant" && last.run_id === null) {
                last.run_id = runId;
              }
            }
            store.getState().appendTrace(sessionId, rec.run_id, rec);
          } else if (event === "routing_decision") {
            const d = data as RoutingData;
            runId = d.run_id;
            store.getState().setRouting(sessionId, d.run_id, d.decision);
          } else if (event === "token") {
            const t = data as TokenData;
            store.getState().appendToken(sessionId, t.run_id, t.text);
          } else if (event === "final") {
            const f = data as FinalData;
            store.getState().finaliseMessage(sessionId, f.run_id, f.content);
          } else if (event === "error") {
            const e = data as ErrorData;
            store.getState().errorMessage(sessionId, e.run_id, e.message);
          }
        },
        onError: (err) => {
          if (runId !== null) {
            store.getState().errorMessage(
              sessionId, runId, err instanceof Error ? err.message : String(err),
            );
          }
        },
      },
      abortRef.current.signal,
    );
  }, [store]);

  return { send };
}
```

NOTE: the mutation `last.run_id = runId` is intentional — Zustand state objects are shallowly compared, but per-message field patching is fine here because the consuming components re-render off the `sessions` array reference changes triggered by `appendTrace` immediately after. If a reviewer flags this as suspicious, replace with a `patchAssistantRunId(sessionId, runId)` store action.

- [ ] **Step 7: Run.**

```powershell
npm test
```

Expected: PASS.

- [ ] **Step 8: Gates.**

```powershell
npm run typecheck
npm run lint
```

Both clean.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): SSE consumer hook driving Zustand chat store"
```

---

## Task 6 — Theme provider + toggle

**Files:**
- Create: `frontend/src/components/layout/ThemeToggle.tsx`
- Modify: `frontend/src/main.tsx` (apply initial theme class)
- Create: `frontend/tests/components/ThemeToggle.test.tsx`

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/ThemeToggle.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useThemeStore } from "@/store/theme";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    useThemeStore.setState({ theme: "light" });
  });

  it("flips theme on click", async () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: /theme/i });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await userEvent.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(useThemeStore.getState().theme).toBe("dark");
  });
});
```

- [ ] **Step 2: Install the icon library.**

```powershell
npm install lucide-react
```

- [ ] **Step 3: Implement.**

`frontend/src/components/layout/ThemeToggle.tsx`:

```tsx
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useThemeStore } from "@/store/theme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useThemeStore();
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch theme (currently ${theme})`}
      onClick={toggleTheme}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
```

- [ ] **Step 4: Apply the initial class on app boot.**

Edit `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { useThemeStore } from "@/store/theme";
import "./index.css";

document.documentElement.classList.toggle(
  "dark",
  useThemeStore.getState().theme === "dark",
);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 5: Run.**

```powershell
npm test
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): theme toggle + system-preference default"
```

---

## Task 7 — Layout shell (Sidebar slot + main slot)

**Files:**
- Create: `frontend/src/components/layout/Shell.tsx`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `Shell.tsx`.**

```tsx
import { ReactNode } from "react";

export function Shell({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid h-screen grid-cols-[260px_1fr] bg-background text-foreground">
      <aside className="border-r border-border bg-card flex flex-col">
        {sidebar}
      </aside>
      <main className="flex flex-col min-h-0">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Write a minimal `Sidebar.tsx` (sessions list slot + theme toggle for now; new-chat button comes in Task 13).**

```tsx
import { useChatStore } from "@/store/chat";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

export function Sidebar() {
  const { sessions, activeSessionId, newSession, selectSession } = useChatStore();

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <span className="text-lg font-semibold">PaperHub</span>
        <ThemeToggle />
      </div>
      <div className="p-3">
        <Button
          variant="default"
          className="w-full justify-start gap-2"
          onClick={() => newSession()}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-4 space-y-1">
        {sessions.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">
            No chats yet.
          </p>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => selectSession(s.id)}
            className={`w-full text-left text-sm rounded-md px-3 py-2 transition-colors ${
              s.id === activeSessionId
                ? "bg-accent text-accent-foreground"
                : "hover:bg-accent/50 text-foreground"
            }`}
          >
            {s.title}
          </button>
        ))}
      </nav>
    </div>
  );
}
```

- [ ] **Step 3: Update `App.tsx`.**

```tsx
import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/toaster";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          ChatPage placeholder — Task 14 will render here.
        </div>
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
```

- [ ] **Step 4: Manual visual check.**

```powershell
npm run dev
```

Visit `http://localhost:5173`. Click "New chat" — sessions list should grow. Toggle theme — colors invert. Kill the server.

- [ ] **Step 5: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): layout shell + sidebar with sessions list + theme toggle"
```

---

## Task 8 — MessageBubble component

**Files:**
- Create: `frontend/src/components/chat/MessageBubble.tsx`
- Create: `frontend/tests/components/MessageBubble.test.tsx`

- [ ] **Step 1: Install a tiny markdown renderer.**

```powershell
npm install marked
npm install --save-dev @types/marked
```

(`marked` keeps the trace + status surface simple. Citation buttons land in Plan D.)

- [ ] **Step 2: Write the failing test.**

`frontend/tests/components/MessageBubble.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "@/components/chat/MessageBubble";

describe("MessageBubble", () => {
  it("renders a user message right-aligned", () => {
    render(
      <MessageBubble message={{ role: "user", content: "hello", run_id: null }} />,
    );
    const node = screen.getByText("hello");
    expect(node.closest("article")).toHaveAttribute("data-role", "user");
  });

  it("renders streaming state for an in-flight assistant message", () => {
    render(
      <MessageBubble
        message={{ role: "assistant", content: "Hi th", run_id: 1, status: "streaming" }}
      />,
    );
    expect(screen.getByText(/hi th/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/streaming/i)).toBeInTheDocument();
  });

  it("renders an error message with the error string", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant", content: "", run_id: 1,
          status: "error", error: "Provider 500",
        }}
      />,
    );
    expect(screen.getByText(/provider 500/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Implement.**

`frontend/src/components/chat/MessageBubble.tsx`:

```tsx
import { marked } from "marked";
import type { ChatMessage } from "@/types/domain";

interface Props { message: ChatMessage; }

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const html = marked.parse(message.content || " ", { async: false }) as string;

  return (
    <article
      data-role={message.role}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 prose prose-sm dark:prose-invert ${
          isUser ? "bg-primary text-primary-foreground" : "bg-card border border-border"
        }`}
      >
        {message.status === "error" ? (
          <p className="text-destructive">{message.error}</p>
        ) : (
          <div dangerouslySetInnerHTML={{ __html: html }} />
        )}
        {message.status === "streaming" && (
          <span aria-label="streaming" className="inline-flex ml-2 gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:120ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:240ms]" />
          </span>
        )}
      </div>
    </article>
  );
}
```

NOTE: `dangerouslySetInnerHTML` with marked is acceptable for now because the assistant content comes from our own LLM and is text-only. When Plan D adds citation buttons inside markdown, switch to a structured renderer (react-markdown).

- [ ] **Step 4: Install Tailwind typography for `prose` classes.**

```powershell
npm install --save-dev @tailwindcss/typography
```

Add `require("@tailwindcss/typography")` to `tailwind.config.js`'s `plugins` array.

- [ ] **Step 5: Run.**

```powershell
npm test
```

Expected: 3 message-bubble tests PASS.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): MessageBubble with user/assistant variants + streaming indicator"
```

---

## Task 9 — RoutingBadge component

**Files:**
- Create: `frontend/src/components/chat/RoutingBadge.tsx`
- Create: `frontend/tests/components/RoutingBadge.test.tsx`

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/RoutingBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoutingBadge } from "@/components/chat/RoutingBadge";

describe("RoutingBadge", () => {
  it("renders intent + confidence + tier", () => {
    render(
      <RoutingBadge
        decision={{
          intent: "paper_qa", model_tier: "flagship",
          confidence: 0.92, reasoning: "asks about a paper",
        }}
      />,
    );
    expect(screen.getByText(/paper_qa/i)).toBeInTheDocument();
    expect(screen.getByText(/92/i)).toBeInTheDocument();
    expect(screen.getByText(/flagship/i)).toBeInTheDocument();
  });

  it("colors low-confidence (<0.5) badge in destructive style", () => {
    const { container } = render(
      <RoutingBadge
        decision={{
          intent: "chitchat", model_tier: "small",
          confidence: 0.32, reasoning: "uncertain",
        }}
      />,
    );
    expect(container.querySelector("[data-conf=\"low\"]")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Install the badge primitive.**

```powershell
npx shadcn@latest add badge
```

- [ ] **Step 3: Implement.**

`frontend/src/components/chat/RoutingBadge.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
  from "@/components/ui/tooltip";
import type { RoutingDecision } from "@/types/domain";

const intentLabel: Record<RoutingDecision["intent"], string> = {
  paper_search: "Paper search",
  paper_qa: "Paper Q&A",
  slides: "Slides",
  library_stats: "Library stats",
  chitchat: "Chitchat",
};

export function RoutingBadge({ decision }: { decision: RoutingDecision }) {
  const conf = decision.confidence;
  const confLevel = conf >= 0.8 ? "high" : conf >= 0.5 ? "mid" : "low";
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            data-conf={confLevel}
            className="inline-flex items-center gap-2 text-xs"
          >
            <Badge variant={confLevel === "low" ? "destructive" : "secondary"}>
              {intentLabel[decision.intent]}
            </Badge>
            <span className="text-muted-foreground">
              {Math.round(conf * 100)}% · {decision.model_tier}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs text-sm">{decision.reasoning}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
```

- [ ] **Step 4: Run.**

```powershell
npm test
```

Expected: 2 routing-badge tests PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): RoutingBadge with intent label + confidence + reasoning tooltip"
```

---

## Task 10 — TraceInline component

**Files:**
- Create: `frontend/src/components/chat/TraceInline.tsx`
- Create: `frontend/tests/components/TraceInline.test.tsx`

- [ ] **Step 1: Install the collapsible primitive.**

```powershell
npx shadcn@latest add collapsible
```

- [ ] **Step 2: Write the failing test.**

`frontend/tests/components/TraceInline.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TraceInline } from "@/components/chat/TraceInline";

const sampleTrace = [
  {
    run_id: 1, branch: "" as const, step_index: 0, parent_step: null,
    agent: "router", tool: "classify", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 12, token_in: null, token_out: null,
    status: "ok" as const, error: null,
  },
  {
    run_id: 1, branch: "" as const, step_index: 1, parent_step: null,
    agent: "chitchat", tool: "generate", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 240, token_in: null, token_out: null,
    status: "ok" as const, error: null,
  },
];

describe("TraceInline", () => {
  it("starts collapsed with a step count", () => {
    render(<TraceInline trace={sampleTrace} />);
    expect(screen.getByRole("button", { name: /2 steps/i })).toBeInTheDocument();
    expect(screen.queryByText(/router · classify/i)).not.toBeInTheDocument();
  });

  it("expands to show all steps", async () => {
    render(<TraceInline trace={sampleTrace} />);
    await userEvent.click(screen.getByRole("button", { name: /2 steps/i }));
    expect(screen.getByText(/router · classify/i)).toBeInTheDocument();
    expect(screen.getByText(/chitchat · generate/i)).toBeInTheDocument();
  });

  it("flags an error step with destructive styling", async () => {
    const errorTrace = [{ ...sampleTrace[0], status: "error" as const, error: "boom" }];
    const { container } = render(<TraceInline trace={errorTrace} />);
    await userEvent.click(screen.getByRole("button"));
    expect(container.querySelector("[data-status=\"error\"]")).not.toBeNull();
  });
});
```

- [ ] **Step 3: Implement.**

`frontend/src/components/chat/TraceInline.tsx`:

```tsx
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ToolCallRecord } from "@/types/domain";

export function TraceInline({ trace }: { trace: ToolCallRecord[] }) {
  const [open, setOpen] = useState(false);
  if (trace.length === 0) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="mt-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <Icon className="h-3 w-3" /> Trace · {trace.length} {trace.length === 1 ? "step" : "steps"}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 font-mono">
          {trace.map((r) => (
            <li
              key={`${r.branch}-${r.step_index}`}
              data-status={r.status}
              className={`px-2 py-0.5 rounded ${
                r.status === "error"
                  ? "bg-destructive/10 text-destructive"
                  : "text-muted-foreground"
              }`}
            >
              [{r.branch || "main"}#{r.step_index}] {r.agent} · {r.tool} ({r.model ?? "-"}) {r.latency_ms}ms {r.status}
              {r.error && ` — ${r.error}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run.**

```powershell
npm test
```

Expected: 3 TraceInline tests PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): TraceInline collapsible step list with error highlighting"
```

---

## Task 11 — Composer

**Files:**
- Create: `frontend/src/components/chat/Composer.tsx`
- Create: `frontend/tests/components/Composer.test.tsx`

- [ ] **Step 1: Install textarea primitive.**

```powershell
npx shadcn@latest add textarea
```

- [ ] **Step 2: Write the failing test.**

`frontend/tests/components/Composer.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/chat/Composer";

describe("Composer", () => {
  it("submits via the send button", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} disabled={false} />);
    await userEvent.type(screen.getByRole("textbox"), "hello world");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSubmit).toHaveBeenCalledWith("hello world");
  });

  it("submits via Ctrl+Enter", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} disabled={false} />);
    await userEvent.type(screen.getByRole("textbox"), "hi{Control>}{Enter}{/Control}");
    expect(onSubmit).toHaveBeenCalledWith("hi");
  });

  it("disables the send button when disabled prop is true", () => {
    render(<Composer onSubmit={() => {}} disabled={true} />);
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("does not submit empty input", async () => {
    const onSubmit = vi.fn();
    render(<Composer onSubmit={onSubmit} disabled={false} />);
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Implement.**

`frontend/src/components/chat/Composer.tsx`:

```tsx
import { KeyboardEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send } from "lucide-react";

interface Props {
  onSubmit: (text: string) => void;
  disabled: boolean;
}

export function Composer({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-border bg-card p-3">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a paper, search, or just chat… (Ctrl+Enter to send)"
          rows={2}
          className="resize-none"
          disabled={disabled}
        />
        <Button onClick={submit} disabled={disabled} aria-label="Send">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run.**

```powershell
npm test
```

Expected: 4 Composer tests PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): Composer with Ctrl+Enter submit + disabled state"
```

---

## Task 12 — ChatThread with NFR-02 inline states

**Files:**
- Create: `frontend/src/components/chat/ChatThread.tsx`
- Create: `frontend/src/components/states/EmptyState.tsx`
- Create: `frontend/src/components/states/LoadingDots.tsx`
- Create: `frontend/src/components/states/RejectionPill.tsx`

- [ ] **Step 1: Write the three inline states.**

`frontend/src/components/states/EmptyState.tsx`:

```tsx
import { MessageSquare } from "lucide-react";

export function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center text-muted-foreground gap-3">
      <MessageSquare className="h-12 w-12" />
      <p className="text-sm">Start a conversation. Try: "What can you help me with?"</p>
    </div>
  );
}
```

`frontend/src/components/states/LoadingDots.tsx`:

```tsx
export function LoadingDots() {
  return (
    <span
      role="status"
      aria-label="Loading"
      className="inline-flex items-center gap-1"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:120ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:240ms]" />
    </span>
  );
}
```

`frontend/src/components/states/RejectionPill.tsx`:

```tsx
import { ShieldAlert } from "lucide-react";

export function RejectionPill({ reason }: { reason: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-900 dark:text-yellow-200 px-2 py-0.5 text-xs">
      <ShieldAlert className="h-3 w-3" /> Rejected: {reason}
    </span>
  );
}
```

- [ ] **Step 2: Implement ChatThread.**

`frontend/src/components/chat/ChatThread.tsx`:

```tsx
import { useEffect, useRef } from "react";
import type { ChatSession } from "@/types/domain";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { RoutingBadge } from "@/components/chat/RoutingBadge";
import { TraceInline } from "@/components/chat/TraceInline";
import { EmptyState } from "@/components/states/EmptyState";
import { ScrollArea } from "@/components/ui/scroll-area";

export function ChatThread({ session }: { session: ChatSession | null }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, session?.messages[session.messages.length - 1]?.content]);

  if (!session || session.messages.length === 0) {
    return <EmptyState />;
  }

  return (
    <ScrollArea className="flex-1">
      <div className="max-w-3xl mx-auto p-4 space-y-4">
        {session.messages.map((msg, i) => (
          <div key={`${msg.run_id ?? "user"}-${i}`} className="space-y-1">
            <MessageBubble message={msg} />
            {msg.role === "assistant" && msg.routing_decision && (
              <div className="flex justify-start pl-1">
                <RoutingBadge decision={msg.routing_decision} />
              </div>
            )}
            {msg.role === "assistant" && msg.trace && msg.trace.length > 0 && (
              <div className="pl-1">
                <TraceInline trace={msg.trace} />
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
```

NOTE: `RejectionPill` is exported but only rendered once Plan E (sqlite MCP scope rejection) or Plan G (filesystem `..` rejection) produces `status='rejected'` tool_calls. Plan B doesn't currently surface it inline; it's available for the Trace panel to render per-step.

- [ ] **Step 3: Manual visual check (no test — visual & integrated).**

```powershell
npm run dev
```

Open the page, click "New chat", confirm the EmptyState renders. Kill the server.

- [ ] **Step 4: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): ChatThread with auto-scroll + EmptyState/LoadingDots/RejectionPill"
```

---

## Task 13 — Wire ChatPage + send action

**Files:**
- Create: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `ChatPage.tsx`.**

```tsx
import { useChatStore } from "@/store/chat";
import { useChatStream } from "@/hooks/useChatStream";
import { useToast } from "@/components/ui/use-toast";
import { ChatThread } from "@/components/chat/ChatThread";
import { Composer } from "@/components/chat/Composer";

export function ChatPage() {
  const { sessions, activeSessionId, newSession } = useChatStore();
  const { send } = useChatStream();
  const { toast } = useToast();
  const activeSession =
    activeSessionId === null
      ? null
      : sessions.find((s) => s.id === activeSessionId) ?? null;

  const isStreaming =
    activeSession?.messages.some((m) => m.status === "streaming") ?? false;

  const onSubmit = async (text: string) => {
    const sessionId = activeSessionId ?? newSession();
    try {
      await send(sessionId, text);
    } catch (err) {
      toast({
        variant: "destructive",
        title: "Request failed",
        description: err instanceof Error ? err.message : String(err),
      });
    }
  };

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <ChatThread session={activeSession} />
      <Composer onSubmit={onSubmit} disabled={isStreaming} />
    </div>
  );
}
```

- [ ] **Step 2: Slot it into the Shell.**

`frontend/src/App.tsx`:

```tsx
import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { ChatPage } from "@/pages/ChatPage";
import { Toaster } from "@/components/ui/toaster";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <ChatPage />
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
```

- [ ] **Step 3: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): ChatPage wiring (Composer → useChatStream → ChatThread)"
```

---

## Task 14 — End-to-end smoke script (frontend + backend)

**Files:**
- Create: `scripts/smoke_e2e.ps1` (repo root)

This script boots backend + Vite dev server, opens the browser, leaves both running, and prints next-step instructions. It's operator-facing — used to verify the chitchat round-trip with mocked LLM end-to-end.

- [ ] **Step 1: Write the script.**

`scripts/smoke_e2e.ps1`:

```powershell
# Boot backend (mocked LLM) + Vite dev server. Operator manually drives the browser.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace_smoke_e2e"
$env:PAPERHUB_ROUTER_MOCK = '{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"e2e smoke"}'
$env:PAPERHUB_CHITCHAT_MOCK = "Hi from PaperHub! (e2e smoke)"

if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

Push-Location $backendDir
$backend = Start-Process -PassThru -NoNewWindow uv -ArgumentList @(
    "run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8000"
)
Pop-Location

Push-Location $frontendDir
$frontend = Start-Process -PassThru -NoNewWindow npm -ArgumentList @("run", "dev")
Pop-Location

try {
    Write-Host "`nBackend: http://127.0.0.1:8000 (PID $($backend.Id))"
    Write-Host "Frontend: http://127.0.0.1:5173 (PID $($frontend.Id))"
    Write-Host "`nDrive the browser: type 'hello' and Ctrl+Enter."
    Write-Host "Expected: routing badge says 'Chitchat 90% · small', trace shows 2 steps,"
    Write-Host "assistant message is 'Hi from PaperHub! (e2e smoke)'."
    Write-Host "`nCtrl+C to stop both processes." -ForegroundColor Yellow
    Wait-Event
} finally {
    & taskkill.exe /F /T /PID $backend.Id 2>&1 | Out-Null
    & taskkill.exe /F /T /PID $frontend.Id 2>&1 | Out-Null
}
```

- [ ] **Step 2: Mention the script in `README.md`.**

Add under the "Quick start" section:

```markdown
End-to-end smoke (backend + frontend together, mocked LLM):

    .\scripts\smoke_e2e.ps1
```

- [ ] **Step 3: Commit.**

```powershell
git add scripts/smoke_e2e.ps1 README.md
git commit -m "test(e2e): smoke script boots backend + frontend with mocked chitchat"
```

---

## Task 15 — Lint + typecheck gate documentation + commit hooks (optional)

**Files:**
- Modify: `frontend/README.md`
- Modify: `CLAUDE.md` (add frontend gates)

- [ ] **Step 1: Verify all gates pass.**

From `frontend/`:

```powershell
npm test
npm run typecheck
npm run lint
npm run build
```

All four succeed.

- [ ] **Step 2: Append a "Quality gates" section to `frontend/README.md`.**

```markdown
## Quality gates

Must pass before opening a PR:

    npm test          # Vitest + RTL + MSW
    npm run typecheck # tsc strict
    npm run lint      # ESLint
    npm run build     # Vite production build
```

- [ ] **Step 3: Update CLAUDE.md so future Claude sessions know the frontend gates.**

In `CLAUDE.md`, under "Backend quality gates", add a parallel "Frontend quality gates" subsection mirroring the four commands above.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/README.md CLAUDE.md
git commit -m "docs(frontend): document quality gates + update CLAUDE.md"
```

---

## Done state

After Task 15:

- `cd frontend; npm test` — all Vitest tests pass.
- `cd frontend; npm run typecheck` — tsc strict clean.
- `cd frontend; npm run lint` — ESLint clean.
- `cd frontend; npm run build` — Vite production build succeeds.
- `cd backend; uv run pytest` — all backend tests pass (including the new CORS preflight test).
- `.\scripts\smoke_e2e.ps1` boots both processes; manual browser drive shows: New chat → "hello" → routing badge → token stream → final message → expandable trace panel.
- Theme toggle works; system preference is honored on first load.
- All four NFR-02 states are reachable (EmptyState renders by default, LoadingDots/streaming animation while tokens arrive, RejectionPill component available for future rejection-status traces, ErrorToast fires on transport failure).
- No Citation Canvas, no Reference Sources panel, no Search Results, no Compare view — Plans D / G remain to land.

---

## Plan self-review

- **Spec coverage** — every SRS §III-2 component slot for Plan-B scope mapped to a task. Citation Canvas (FR-03), Reference Sources panel (FR-08 UI), Search Results, Compare-split, Slide preview chip are correctly deferred and unreferenced.
- **Placeholder scan** — every step contains real code blocks or real commands. No TBD / TODO.
- **Type consistency** — `RoutingDecision`, `ToolCallRecord`, `ChatMessage`, `ChatSession`, `Intent`, `Branch` shapes match Plan A's Pydantic models exactly. The `branch` literal `["", "A", "B"]` is mirrored.
- **No scope creep** — no react-router, no react-query, no react-markdown (deferred to Plan D), no IndexedDB persistence, no auth.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-paperhub-B-frontend-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with spec + code-quality reviews between tasks. Same flow as Plan A.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
