# ADR-0003: Rate Limiting Strategy for Allow Clicks

## Status

Accepted

## Context

The auto-allow agent can trigger Copilot API rate limits if it clicks Allow too frequently or ignores explicit `Try Again` signals. We must:

- Respect organizational quotas.
- Avoid flapping between allowed and rate-limited states.
- Provide clear diagnostics and recovery procedures.

## Decision

We implemented a layered rate limiting strategy:

1. **Per-hour Allow tracking** via `automation.rate_limit.tracker`:
   - Uses a deque of `(timestamp, window_title)` events.
   - Enforces `MAX_ALLOWS_PER_HOUR` within `ALLOW_EVENT_RETENTION_MINUTES`.
   - Exposes `get_rate_limit_wait_seconds()` and `format_rate_status()`.

2. **UI-based detection of rate limits** via `automation.ui.button_clicker`:
   - Searches for `Try Again` buttons after Allow clicks.
   - Invokes `trigger_rate_limit_cooldown()` which:
     - Starts a global cooldown (via `automation.rate_limit.cooldown`).
     - Plays an audio alert.
     - Logs a prominent message.

## Consequences

- The system slows down proactively as it approaches rate limits, reducing hard failures.
- Production behavior depends on configuration (`MAX_ALLOWS_PER_HOUR`, `TRY_AGAIN_COOLDOWN_MINUTES`).
- Future changes to Copilot’s rate limit UI must be reflected in button detection heuristics.
