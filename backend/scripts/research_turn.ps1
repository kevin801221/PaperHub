# Smoke test: three sub-tests for the paper_search tool-calling loop.
#   Sub-test 1 (I-8 #8): vague prompt → clarifying question, zero search_arxiv calls.
#   Sub-test 2 (I-8 #9): library hit → search_library before search_arxiv, library: prefix in add.
#   Sub-test 3 (happy path): clear RAG prompt → at least one add_paper_to_session + papers row.
# Requires a real LLM key (GEMINI_API_KEY or equivalent) in backend/.env.
# Usage: .\scripts\research_turn.ps1
$ErrorActionPreference = "Stop"

# ── 1. Load backend/.env ──────────────────────────────────────────────────────
$backendDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$envFile = Join-Path $backendDir ".env"
if (-not (Test-Path $envFile)) {
    throw "Missing $envFile. Copy backend/.env.example to backend/.env and fill in your API key."
}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if (($val.StartsWith('"') -and $val.EndsWith('"')) -or
        ($val.StartsWith("'") -and $val.EndsWith("'"))) {
        $val = $val.Substring(1, $val.Length - 2)
    }
    if ($val -ne "") { Set-Item -Path "env:$key" -Value $val }
}

# ── Real-flow guard ───────────────────────────────────────────────────────────
$paperQaModel = if ($env:PAPERHUB_PAPER_QA_MODEL) { $env:PAPERHUB_PAPER_QA_MODEL } else { "gemini/gemini-2.5-pro" }
$needsKey = @{
    "gemini"    = "GEMINI_API_KEY"
    "openai"    = "OPENAI_API_KEY"
    "anthropic" = "ANTHROPIC_API_KEY"
}
$provider = ($paperQaModel -split "/", 2)[0]
$keyName  = $needsKey[$provider]
if ($keyName -and -not (Get-Item -Path "env:$keyName" -ErrorAction SilentlyContinue).Value) {
    throw "Model '$paperQaModel' requires env var '$keyName'. Set it in backend/.env."
}

# ── 2. Isolated workspace ─────────────────────────────────────────────────────
$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace\smoke-research"
if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

Remove-Item Env:PAPERHUB_ROUTER_MOCK   -ErrorAction SilentlyContinue
Remove-Item Env:PAPERHUB_CHITCHAT_MOCK -ErrorAction SilentlyContinue

# ── 3. Pre-flight: port 8769 must be free ─────────────────────────────────────
$portInUse = $false
try {
    $tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8769)
    $tcp.Start(); $tcp.Stop()
} catch { $portInUse = $true }
if ($portInUse) {
    throw "Port 8769 already in use. Kill the orphan process and retry."
}

# ── 4. Boot uvicorn ───────────────────────────────────────────────────────────
$server = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backendDir `
    uv -ArgumentList @("run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8769")

# ── Helper: send a /chat request and return the final content string ──────────
function Invoke-Chat {
    param([int]$SessionId, [string]$UserMessage)
    $body = @{ session_id = $SessionId; user_message = $UserMessage } | ConvertTo-Json -Compress
    $tmpBody = Join-Path $env:TEMP "smoke_research_body_$SessionId.json"
    [System.IO.File]::WriteAllText($tmpBody, $body)
    $sseRaw = & curl.exe -N -s -X POST http://127.0.0.1:8769/chat `
        -H "Content-Type: application/json" `
        --data-binary "@$tmpBody"
    if ($LASTEXITCODE -ne 0) { throw "curl.exe failed (session $SessionId)." }

    # Parse SSE — find the 'final' event data.
    $finalContent = $null
    $currentEvent = $null
    foreach ($line in ($sseRaw -split "`n")) {
        $line = $line.TrimEnd("`r")
        if ($line.StartsWith("event:")) {
            $currentEvent = $line.Substring(6).Trim()
        } elseif ($line.StartsWith("data:") -and $currentEvent -eq "final") {
            $dataJson = $line.Substring(5).Trim()
            try {
                $obj = $dataJson | ConvertFrom-Json
                $finalContent = $obj.content
            } catch { }
        } elseif ($line -eq "") {
            $currentEvent = $null
        }
    }
    if ($null -eq $finalContent) {
        throw "No 'final' SSE event found for session $SessionId. Raw:`n$sseRaw"
    }
    return $finalContent
}

# ── Helper: run a Python SQLite query, return trimmed lines ──────────────────
function Invoke-SqliteQuery {
    param([string]$DbPath, [string]$Query)
    $result = & uv run --project $backendDir python -c @'
import sqlite3, sys
db, q = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(db)
for row in conn.execute(q).fetchall():
    print("|".join(str(c) for c in row))
conn.close()
'@ $DbPath $Query
    if ($LASTEXITCODE -ne 0) { throw "SQLite query failed: $Query" }
    return @($result | Where-Object { $_ -ne "" })
}

try {
    # ── 5. Wait for /health (30 s) ────────────────────────────────────────────
    $healthy = $false
    for ($i = 0; $i -lt 150; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8769/health -ErrorAction Stop | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    if (-not $healthy) { throw "Server did not become healthy within 30 s." }
    Write-Host "Server up on :8769."

    # ── 6. Pre-create sessions 4, 5, 6, 10 ───────────────────────────────────
    $dbPath = Join-Path $env:PAPERHUB_WORKSPACE "paperhub.db"
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-Path $dbPath) { break }
        Start-Sleep -Milliseconds 200
    }
    & uv run --project $backendDir python -c @'
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
conn.execute("PRAGMA foreign_keys = ON")
for sid, title in [(4,"smoke-r1"),(5,"smoke-r2"),(6,"smoke-r3"),(10,"smoke-lib")]:
    conn.execute("INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (?, ?)", (sid, title))
conn.commit()
conn.close()
'@ $dbPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to pre-create chat_sessions rows." }

    # ═══════════════════════════════════════════════════════════════════════════
    # Sub-test 1 (I-8 #8): vague prompt → clarifying question, zero arxiv calls.
    # ═══════════════════════════════════════════════════════════════════════════
    Write-Host "`n=== Sub-test 1: vague prompt → clarifying question ==="
    $final1 = Invoke-Chat -SessionId 4 -UserMessage "find me good ML papers"
    Write-Host "Response: $($final1.Substring(0, [Math]::Min(300, $final1.Length)))"

    # Must contain a '?' — heuristic for clarifying question.
    if ($final1 -notmatch '\?') {
        throw "ASSERTION I-8 #8: clarifying question expected (response should contain '?'). Got:`n$final1"
    }

    # Get run_id for session 4 (most recent run).
    $runRows1 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT id FROM runs WHERE session_id = 4 ORDER BY id DESC LIMIT 1"
    if ($runRows1.Count -eq 0) { throw "No run found for session 4." }
    $runId1 = $runRows1[0].Trim()

    # Must have at least one paper_search:plan tool_call row.
    $planRows1 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT COUNT(*) FROM tool_calls WHERE run_id = $runId1 AND tool = 'paper_search:plan'"
    $planCount1 = [int]($planRows1[0].Trim())
    if ($planCount1 -lt 1) {
        throw "ASSERTION I-8 #8: expected >= 1 tool_calls row with tool='paper_search:plan', got $planCount1"
    }

    # Must have ZERO search_arxiv calls.
    $arxivRows1 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT COUNT(*) FROM tool_calls WHERE run_id = $runId1 AND tool LIKE 'paper_search:search_arxiv%'"
    $arxivCount1 = [int]($arxivRows1[0].Trim())
    if ($arxivCount1 -ne 0) {
        throw "ASSERTION I-8 #8: expected 0 search_arxiv calls for vague prompt, got $arxivCount1"
    }
    Write-Host "Sub-test 1 PASS — clarifying question returned, plan_calls=$planCount1, arxiv_calls=0"

    # ═══════════════════════════════════════════════════════════════════════════
    # Sub-test 2 (I-8 #9): library hit → library-first preference.
    # ═══════════════════════════════════════════════════════════════════════════
    Write-Host "`n=== Sub-test 2: library hit → library-first preference ==="
    # Pre-ingest 1706.03762 into session 10 (the deduplicated library).
    Write-Host "Pre-ingesting 1706.03762 into session 10 (library pre-seed)..."
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8769/papers" `
        -ContentType "application/json" `
        -Body (@{ session_id = 10; arxiv_id = "1706.03762" } | ConvertTo-Json -Compress) | Out-Null
    Write-Host "Library pre-seed done."

    $final2 = Invoke-Chat -SessionId 5 -UserMessage "I want the original transformer paper"
    Write-Host "Response: $($final2.Substring(0, [Math]::Min(300, $final2.Length)))"

    # Response must mention the transformer paper.
    if ($final2 -notmatch '(?i)(transformer|attention is all you need|vaswani)') {
        throw "ASSERTION I-8 #9: response should name the transformer paper. Got:`n$final2"
    }

    # Get run_id for session 5.
    $runRows2 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT id FROM runs WHERE session_id = 5 ORDER BY id DESC LIMIT 1"
    if ($runRows2.Count -eq 0) { throw "No run found for session 5." }
    $runId2 = $runRows2[0].Trim()

    # search_library must appear before any search_arxiv (by step_index).
    $libStep = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT MIN(step_index) FROM tool_calls WHERE run_id = $runId2 AND tool = 'paper_search:search_library'"
    $arxivStep = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT MIN(step_index) FROM tool_calls WHERE run_id = $runId2 AND tool LIKE 'paper_search:search_arxiv%'"
    $libStepVal   = if ($libStep[0].Trim() -eq "" -or $libStep[0].Trim() -eq "None") { $null } else { [int]$libStep[0].Trim() }
    $arxivStepVal = if ($arxivStep[0].Trim() -eq "" -or $arxivStep[0].Trim() -eq "None") { $null } else { [int]$arxivStep[0].Trim() }

    if ($null -eq $libStepVal) {
        throw "ASSERTION I-8 #9: expected a paper_search:search_library tool_calls row for session 5."
    }
    if ($null -ne $arxivStepVal -and $libStepVal -ge $arxivStepVal) {
        throw "ASSERTION I-8 #9: search_library (step $libStepVal) must appear BEFORE search_arxiv (step $arxivStepVal)."
    }

    # add_paper_to_session with args_redacted_json containing "library:" must exist.
    $addLibRows = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT COUNT(*) FROM tool_calls WHERE run_id = $runId2 AND tool = 'paper_search:add_paper_to_session' AND args_redacted_json LIKE '%library:%'"
    $addLibCount = [int]($addLibRows[0].Trim())
    if ($addLibCount -lt 1) {
        throw "ASSERTION I-8 #9: expected >= 1 add_paper_to_session call with 'library:' in args for session 5, got $addLibCount"
    }
    Write-Host "Sub-test 2 PASS — search_library first (step $libStepVal), add with library: prefix found"

    # ═══════════════════════════════════════════════════════════════════════════
    # Sub-test 3 (happy path): clear prompt, no library hit.
    # ═══════════════════════════════════════════════════════════════════════════
    Write-Host "`n=== Sub-test 3: clear prompt, no library hit → add papers ==="
    $final3 = Invoke-Chat -SessionId 6 -UserMessage "find recent papers about retrieval augmented generation"
    Write-Host "Response: $($final3.Substring(0, [Math]::Min(300, $final3.Length)))"

    # Get run_id for session 6.
    $runRows3 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT id FROM runs WHERE session_id = 6 ORDER BY id DESC LIMIT 1"
    if ($runRows3.Count -eq 0) { throw "No run found for session 6." }
    $runId3 = $runRows3[0].Trim()

    # At least one add_paper_to_session call.
    $addRows3 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT COUNT(*) FROM tool_calls WHERE run_id = $runId3 AND tool = 'paper_search:add_paper_to_session'"
    $addCount3 = [int]($addRows3[0].Trim())
    if ($addCount3 -lt 1) {
        throw "ASSERTION: expected >= 1 add_paper_to_session tool_calls row for session 6, got $addCount3"
    }

    # At least one enabled papers row for session 6.
    $papersRows3 = Invoke-SqliteQuery -DbPath $dbPath -Query "SELECT COUNT(*) FROM papers WHERE session_id = 6 AND enabled = 1"
    $papersCount3 = [int]($papersRows3[0].Trim())
    if ($papersCount3 -lt 1) {
        throw "ASSERTION: expected >= 1 enabled papers row for session 6, got $papersCount3"
    }
    Write-Host "Sub-test 3 PASS — add_paper_to_session calls=$addCount3, enabled papers for session 6=$papersCount3"

    Write-Host "`nPASS: research_turn smoke test complete (all 3 sub-tests)."

} finally {
    & taskkill.exe /F /T /PID $server.Id 2>&1 | Out-Null
    if (Test-Path $env:PAPERHUB_WORKSPACE) {
        Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE -ErrorAction SilentlyContinue
    }
}
