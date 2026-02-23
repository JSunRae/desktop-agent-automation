# Quick Reference: Common Operations

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

## Cost and Metrics

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