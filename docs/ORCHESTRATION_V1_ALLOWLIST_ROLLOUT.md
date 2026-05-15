# Orchestration V1 Allowlist Calibration Rollout

## Decision

The current pilot allowlist remains intentionally narrow.

Accepted calibrated state:

- Keep category gating restricted to `maintenance`, `analysis`, and `bug`.
- Keep severity gating restricted to `low`.
- Keep source gating restricted to `task`, `handover`, and `report`.
- Keep task classes restricted to `docs_hygiene`, `test_hardening`, and `diagnostics_analysis`.
- Keep high-risk blocked terms in place.
- Narrow the previously over-broad schema and database title blockers to phrase-level guards:
  - `schema migration`
  - `database migration`

This keeps the safety posture fail-closed while reducing false negatives for low-risk docs and test work that mention schema changes without implying a destructive migration.

## Quantitative Basis

Live discovery snapshot used for calibration:

- Total discovered items: `60`
- Eligible before calibration: `8`
- Eligible after calibration: `11`
- Net change: `+3` eligible items

First-failure rejection profile before calibration:

- `task_class_not_allowed`: `27`
- `title_contains_blocked_term`: `16`
- `category_not_allowed`: `8`
- `severity_not_allowed`: `1`

First-failure rejection profile after calibration:

- `task_class_not_allowed`: `27`
- `title_contains_blocked_term`: `13`
- `category_not_allowed`: `8`
- `severity_not_allowed`: `1`

Interpretation:

- The dominant throughput limiter remains task-class filtering, not category or severity.
- The calibrated blocked-term change improved eligibility without widening the broader safety envelope.
- No evidence from the audited snapshot justified widening category, severity, source, or task-class gates.

## Guardrails

1. Do not broaden severity beyond `low` without adding dedicated regression coverage for every newly admitted severity.
2. Do not broaden task classes until low-value navigation artifacts are reduced upstream or separately filtered.
3. Treat `deploy`, `gateway`, `credential`, `secret`, `token`, `production`, `delete`, and `drop` as hard blocked terms unless there is a separate risk review.
4. Evaluate future blocked-term changes one phrase at a time and require measured before/after eligibility impact.
5. Use `diagnostics.selection.pilot_allowlist_reason_counts` and `diagnostics.selection.blocked_term_counts` as the primary calibration evidence, not sample anecdotes alone.

## Staged Rollout

### Stage 1 - Observe

- Run with the current calibrated registry.
- Watch selection diagnostics for drift in:
  - `pilot_allowlist_reason_counts`
  - `blocked_term_counts`
  - `eligible_count`

Success criteria:

- No increase in high-risk task admission.
- Newly eligible items are predominantly docs, tests, fixtures, or low-risk diagnostics.

### Stage 2 - Hold Narrow Policy

- Keep the allowlist narrow if the observed eligible items remain high quality.
- Do not widen category, source, severity, or task-class gates during this stage.

Success criteria:

- Throughput improves without a rise in unsafe dispatch candidates.

### Stage 3 - Revisit Only With New Evidence

- Re-open policy only if diagnostics show another clearly over-broad phrase-level blocker.
- Prefer phrase narrowing over removing a whole rule.
- Pair every policy change with explicit regression tests.

## Regression Coverage

The calibrated behavior is locked by:

- `tests/test_orchestration_v1_golden_path.py::test_orchestration_v1_pilot_allowlist_filters_and_dispatches_safe_class`
- `tests/test_orchestration_v1_golden_path.py::test_orchestration_v1_pilot_allowlist_tracks_reason_breakdown`
- `tests/test_orchestration_v1_golden_path.py::test_orchestration_v1_pilot_allowlist_allows_schema_docs_but_blocks_schema_migration`

## Closure

This closes the allowlist calibration workstream unless future diagnostics justify another targeted phrase-level adjustment.
