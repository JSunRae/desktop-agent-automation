# Orchestration V1 Fixtures

This directory is reserved for sanitized, stable orchestration fixtures.

- Do not copy files directly from `state/orchestration/` into git.
- Remove run IDs, absolute paths, timestamps, repo-local secrets, and any machine-specific details before keeping a sample here.
- Prefer one canonical sample per behavior under test, with names that describe the scenario rather than the original run.
- Archive raw runtime outputs outside git if you need full-fidelity forensic records.

Current representative targeting fixtures:

- `targeting_ambiguous_equal_strength.json`: two same-repo windows remain intentionally ambiguous even if one is foreground.
- `targeting_win32_only_with_self_repo_visible.json`: UIA sees only the protected self repo while Win32 finds the intended target off-desktop/cloaked.
- `targeting_ranked_non_auxiliary_preferred.json`: same-repo windows are reduced to one deterministic non-auxiliary selection.
