Pilot Window Targeting Checklist

Use this as the short form of `docs/ORCHESTRATION_V1_OPERATOR_RUNBOOK.md`.

Readiness-only flow

1. Run pilot preflight for the intended repo and verify the selection reason is selected_single_match or selected_best_ranked_match.
2. If the reason is repo_window_detected_win32_only, bring the target repo window onto the active desktop or use explicit fallback open for the exact workspace path.
3. If the reason is ambiguous_repo_window, copy one exact readiness_command from preflight output and use that window_id for readiness-only.
4. Run readiness-only with the selected window id and confirm ready_to_send is true.
5. If readiness is blocked, follow the reported operator guidance before retrying.

Live-dispatch flow

1. Start from a successful preflight or readiness-only result for the exact target repo window.
2. Prefer an explicit window id when multiple repo windows exist.
3. Use dry-run first when testing a new targeting setup to confirm the selected window id and title without focusing or sending.
4. Run live dispatch only after readiness reports ready_to_send.
5. If fallback is required, use the exact workspace path and only retry after the newly opened repo window becomes visible in preflight.

Fast rules

1. Never skip preflight for a new target repo window.
2. Never treat `repo_window_detected_win32_only` as ready-to-send.
3. Never use fallback to solve `ambiguous_repo_window`; use an explicit window id instead.
4. Never run live pilot until readiness says `ready_to_send`.
