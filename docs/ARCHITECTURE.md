# Desktop Auto-Allow Agent - Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR DESKTOP (Windows)                      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   VS Code Window                         │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────┐         │  │
│  │  │  GitHub Copilot Agent Chat                │         │  │
│  │  │                                            │         │  │
│  │  │  Agent is requesting permission to:       │         │  │
│  │  │  • Run terminal commands                  │         │  │
│  │  │  • Create files                           │         │  │
│  │  │                                            │         │  │
│  │  │         ┌────────────┐  ┌──────────┐      │         │  │
│  │  │         │   Allow    │  │  Deny    │      │         │  │
│  │  │         └────────────┘  └──────────┘      │         │  │
│  │  │              ▲                             │         │  │
│  │  │              │ (3) Click here              │         │  │
│  │  └──────────────┼─────────────────────────────┘         │  │
│  └────────────────┼───────────────────────────────────────┐│  │
│                   │                                        ││  │
└───────────────────┼────────────────────────────────────────┼┘  │
                    │                                        │   │
                    │                                        │   │
       ┌────────────┴────────────┐                          │   │
       │  (3) Execute Click      │                          │   │
       │  pyautogui.click(x, y)  │                          │   │
       └─────────────────────────┘                          │   │
                    ▲                                        │   │
                    │                                        │   │
┌───────────────────┴────────────────────────────────────────┴───┘
│          Python: desktop_auto_allow_agent.py                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Every 60 seconds:                                              │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  1. Capture Screenshot                                   │  │
│  │     screenshot = ImageGrab.grab()                        │  │
│  │     screenshot_b64 = base64.encode(screenshot)           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  2. Send to OpenAI Responses API                         │  │
│  │                                                          │  │
│  │     client.responses.create(                            │  │
│  │         model="computer-use-preview",                   │  │
│  │         tools=[{"type": "computer_use_preview", ...}],  │  │
│  │         input=[{                                        │  │
│  │             "type": "input_text",                       │  │
│  │             "text": "Find Copilot approval button..."   │  │
│  │         }, {                                            │  │
│  │             "type": "input_image",                      │  │
│  │             "image_url": "data:image/png;base64,..."    │  │
│  │         }],                                             │  │
│  │         truncation="auto"                               │  │
│  │     )                                                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
└─────────────────────────┼───────────────────────────────────────┘
                          │
         ╔════════════════╧════════════════╗
         ║   OpenAI Computer Use API      ║
         ║   (computer-use-preview model) ║
         ╚════════════════╤════════════════╝
                          │
                          ▼
         ┌─────────────────────────────────┐
         │  Model analyzes screenshot      │
         │  • Detects UI elements          │
         │  • Identifies approval buttons  │
         │  • Checks for rate limits       │
         │  • Returns structured action    │
         └─────────────────────────────────┘
                          │
                          ▼
         ┌─────────────────────────────────────────────┐
         │  Response (one of):                         │
         │                                             │
         │  A) computer_call item:                     │
         │     {                                       │
         │       "type": "computer_call",              │
         │       "action": {                           │
         │         "type": "click",                    │
         │         "x": 1234,                          │
         │         "y": 567                            │
         │       }                                     │
         │     }                                       │
         │     + text: "STATUS: CLICKED"               │
         │                                             │
         │  B) text item only:                         │
         │     "STATUS: NO_BUTTON"                     │
         │                                             │
         │  C) text item only:                         │
         │     "STATUS: RATE_LIMITED"                  │
         │     (triggers 20-minute cooldown)           │
         └─────────────────────────────────────────────┘
                          │
                          ▼
         ┌─────────────────────────────────────────────┐
         │  Python processes response:                 │
         │                                             │
         │  if item.type == "computer_call":           │
         │      click_action = {                       │
         │          "x": item.action.x,                │
         │          "y": item.action.y                 │
         │      }                                      │
         │      pyautogui.click(x, y)                  │
         │      status = "CLICKED"                     │
         │                                             │
         │  elif "RATE_LIMITED" in text:               │
         │      wait 20 minutes                        │
         │                                             │
         │  else:                                      │
         │      wait 60 seconds                        │
         └─────────────────────────────────────────────┘
                          │
                          ▼
         ┌─────────────────────────────────────────────┐
         │  Log activity to auto_allow.log             │
         │  Wait (60s or 20min)                        │
         │  Repeat                                     │
         └─────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════

KEY DIFFERENCES FROM ORIGINAL DESIGN:

❌ OLD (INCORRECT):
   - Used chat.completions.create()
   - Parsed coordinates from text: "click at (x, y)"
   - No tool configuration
   - System prompt explained how to use computer

✅ NEW (CORRECT):
   - Uses responses.create()
   - Gets structured action: item.action.x, item.action.y
   - Proper computer_use_preview tool config
   - Streamlined prompt (model knows computer use)

═══════════════════════════════════════════════════════════════════

TIMING DIAGRAM:

Time     Action
─────    ──────────────────────────────────────────────────────
0:00     Capture screenshot → Send to API
0:02     Receive response: STATUS: NO_BUTTON
0:02     Wait 60 seconds...
1:02     Capture screenshot → Send to API
1:04     Receive response: STATUS: CLICKED (clicked button)
1:04     Wait 60 seconds...
2:04     Capture screenshot → Send to API
2:06     Receive response: STATUS: RATE_LIMITED
2:06     Wait 20 minutes...
22:06    Capture screenshot → Send to API
22:08    Receive response: STATUS: NO_BUTTON
22:08    Wait 60 seconds...
...

═══════════════════════════════════════════════════════════════════

SAFETY LAYERS:

1. System Prompt Constraints
   ↓
2. Model's Built-in Safety Training
   ↓
3. Conservative Status Reporting
   ↓
4. Local Execution Validation (pyautogui failsafe)
   ↓
5. Comprehensive Logging
   ↓
6. Optional: Dry-run mode (--dry-run)

═══════════════════════════════════════════════════════════════════

## Idle Master-Agent Workflow (New)

```
Allow clicked? ──yes──▶ record event + panel ──▶ metrics jsonl log (every 5 min)
      │
      no (for ≥60 min)
      ▼
Fetch docs from WSL paths → trim/pack text → OpenAI prompt request →
write 10-task batch into tasks/generated_prompts + latest.txt → operator feeds
them to sub-agents or automation
```

- History of the last 60 minutes of `Allow` clicks is stored in memory so we know
  how many unique panels are active and when the system is idle.
- Those snapshots are appended to `automation/allow_metrics.jsonl`, giving us the
  data needed to tune how aggressively we click without tripping rate limits.
- Once the system has been idle for the configured window, the master
  orchestrator gathers documentation from WSL, asks OpenAI for 10 conflict-free
  prompts (each tagged with the recommended model), and drops the batch into
  `tasks/generated_prompts/` so you can open fresh agent chats immediately.

## Cross-Repo Todo Ingestion (New)

The master orchestration layer maintains a refreshable, on-disk cache of `Todo.md`
items discovered in sibling repositories (Windows and `\\wsl.localhost\...` paths).
This cache is used to surface cross-repo priorities and blockers without requiring
the master orchestrator to fully ingest every repository.

Workflow:

1. Discovery: scan the workspace parent directory for sibling repos and check
   each repo for `Todo.md` and/or `docs/Todo.md`.
2. Parsing: extract bullet/numbered items and infer `priority` (e.g., `P0`) and
   `blocked` / `blocked by ...` hints.
3. Cache: persist a JSON snapshot to `automation/cross_repo_todo_cache.json`.
4. Prompt context: `automation/master_prompt_orchestrator.py` injects a synthetic
   `cross_repo_todos_summary.md` document slice into the context bundle.

Configuration (environment variables):

- `CROSS_REPO_TODO_ENABLED`: enable/disable ingestion (default: true)
- `CROSS_REPO_TODO_REFRESH_INTERVAL_SECONDS`: refresh cadence (default: 300)
- `CROSS_REPO_TODO_CACHE_PATH`: snapshot JSON path
- `CROSS_REPO_TODO_SEARCH_ROOTS`: extra scan roots (JSON array or `;`-separated)
- `CROSS_REPO_TODO_REPO_OVERRIDES`: explicit repo roots (`{"repo": "path"}` or `repo=path;...`)
