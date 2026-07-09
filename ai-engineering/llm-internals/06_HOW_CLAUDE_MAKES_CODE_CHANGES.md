# 🔧 How Claude Makes Code Changes — The Complete Step-by-Step Flow

> **A deep-dive into what happens when you ask Claude to write code, fix bugs, or refactor — tracing every API call, tool execution, and decision point.**

---

## 1. THE BIG PICTURE

When you ask Claude to make a code change, here's the **high-level loop** that runs:

```ascii
                    THE CLAUDE CODE CHANGE LOOP
                    ────────────────────────────

  User says: "Add a health check endpoint"
         │
         ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  1. READ CONTEXT — Understand the current state              │
  │     ├── Read project files                                   │
  │     ├── Search for relevant code                             │
  │     └── Check git status                                     │
  │                                                              │
  │  2. PLAN — Decide what needs to change                       │
  │     ├── Parse requirements                                   │
  │     ├── Identify files to modify                             │
  │     └── Determine change order (dependencies)                 │
  │                                                              │
  │  3. EXECUTE — Make the changes                               │
  │     ├── Apply edits (str_replace / write_file)               │
  │     ├── Handle dependencies (update imports, etc.)           │
  │     └── Verify syntax (optional check)                       │
  │                                                              │
  │  4. VERIFY — Check correctness                               │
  │     ├── Run tests                                            │
  │     ├── Fix any failures                                     │
  │     └── Confirm the change is complete                       │
  │                                                              │
  │  5. REPORT — Tell the user what happened                     │
  │     ├── Summarize changes made                               │
  │     ├── Highlight any issues or decisions                    │
  │     └── Ask for confirmation if needed                       │
  │                                                              │
  └─────────────────────────────────────────────────────────────┘
         │
         ▼
  Done — or — More changes needed (loop back)
```

---

## 2. THE COMPLETE STEP-BY-STEP FLOW (WITH REAL API CALLS)

Let's trace a real example: **"Add a health check endpoint to the FastAPI app"**

### Step 0: User Sends the Request

```ascii
User types: "Add a health check endpoint to the FastAPI app"
                               │
                               ▼
                    Claude Code receives the text
                    Displays it in the terminal
                    Starts processing...
```

### Step 1: Context Gathering (Pre-API)

Before anything hits the Claude API, Claude Code gathers **local context**:

```ascii
Claude Code scans the environment:
  ├── Reads current directory listing
  ├── Checks git status (any uncommitted changes?)
  ├── Reads .gitignore (what to exclude?)
  ├── Detects project language/framework (pyproject.toml, etc.)
  └── Reads relevant config files

This context is PREPENDED to the user message:
  "Current project: FastAPI app in /Users/me/project
   Files: main.py, requirements.txt, Dockerfile
   Git: clean, no uncommitted changes"
```

### Step 2: Prompt Assembly (Claude Code CLI)

Claude Code builds the complete request payload:

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 8192,
  "temperature": 0.0,
  "system": [
    {
      "type": "text",
      "text": "You are Claude, an AI assistant created by Anthropic...
              You have access to tools: read_files, write_file,
              str_replace, run_terminal_command, code_search...
              Rules:
              1. Always read files before making changes
              2. Make minimal, targeted edits
              3. Run tests after changes
              4. Ask for clarification when requirements are ambiguous
              5. Follow project conventions..." ,
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "tools": [
    {
      "name": "read_files",
      "description": "Read the contents of one or more files...",
      "input_schema": {
        "type": "object",
        "properties": {
          "paths": {
            "type": "array",
            "items": {"type": "string"}
          }
        },
        "required": ["paths"]
      }
    },
    {
      "name": "str_replace",
      "description": "Make targeted edits to a file by finding and
                      replacing a specific string...",
      "input_schema": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "old_string": {"type": "string", "description": "Exact text to find"},
          "new_string": {"type": "string", "description": "Replacement text"}
        },
        "required": ["path", "old_string", "new_string"]
      }
    },
    {
      "name": "write_file",
      "description": "Create a new file or overwrite an existing one...",
      "input_schema": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "content": {"type": "string", "description": "Complete file content"},
          "instructions": {"type": "string", "description": "Brief description"}
        },
        "required": ["path", "content"]
      }
    },
    {
      "name": "run_terminal_command",
      "description": "Execute a shell command in the project directory...",
      "input_schema": {
        "type": "object",
        "properties": {
          "command": {"type": "string"},
          "timeout_seconds": {"type": "number", "default": 30}
        },
        "required": ["command"]
      }
    }
    // ... more tools (list_directory, code_search, glob, etc.)
  ],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Add a health check endpoint to the FastAPI app\n
                   [Context: Current directory contains:
                   - main.py (FastAPI app)
                   - requirements.txt
                   - Dockerfile]"
        }
      ]
    }
  ]
}
```

**Total tokens sent in this first request:** ~4,500 tokens

### Step 3: API Request Sent

```ascii
Claude Code CLI                               Anthropic API
     │                                            │
     │  POST https://api.anthropic.com/v1/messages │
     │  Headers:                                   │
     │    Authorization: Bearer sk-ant-***         │
     │    anthropic-version: 2025-01-01            │
     │    Content-Type: application/json           │
     │                                             │
     │  Body: ~4,500 tokens                        │
     │────────────────────────────────────────────►│
     │                                             │
     │  (Waits ~500ms for first token)             │
     │                                             │
```

### Step 4: Streaming Response Received

The response comes back as a stream of **Server-Sent Events (SSE)**:

```ascii
Event 1: message_start
  ┌────────────────────────────────────────────┐
  │ Message ID: msg_01ABC                      │
  │ Usage: input_tokens=4500, output_tokens=0  │
  └────────────────────────────────────────────┘

Event 2: content_block_start (type: text)
  ┌────────────────────────────────────────────┐
  │ Block 0: text block opened                 │
  └────────────────────────────────────────────┘

Events 3-20: content_block_delta (streaming text)
  ┌────────────────────────────────────────────┐
  │ "I'll" → " add" → " a" → " health" → ...  │
  │ Claude Code displays this text in real-time│
  └────────────────────────────────────────────┘

Event 21: content_block_stop
  ┌────────────────────────────────────────────┐
  │ Block 0 complete                           │
  └────────────────────────────────────────────┘

Event 22: content_block_start (type: tool_use)
  ┌────────────────────────────────────────────┐
  │ Tool: "read_files"                         │
  │ Args: {"paths": ["main.py"]}              │
  │ ID: "toolu_abc123"                         │
  └────────────────────────────────────────────┘

Event 23: message_delta
  ┌────────────────────────────────────────────┐
  │ Stop reason: "tool_use"                    │
  │ Output tokens so far: 85                   │
  └────────────────────────────────────────────┘

Event 24: message_stop
  ┌────────────────────────────────────────────┐
  │ Stream complete                            │
  └────────────────────────────────────────────┘
```

### Step 5: Tool Execution (Local)

Claude Code receives the `tool_use` block and executes it **locally**:

```json
// Response from API says: Claude wants to read main.py
{
  "type": "tool_use",
  "id": "toolu_abc123",
  "name": "read_files",
  "input": {"paths": ["main.py"]}
}
```

```ascii
Claude Code CLI:
  1. Validates: "read_files" is an allowed tool
  2. Validates: {"paths": ["main.py"]} matches the tool's JSON schema
  3. Executes: reads /Users/me/project/main.py
  4. Gets content: 340 tokens worth of Python code
  5. Appends result to conversation history:
     {
       "role": "user",
       "content": [{
         "type": "tool_result",
         "tool_use_id": "toolu_abc123",
         "content": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\ndef read_root():\n    return {'Hello': 'World'}"
       }]
     }
```

### Step 6: Second API Call (With Tool Result)

Claude Code sends **another API call** with the updated conversation:

```ascii
Turn 2 API Call:
  System prompt:   ~2,000 tokens  (cached)
  Tool schemas:    ~2,500 tokens  (cached)
  History:         ~4,585 tokens  (previous messages + tool result)
  New message:         ~8 tokens  (same user message — it's still active)
  ─────────────────────────────────────────
  Total input:     ~6,133 tokens

  Wait for response (~300ms this time — less thinking needed)
```

### Step 7: Claude Decides — Edit the File

```json
{
  "content": [
    {
      "type": "text",
      "text": "I can see the app has a single route. Let me add the health check endpoint."
    },
    {
      "type": "tool_use",
      "id": "toolu_def456",
      "name": "str_replace",
      "input": {
        "path": "main.py",
        "old_string": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\ndef read_root():\n    return {'Hello': 'World'}",
        "new_string": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\ndef read_root():\n    return {'Hello': 'World'}\n\n\n@app.get('/health')\ndef health_check():\n    \"\"\"Health check endpoint.\"\"\"\n    return {'status': 'healthy'}"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

### Step 8: Claude Code Applies the Edit Locally

```python
# Claude Code takes the str_replace arguments and:
# 1. Validates the path exists
# 2. Checks that old_string matches EXACTLY in the file
# 3. If old_string is found EXACTLY ONCE, replaces it with new_string
# 4. If old_string is found MULTIPLE times, raises error (needs more context)
# 5. If old_string is NOT found, raises error (file may have changed)

# In this case:
# - Found "from fastapi import FastAPI\napp = FastAPI()\n..." exactly once
# - Replaced with the new version including the /health endpoint
# - File saved to disk
```

### Step 9: Verification — Run Tests

Claude usually follows up with one more API call to verify:

```json
// Claude says: "Let me verify the code works"
{
  "content": [
    {
      "type": "text",
      "text": "The endpoint has been added. Let me verify the syntax is correct."
    },
    {
      "type": "tool_use",
      "id": "toolu_ghi789",
      "name": "run_terminal_command",
      "input": {
        "command": "python -c \"import main; print('Syntax OK')\""
      }
    }
  ]
}
```

### Step 10: Final Response to User

```ascii
Claude Code CLI sends one more API call with the verification result.

Claude responds with text only (stop_reason: "end_turn"):

  "Done! I've added a health check endpoint to your FastAPI app:

   ✅ Added GET /health endpoint that returns {'status': 'healthy'}

   The app structure is:
   - GET /        → Root endpoint
   - GET /health  → Health check endpoint (new)

   You can verify by running: curl http://localhost:8000/health"

This text is streamed to the user in real-time.
```

---

## 3. THE COMPLETE API CALL SEQUENCE (DIAGRAM)

```ascii
USER                    CLAUDE CODE CLI              CLAUDE API
 │                            │                         │
 │  "Add health check"        │                         │
 │───────────────────────────►│                         │
 │                            │                         │
 │                            │ 1. Gather local context │
 │                            │    (files, git, config) │
 │                            │                         │
 │                            │ 2. POST /v1/messages    │
 │                            │────────────────────────►│
 │                            │   Input: ~4,500 tokens  │
 │                            │                         │
 │                            │ 3. SSE stream ◄────────│
 │                            │   Text: "I'll add..."   │
 │                            │   Tool: read_files()    │
 │                            │   Stop: tool_use        │
 │                            │   Output: 85 tokens     │
 │                            │                         │
 │  "Reading main.py..."      │                         │
 │◄───────────────────────────│                         │
 │                            │                         │
 │                            │ 4. Execute read_files   │
 │                            │    (local file system)  │
 │                            │                         │
 │                            │ 5. POST /v1/messages    │
 │                            │    (with tool result)   │
 │                            │────────────────────────►│
 │                            │   Input: ~6,133 tokens  │
 │                            │                         │
 │                            │ 6. SSE stream ◄────────│
 │                            │   Text: "Adding..."     │
 │                            │   Tool: str_replace()   │
 │                            │   Stop: tool_use        │
 │                            │   Output: 62 tokens     │
 │                            │                         │
 │                            │ 7. Execute str_replace  │
 │                            │    (edit main.py)       │
 │                            │                         │
 │                            │ 8. POST /v1/messages    │
 │                            │    (with tool result)   │
 │                            │────────────────────────►│
 │                            │   Input: ~6,257 tokens  │
 │                            │                         │
 │                            │ 9. SSE stream ◄────────│
 │                            │   Text: "Verifying..."  │
 │                            │   Tool: run_terminal()  │
 │                            │   Stop: tool_use        │
 │                            │   Output: 90 tokens     │
 │                            │                         │
 │                            │ 10. Execute bash cmd    │
 │                            │     (python -c import)  │
 │                            │                         │
 │                            │ 11. POST /v1/messages   │
 │                            │────────────────────────►│
 │                            │                         │
 │                            │ 12. SSE stream ◄───────│
 │                            │   Text: "Done! Added"   │
 │                            │   Stop: end_turn        │
 │                            │   Output: 150 tokens    │
 │                            │                         │
 │  "Done! Added /health..."  │                         │
 │◄───────────────────────────│                         │
 │                            │                         │
```

---

## 4. HOW DEBUGGING WORKS (THE BUG-FIX FLOW)

Debugging uses a **different flow pattern** from feature addition:

```ascii
                     THE DEBUG FLOW
                     ──────────────

  User: "This code is throwing a KeyError, can you fix it?"
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  PHASE 1: REPRODUCE                                          │
  │  ├── Read the file where the error occurs                    │
  │  ├── Read the error message / stack trace                    │
  │  └── Run the code to reproduce the error (optional)          │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  PHASE 2: DIAGNOSE                                           │
  │  ├── Trace the code path leading to the error                │
  │  ├── Identify the root cause (not just the symptom)          │
  │  ├── Check for similar issues in the same file               │
  │  └── Formulate a hypothesis: \"The error occurs because...\"   │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  PHASE 3: FIX                                                │
  │  ├── Apply the fix (str_replace / write_file)                │
  │  ├── Consider edge cases                                     │
  │  └── Check for the same bug pattern elsewhere               │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  PHASE 4: VERIFY                                             │
  │  ├── Run the code again to confirm the fix                   │
  │  ├── Run related tests                                       │
  │  └── If still broken, loop back to Phase 2                   │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  PHASE 5: EXPLAIN                                            │
  │  ├── Tell the user what was wrong                            │
  │  ├── Explain what was changed                                │
  │  └── Suggest how to prevent similar issues                   │
  └──────────────────────────────────────────────────────────────┘
```

### Real Debugging Trace

```ascii
User: "I'm getting 'KeyError: 'username'' when I call /users endpoint"

─── API Call 1 ──────────────────────────────────────────────────
  Claude reads main.py to see the /users endpoint
  Claude reads the error traceback (user provided it)

─── API Call 2 ──────────────────────────────────────────────────
  Claude identifies: The /users endpoint expects a 'username' key
  in the request body but doesn't validate it first.
  
  Root cause: No input validation before accessing dict keys.
  
  Claude applies the fix:
    old: username = data["username"]
    new: username = data.get("username")
         if not username:
             raise HTTPException(status_code=400, ...)

─── API Call 3 ──────────────────────────────────────────────────
  Claude runs the endpoint to verify: curl -X POST /users -d '{}'
  Confirms it now returns a proper 400 error instead of 500.

─── API Call 4 ──────────────────────────────────────────────────
  Claude checks for similar patterns in the codebase:
  Searches for other `data["` patterns that might have the same bug.
  
─── Final Response ──────────────────────────────────────────────
  "Found and fixed the KeyError. Root cause: missing input validation.
   Also checked for similar issues in the codebase — no other instances found."
```

---

## 5. HOW CLAUDE DECIDES WHEN TO ASK FOR USER INPUT

This is one of the most important and nuanced behaviors. Claude follows a **confidence-based escalation system**:

### The Decision Tree

```ascii
  User request received
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Does Claude understand the request clearly?                  │
  ├──────────────────────────────────────────────────────────────┤
  │  YES → Proceed with changes                                  │
  │  NO  → Ask user for clarification                            │
  │         Example: "Should this endpoint return JSON or plain   │
  │                  text? Also, should it be authenticated?"     │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Are there ambiguous design choices?                          │
  ├──────────────────────────────────────────────────────────────┤
  │  NO  → Make reasonable defaults and proceed                  │
  │  YES → Flag to user and ask OR make a best-guess decision    │
  │         (depends on the impact of being wrong)               │
  │                                                              │
  │  Low impact (variable name, formatting):                     │
  │    → Make a choice and proceed                                │
  │                                                              │
  │  Medium impact (library choice, architecture):               │
  │    → Make a choice but mention it in the response            │
  │                                                              │
  │  High impact (database, auth, security):                     │
  │    → STOP and ask the user                                   │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Did the tool execution succeed?                              │
  ├──────────────────────────────────────────────────────────────┤
  │  YES → Continue to next step                                 │
  │  NO  → Can Claude fix it without new info?                   │
  │    YES → Fix and retry                                       │
  │    NO  → Report error and ask user                           │
  │         Example: "I tried to edit the file but the exact text│
  │                  wasn't found. Has the file changed?"         │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Did something unexpected happen?                             │
  ├──────────────────────────────────────────────────────────────┤
  │  NO  → Complete and report success                           │
  │  YES → Does Claude understand the unexpected behavior?       │
  │    YES → Explain and adjust                                  │
  │    NO  → Ask user for guidance                               │
  └──────────────────────────────────────────────────────────────┘
```

### Concrete Examples of When Claude Asks vs When It Doesn't

| Scenario | Claude's Behavior | Why |
|----------|------------------|-----|
| **Vague request**: "Make this better" | ❓ **Asks**: "What specifically would you like improved? Performance? Readability? Features?" | Too ambiguous |
| **Missing detail**: "Add error handling" | ❓ **Asks**: "What kind of errors should I handle? Network errors? Validation? Database?" | Multiple valid interpretations |
| **Security-sensitive**: "Add user auth" | ❓ **Asks**: "What auth method? JWT? OAuth? Session-based? Any existing auth provider?" | High impact choice |
| **Uncommon dependency**: "Use library X" | ✅ **Proceeds** (or asks about version) | If it's a known library, proceeds |
| **File-rename impact**: "Rename this function" | ✅ **Proceeds** with searching for all callers | Routine refactoring |
| **Test failure after change** | ✅ **Fixes** and retries automatically | Part of the normal loop |
| **Tool execution error** (str_replace failed) | ❓ **Asks**: "The exact string wasn't found, has the file changed?" | Unexpected error |
| **Ambiguous formatting choice**: "Use tabs vs spaces" | ✅ **Proceeds** with project conventions | Low impact |
| **Adding new dependency**: "Add FastAPI" | ❓ **Asks**: "Which version? Any specific plugins?" | Version choice matters |

---

## 6. HOW MULTI-FILE CHANGES WORK

When a change spans multiple files, Claude follows a **dependency-ordered execution**:

```ascii
                    MULTI-FILE CHANGE FLOW
                    ─────────────────────

  Example: "Add a new /users endpoint with database support"

  ┌──────────────────────────────────────────────────────────────┐
  │  1. IDENTIFY FILES TOUCHED                                    │
  │     ├── app/main.py          — New route                      │
  │     ├── app/models.py        — New User model                 │
  │     ├── app/schemas.py       — New Pydantic schemas           │
  │     ├── app/database.py      — May need new DB function       │
  │     └── tests/test_users.py  — New test file                  │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  2. DETERMINE BUILD ORDER (dependency analysis)               │
  │                                                               │
  │   Files with no dependencies FIRST:                           │
  │     ├── app/models.py       (no internal dependencies)        │
  │     └── app/schemas.py      (no internal dependencies)        │
  │                                                               │
  │   Files that depend on others SECOND:                         │
  │     ├── app/database.py     (uses models)                     │
  │     └── app/main.py         (uses schemas, database)          │
  │                                                               │
  │   Tests LAST:                                                  │
  │     └── tests/test_users.py (uses everything)                 │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  3. APPLY CHANGES IN ORDER                                    │
  │                                                               │
  │  ── API Call: Create models.py (write_file)                   │
  │  ── API Call: Create schemas.py (write_file)                  │
  │  ── API Call: Update database.py (str_replace)                │
  │  ── API Call: Update main.py (str_replace × 2)                │
  │  ── API Call: Create test_users.py (write_file)               │
  │                                                               │
  │  → 5 API calls × ~6,000 tokens = ~30,000 tokens total        │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  4. VERIFY                                                    │
  │     ├── Run import check: python -c "import app"              │
  │     ├── Run tests: pytest tests/test_users.py                 │
  │     └── If failures: diagnose, fix, retry                     │
  └──────────────────────────────────────────────────────────────┘
```

### How Claude Handles Dependencies

```python
# Claude understands dependency ordering implicitly:
# 1. It reads all relevant files first (context gathering)
# 2. It mentally maps which files depend on which
# 3. It creates/modifies files in dependency order
# 4. It verifies that imports work end-to-end

# Example: If main.py imports from models.py and schemas.py,
# Claude creates/modifies models.py and schemas.py FIRST,
# then updates main.py — so imports never break.
```

---

## 7. HOW CLAUDE HANDLES EDITS (str_replace vs write_file)

Claude has two main tools for making changes, and it chooses between them based on the situation:

### str_replace (Targeted Edits)

```python
# Claude uses this when: Making a small change to an existing file
# Advantage: Preserves file history, minimal diff, fewer tokens

# Example: Adding one import
old_string = "from fastapi import FastAPI"
new_string = "from fastapi import FastAPI, HTTPException"

# Claude Code validates:
# 1. The file exists
# 2. old_string is found EXACTLY ONCE
# 3. If found multiple times → error (ambiguity)
# 4. If not found → error (file may have changed since reading)
```

### write_file (Full File Write)

```python
# Claude uses this when:
# - Creating a brand new file
# - The edit is >50% of the file content
# - Multiple scattered changes across the file

# Claude Code validates:
# 1. The parent directory exists
# 2. If overwriting: warns the user first
# 3. Writes the complete file content
```

### How Claude Chooses

```ascii
  ┌──────────────────────────────────────────────────────────┐
  │  Does the file exist?                                     │
  │  NO  → write_file (create new file)                      │
  │  YES → Is the change >50% of the file?                    │
  │    YES → write_file (rewrite entire file)                 │
  │    NO  → Are changes scattered across the file?           │
  │      → Multiple str_replace calls                         │
  │      → OR write_file if >3 scattered edits               │
  └──────────────────────────────────────────────────────────┘
```

---

## 8. THE TOOL EXECUTION PIPELINE

Every tool call goes through this pipeline:

```ascii
┌──────────────────────────────────────────────────────────────────┐
│                    TOOL EXECUTION PIPELINE                        │
│                                                                  │
│  Claude API responds with tool_use                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  1. PARSE & VALIDATE                                      │   │
│  │     ├── Extract tool name, id, input                      │   │
│  │     ├── Validate tool name is in the allowed list         │   │
│  │     ├── Validate input against tool's JSON schema         │   │
│  │     └── Reject hallucinated tools (e.g., "delete_all")   │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  2. SANITIZE                                               │   │
│  │     ├── Sanitize file paths (prevent path traversal)      │   │
│  │     ├── Sanitize command arguments (shell injection)      │   │
│  │     └── Validate within project boundaries                │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  3. EXECUTE                                                │   │
│  │     ├── Run the tool locally                              │   │
│  │     ├── Respect timeouts                                  │   │
│  │     ├── Respect rate limits (per-second, per-tool)        │   │
│  │     └── Capture stdout, stderr, exit code                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  4. FORMAT RESULT                                          │   │
│  │     ├── Truncate large outputs (token budget)             │   │
│  │     ├── Mask sensitive data (API keys, secrets)           │   │
│  │     └── Format as tool_result message                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  5. APPEND TO HISTORY & SEND NEXT API CALL                │   │
│  │     ├── Add tool_result to messages array                 │   │
│  │     ├── Send complete history back to Claude API          │   │
│  │     └── Claude decides: more tools or end_turn            │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. SUMMARY: THE COMPLETE CODE CHANGE LOOP

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                THE COMPLETE CLAUDE CODE CHANGE LOOP                   │
│                                                                      │
│  1. USER SENDS REQUEST                                                │
│     └── Claude Code gathers local context (files, git, config)        │
│                                                                      │
│  2. API CALL #1: Understand + Plan                                    │
│     ├── Send: System + Tools + User message                           │
│     ├── Receive: Streaming text + tool_use (read_files)               │
│     └── Execute: Read file(s) from disk                              │
│                                                                      │
│  3. API CALL #2: Plan + First Edit                                    │
│     ├── Send: Previous + Tool result                                  │
│     ├── Receive: Streaming text + tool_use (str_replace/write_file)   │
│     └── Execute: Edit file(s) on disk                                │
│                                                                      │
│  4. API CALL #3-N: Continue Editing + Handle Dependencies             │
│     ├── Each call adds more context and results                       │
│     ├── Each call costs ~5,000-8,000 input tokens                     │
│     └── Continues until Claude finishes all edits                     │
│                                                                      │
│  5. API CALL (Final): Verify + Report                                 │
│     ├── Run tests to verify correctness                               │
│     ├── If failures: fix and retry (loop back to step 3)              │
│     └── If success: Final response to user (end_turn)                 │
│                                                                      │
│  DECISION POINTS along the way:                                       │
│  ├── Need more context? → Read more files                             │
│  ├── Need clarification? → Ask user                                   │
│  ├── Tool failed? → Retry or report error                             │
│  ├── Tests failed? → Diagnose and fix                                 │
│  └── Unexpected state? → Ask user for guidance                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. KEY TAKEAWAYS

| Concept | Why It Matters |
|---------|---------------|
| **Each tool call = one API round-trip** | 5 edits = 5 API calls × growing context = expensive |
| **Claude reads before writing** | Always: read file → understand → edit. Never blind writes |
| **str_replace is preferred over write_file** | Targetted edits preserve history and show exact changes |
| **Context grows with every turn** | Each tool result is appended, making subsequent calls more expensive |
| **Claude asks only when necessary** | Uses confidence-based escalation: low-impact → proceed, high-impact → ask |
| **Debugging follows a different pattern** | Reproduce → Diagnose → Fix → Verify — more analysis, fewer edits |
| **Multi-file changes are dependency-ordered** | Files with no deps first, dependent files second, tests last |
| **Temperature=0 for coding** | Deterministic — same input always produces same output |
| **Streaming is critical for UX** | First token in ~500ms, full response streamed in real-time |

---

> **Next:** See the [Request/Response Cycle](03_REQUEST_RESPONSE_CYCLE.md) for full token breakdowns, or [System Prompt Engineering](05_SYSTEM_PROMPT_ENGINEERING.md) for how Claude's behavior is defined.
