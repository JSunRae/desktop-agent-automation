# Quick Reference: Common Operations

## Current Validated State

- In-repo status: full repo-root pytest is green, focused orchestration and pilot slices are green, all-repo readiness is green under the documented contracts-only `MASTER_AGENT_REPO_CONFIGS` override, and no in-repo blockers were found in the fresh pass.
- External environment blocker: live OpenAI-backed prompt refresh still fails in this environment with `401 invalid_api_key`.
- Exact-window trading pilot targeting/readiness has been validated; `ready_to_send=true` remains the only green readiness state before live dispatch.

## Master Orchestrator

- Start orchestrator (Windows PowerShell):

  ```powershell
  master
  ```

- Run orchestrator script directly:

  ```powershell
  python .\master.py
  ```

- Tail main automation logs:

  ```powershell
  Get-Content automation\auto_allow.log -Tail 200 -Wait
  ```

## Debugging Windows and Desktops

- List VS Code windows:

  ```powershell
  python debug\debug_vscode_windows.py
  ```

- List virtual desktops:

  ```powershell
  python debug\debug_virtual_desktops.py
  ```

- Reset desktop failure counters:

  ```powershell
  python - << 'EOF'
  from automation.desktop.reliability import reset_all_desktop_failures
  reset_all_desktop_failures()
  EOF
  ```

## Rate Limit and Allow Tracking

- Show current rate status:

  ```powershell
  python - << 'EOF'
  from automation.rate_limit.tracker import format_rate_status
  print(format_rate_status())
  EOF
  ```

  Output includes last 60 minutes and total Allow clicks.

- View recent Allow metrics:

  ```powershell
  Get-Content automation\allow_metrics.jsonl -Tail 50
  ```

## Panel State and Seeding

- Inspect panels and statuses:

  ```powershell
  python - << 'EOF'
  from automation.panel_tracker_core import PanelTracker
  tracker = PanelTracker()
  for key, panel in list(tracker.panels.items())[:10]:
      print(key, panel.status, panel.repo_name)
  EOF
  ```

- Reset panel state (full cleanup):

  ```powershell
  Remove-Item automation\panel_state.json -ErrorAction SilentlyContinue
  ```

## Storage Diagnosis and Cleanup

- Diagnose workspace storage bloat (quick scan):

  ```powershell
  master --run diagnose-storage
  ```

- Deep scan with subfolder breakdown:

  ```powershell
  master --run diagnose-storage -- --deep --top 20
  ```

- JSON output for automation:

  ```powershell
  master --run diagnose-storage -- --top 0 --deep --json
  ```

- Preview cleanup (dry-run, default):

  ```powershell
  master --run cleanup-storage
  ```

- Cleanup for a specific repo (dry-run):

  ```powershell
  master --run cleanup-storage -- --repo my-project
  ```

- Execute cleanup with confirmation:

  ```powershell
  master --run cleanup-storage -- --execute
  ```

- Execute cleanup for one repo, non-interactive (CI):

  ```powershell
  master --run cleanup-storage -- --repo my-project --execute --yes
  ```

- Cleanup items older than 30 days, JSON output:

  ```powershell
  master --run cleanup-storage -- --older-than 30 --json
  ```

## Cost and Metrics

- Run standard automation with Copilot usage monitor enabled for the session:

  ```powershell
  $env:ENABLE_COPILOT_USAGE_MONITOR = "true"
  python run_automation.py
  ```

- Change Copilot usage polling cadence:

  ```powershell
  $env:COPILOT_USAGE_MONITOR_INTERVAL_SECONDS = "120"
  python run_automation.py
  ```

- Check budget alerts:

  ```powershell
  python - << 'EOF'
  from automation.cost_tracker import get_cost_tracker
  print(get_cost_tracker().check_budget_alerts())
  EOF
  ```

- View metrics summary:

  ```powershell
  python scripts\view_metrics.py
  ```

## Cross-Repo Todos

- Refresh cross-repo Todo cache and print summary:

  ```powershell
  python - << 'EOF'
  from pathlib import Path
  from automation.cross_repo_todo_ingestion import CrossRepoTodoIngestionService

  root = Path(".").resolve()
  cache = root / "automation" / "cross_repo_todo_cache.json"
  svc = CrossRepoTodoIngestionService(
      workspace_root=root,
      cache_path=cache,
      refresh_interval_seconds=0,
      search_roots=[root.parent],
      repo_overrides={},
  )
  snap = svc.refresh()
  print("Repos:", [r.repo_name for r in snap.repos])
  EOF
  ```

## Master Orchestrator Config Overrides

- Contracts-only `MASTER_AGENT_REPO_CONFIGS` override for the trading-system layout:

  This is the documented current-branch path for green all-repo readiness in the present environment.

  ```powershell
  $env:MASTER_AGENT_REPO_CONFIGS = @'
  [
    {
      "name": "contracts",
      "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts",
      "docs_dirs": [
        "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\README.md",
        "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\contracts",
        "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\schemas",
        "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\rules",
        "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\contracts\\data_formats"
      ],
      "role": "source of truth"
    },
    {
      "name": "TF",
      "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\TF",
      "docs_dirs": ["\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\TF\\docs"],
      "role": "upstream framework"
    },
    {
      "name": "Trading",
      "repo_root": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\Trading",
      "docs_dirs": ["\\\\wsl.localhost\\Ubuntu-24.04\\home\\jrae\\wsl_projects\\trading-system\\Trading\\docs"],
      "role": "downstream live system"
    }
  ]
  '@
  ```

- Why not `TRADING_SYSTEM_ROOT_WIN` for this case: if only `contracts` changed layout, changing that root would repoint `contracts`, `TF`, and `Trading` together.

- Validate the override:

  ```powershell
  python -m automation.master_prompt_orchestrator --readiness-check --json
  ```

- Expected result: `contracts`, `TF`, and `Trading` all report `live_ready`.

## Orchestration V1 Operator Flow

- Read-only preflight for all managed repos:

  ```powershell
  python scripts\orchestration_v1.py --pilot-preflight --json
  ```

- Read-only preflight for one repo:

  ```powershell
  python scripts\orchestration_v1.py --pilot-preflight --pilot-preflight-repo trading --json
  ```

- Readiness-only probe for one exact repo window:

  ```powershell
  python scripts\orchestration_v1.py --pilot-readiness-only --pilot-readiness-repo trading --pilot-window-id <window_id> --json
  ```

- Live dry-run rehearsal without sending text:

  ```powershell
  python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-dry-run --pilot-dry-run-repo trading --pilot-window-id <window_id> --json
  ```

- Live pilot with fail-closed activation checks:

  ```powershell
  python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-safe-activate --pilot-window-id <window_id> --json
  ```

- Strict first-reply mode for live pilot:

  ```powershell
  python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-known-good-strict --pilot-window-id <window_id> --strict-plain-text
  ```

- Explicit fallback targeting before dispatch:

  ```powershell
  python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-fallback-explicit-target --pilot-fallback-repo trading --pilot-fallback-workspace-path <absolute_workspace_path> --pilot-window-id <window_id> --json
  ```

- Sandbox self-test:

  ```powershell
  python scripts\orchestration_v1.py --pilot-live-dispatch --pilot-sandbox-self-test --pilot-window-id <window_id> --json
  ```

- Operator runbook:

  `docs/ORCHESTRATION_V1_OPERATOR_RUNBOOK.md`

- Strict rejection guide:

  `docs/ORCHESTRATION_V1_STRICT_RESPONSE_GUIDE.md`

---

# Troubleshooting Flowcharts (Textual)

## 1. System Appears Idle / Not Clicking

```text
Start
 |
 v
Is `master` running? -- no --> Start `master` --> End
 |
 yes
 |
 v
Any VS Code windows visible? -- no --> Restore / open VS Code --> End
 |
 yes
 |
 v
Check for `RATE LIMITED` in logs -- yes --> Wait 20–30min, then restart --> End
 |
 no
 |
 v
Run debug_vscode_windows.py and debug_virtual_desktops.py
 |
 v
Are expected windows/desktops listed? -- no --> Fix DESKTOPS_TO_CHECK / desktop config --> End
 |
 yes
 |
 v
Inspect panel_state.json for many STALE/ERROR panels
 |
 v
If corrupted or very stale -> delete panel_state.json and restart
 |
 v
End
```

## 2. Frequent Rate Limiting

```text
Start
 |
 v
Check allow_metrics.jsonl and format_rate_status()
 |
 v
Are allows close to MAX_ALLOWS_PER_HOUR? -- yes --> Lower MAX_ALLOWS_PER_HOUR and restart --> End
 |
 no
 |
 v
Search logs for Try Again detections
 |
 v
Seen often? -- yes --> Increase TRY_AGAIN_COOLDOWN_MINUTES and reduce manual Copilot use --> End
 |
 no
 |
 v
Investigate individual high-cost workflows via cost_metrics.jsonl
 |
 v
Optimize prompts/models per workflow
 |
 v
End
```
