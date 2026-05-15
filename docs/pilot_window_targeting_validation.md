Pilot Window Targeting Validation

Purpose

This note records the committed evidence used to close the pilot window targeting reliability remediation workstream.

Representative sanitized scenarios

1. Ambiguous equal-strength same-repo windows
   - Fixture: `tests/fixtures/orchestration_v1/targeting_ambiguous_equal_strength.json`
   - Intent: preserve an explicit `ambiguous_repo_window` stop when the evidence is truly tied.

2. Win32-only target with protected self repo visible in UIA
   - Fixture: `tests/fixtures/orchestration_v1/targeting_win32_only_with_self_repo_visible.json`
   - Intent: replace a generic no-match with `repo_window_detected_win32_only` while preserving self-repo rejection.

3. Ranked non-auxiliary candidate preferred
   - Fixture: `tests/fixtures/orchestration_v1/targeting_ranked_non_auxiliary_preferred.json`
   - Intent: reduce avoidable ambiguous stops by deterministically selecting the visible non-auxiliary repo window.

Fixture-backed regressions

- `test_window_targeting_fixture_ambiguous_equal_strength_preserves_stop`
- `test_window_targeting_fixture_win32_only_target_surfaces_real_case`
- `test_window_targeting_fixture_ranked_non_auxiliary_reduces_avoidable_ambiguity`

Validation command

```powershell
& "C:/Users/Pilot/Documents/Vs Code Projects/desktop-agent-automation/.venv/Scripts/python.exe" -m pytest tests/test_orchestration_v1_pilot_flow.py tests/test_orchestration_v1_cli_readiness.py -q
```

Observed result

- `45 passed in 13.72s`

Closure statement

The original pilot window targeting remediation is considered closed when evaluated against the original goals:

1. deterministic and fail-closed repo window selection is implemented
2. self-repo protection remains enforced
3. real failure modes are represented by sanitized committed fixtures
4. representative dry-run targeting behavior is covered by committed regression tests
5. operator guidance exists in the runbook and short checklist

Any remaining orchestration_v1 backlog items are broader follow-on work and are not blockers for this specific targeting remediation.
