# ADR-0001: Panel Tracking and Persistent State

## Status

Accepted

## Context

The system needs to track many Copilot panels across multiple VS Code windows and desktops. Each panel can have a long-running lifecycle with multiple Allow clicks, output updates, and follow-up prompts. We need:

- A durable record of panel status across restarts.
- Support for classification-based transitions (COMPLETED, NEEDS_INPUT, ERROR, etc.).
- Per-repo prompt rotation and assignment tracking.

## Decision

We introduced `automation.panel_tracker_core.PanelTracker` and `automation.panel_state.PanelState` as the canonical source of truth for panel lifecycle, persisted to `PANEL_STATE_PATH` (default `private/runtime/panel_state.json`).

Key aspects:

- Panel identity is derived from `(window_title, panel_id)` keys.
- The tracker applies periodic time-based transitions (IDLE, FINISHED, STALE).
- Response parsing results drive higher-level statuses (COMPLETED, NEEDS_INPUT, ERROR).
- Repo-specific indices (`repo_prompt_indices`) support per-repo prompt scheduling.

## Consequences

- Panel state can survive process restarts and allows the master orchestrator to resume where it left off.
- Stale or corrupted state requires explicit cleanup (see `docs/PANEL_LIFECYCLE.md`).
- Changes to response categories or thresholds must consider their impact on persisted state.
