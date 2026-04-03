# Agent Handover Document
Generated: 2026-03-21T13:34:14   Repo: contracts


## North Star Goal
## NORTH STAR — STAY ON GOAL

**Primary goal:** Lead phased execution to reach repeatable seconds-model paper-trading readiness first, then close highest-risk data/infra/contract gaps for hourly/gap reliability, stock-finder progression, and RL offline foundation.

**Work currently in-flight (DO NOT duplicate):**
  - [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

**Repo ownership:**
  - **contracts**: JSON Schemas (manifest, bars, L2, gap-opener); JSON-Logic promotion rules; canonical fixtures and checksums
  - **TF**: ML model training and evaluation; feature and label engineering; experiment tracking (W&B)
  - **Trading**: data acquisition and orchestration; IB gateway lifecycle (headless, paper, live); market data pipelines (IBKR, DataBento)

Confirm that your work targets the correct repo and does not overlap with any in-flight task listed above before proceeding.

## Your Repo: contracts
Owns: JSON Schemas (manifest, bars, L2, gap-opener), JSON-Logic promotion rules, canonical
  fixtures and checksums, schema versioning and governance

  Boundaries (do not cross):
    * Schemas only — no model training, no execution logic
    * Every schema change must be backward-compatible or versioned
    * Changes here affect BOTH TF and Trading — coordinate carefully

## P0 Tasks (highest priority)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P0] [Trading] tf1-l2-depth-delivery-window-20251213: TF1 Level 2 depth delivery window
  - [P0] [Trading] tf1-gap-opener-migration-20251209: TF_1 gap opener migration
  - [P0] [Trading] tf1-l2-depth-investigation-followup: TF_1 L2 depth investigation followup
  - [P0] [Trading] tw-alignment-delivery-20260224: TF_1 alignment 2026-02-19: delivery status and action plan
  - [P0] [Trading] gateway-api-listener-restore-20260227: Restore IB Gateway API listener ports
  - [P0] [Trading] raw-bars-manifest-loop-closure-20260227: Close Ask #1 raw bars confirmation loop
  - [P0] [Trading] production-readiness-staged-path-20260318: Staged production readiness execution

## In-Progress Tasks (across all repos)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P1] [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [P2] [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

## Coordination Warnings
  Overlaps:
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] release-owner-seconds-rc-20260318: both touch: seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: paper_trading, seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] inspect-schema-ml-paths-20260209: both touch: contracts_schema
  - [HIGH] [Trading] release-owner-seconds-rc-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: seconds_model
  - [HIGH] [Trading] tf1-l2-depth-regression-20260118 OVERLAPS [Trading] tf1-l2-depth-delivery-window-20251213: both touch: l2_orderbook
  Drifts:
  - [MEDIUM] [Trading] recapture-l2-shallow-databento-20260122: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] markdownlint-review-20260221: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] tf1-openbid-openask-investigation-20260222: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] backlog-reconciliation-focus-window-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] option-b-default-option-a-rehearsal-plan-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "

## Instructions for Incoming Agent
You are taking over the contracts repo panel from a previous agent session.
Read the above context carefully, then:
  1. Confirm you understand the North Star goal and your repo boundaries.
  2. Review the in-progress tasks — pick up where the previous agent left off.
  3. Check for any coordination warnings and avoid duplicating work.
  4. Begin with a brief status report: what you know, what you plan to do next.
  5. Stay strictly within contracts/ — redirect out-of-scope work to the correct repo.


========================================================================

# Agent Handover Document
Generated: 2026-03-21T13:34:14   Repo: TF


## North Star Goal
## NORTH STAR — STAY ON GOAL

**Primary goal:** Lead phased execution to reach repeatable seconds-model paper-trading readiness first, then close highest-risk data/infra/contract gaps for hourly/gap reliability, stock-finder progression, and RL offline foundation.

**Work currently in-flight (DO NOT duplicate):**
  - [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

**Repo ownership:**
  - **contracts**: JSON Schemas (manifest, bars, L2, gap-opener); JSON-Logic promotion rules; canonical fixtures and checksums
  - **TF**: ML model training and evaluation; feature and label engineering; experiment tracking (W&B)
  - **Trading**: data acquisition and orchestration; IB gateway lifecycle (headless, paper, live); market data pipelines (IBKR, DataBento)

Confirm that your work targets the correct repo and does not overlap with any in-flight task listed above before proceeding.

## Your Repo: TF
Owns: ML model training and evaluation, feature and label engineering, experiment tracking
  (W&B), model export and manifest generation, data preparation from Trading outputs

  Boundaries (do not cross):
    * Stay within TF/ — do NOT write trading execution code
    * Export models to contracts/ schema format only
    * Use W&B for all experiment logging
    * Do NOT commit changes to Trading/ or contracts/ directly

## P0 Tasks (highest priority)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P0] [Trading] tf1-l2-depth-delivery-window-20251213: TF1 Level 2 depth delivery window
  - [P0] [Trading] tf1-gap-opener-migration-20251209: TF_1 gap opener migration
  - [P0] [Trading] tf1-l2-depth-investigation-followup: TF_1 L2 depth investigation followup
  - [P0] [Trading] tw-alignment-delivery-20260224: TF_1 alignment 2026-02-19: delivery status and action plan
  - [P0] [Trading] gateway-api-listener-restore-20260227: Restore IB Gateway API listener ports
  - [P0] [Trading] raw-bars-manifest-loop-closure-20260227: Close Ask #1 raw bars confirmation loop
  - [P0] [Trading] production-readiness-staged-path-20260318: Staged production readiness execution

## In-Progress Tasks (across all repos)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P1] [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [P2] [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

## Coordination Warnings
  Overlaps:
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] release-owner-seconds-rc-20260318: both touch: seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: paper_trading, seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] inspect-schema-ml-paths-20260209: both touch: contracts_schema
  - [HIGH] [Trading] release-owner-seconds-rc-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: seconds_model
  - [HIGH] [Trading] tf1-l2-depth-regression-20260118 OVERLAPS [Trading] tf1-l2-depth-delivery-window-20251213: both touch: l2_orderbook
  Drifts:
  - [MEDIUM] [Trading] recapture-l2-shallow-databento-20260122: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] markdownlint-review-20260221: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] tf1-openbid-openask-investigation-20260222: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] backlog-reconciliation-focus-window-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] option-b-default-option-a-rehearsal-plan-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "

## Instructions for Incoming Agent
You are taking over the TF repo panel from a previous agent session.
Read the above context carefully, then:
  1. Confirm you understand the North Star goal and your repo boundaries.
  2. Review the in-progress tasks — pick up where the previous agent left off.
  3. Check for any coordination warnings and avoid duplicating work.
  4. Begin with a brief status report: what you know, what you plan to do next.
  5. Stay strictly within TF/ — redirect out-of-scope work to the correct repo.


========================================================================

# Agent Handover Document
Generated: 2026-03-21T13:34:14   Repo: Trading


## North Star Goal
## NORTH STAR — STAY ON GOAL

**Primary goal:** Lead phased execution to reach repeatable seconds-model paper-trading readiness first, then close highest-risk data/infra/contract gaps for hourly/gap reliability, stock-finder progression, and RL offline foundation.

**Work currently in-flight (DO NOT duplicate):**
  - [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

**Repo ownership:**
  - **contracts**: JSON Schemas (manifest, bars, L2, gap-opener); JSON-Logic promotion rules; canonical fixtures and checksums
  - **TF**: ML model training and evaluation; feature and label engineering; experiment tracking (W&B)
  - **Trading**: data acquisition and orchestration; IB gateway lifecycle (headless, paper, live); market data pipelines (IBKR, DataBento)

Confirm that your work targets the correct repo and does not overlap with any in-flight task listed above before proceeding.

## Your Repo: Trading
Owns: data acquisition and orchestration, IB gateway lifecycle (headless, paper, live),
  market data pipelines (IBKR, DataBento), signal consumption and order routing, manifest
  consumption under TRADING_SYSTEM_DATA

  Boundaries (do not cross):
    * Stay within Trading/ — do NOT train ML models here
    * Consume model outputs via contracts/ schema interfaces only
    * All data pipeline changes must preserve contracts/ compatibility
    * Do NOT import TF training code directly

## P0 Tasks (highest priority)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P0] [Trading] tf1-l2-depth-delivery-window-20251213: TF1 Level 2 depth delivery window
  - [P0] [Trading] tf1-gap-opener-migration-20251209: TF_1 gap opener migration
  - [P0] [Trading] tf1-l2-depth-investigation-followup: TF_1 L2 depth investigation followup
  - [P0] [Trading] tw-alignment-delivery-20260224: TF_1 alignment 2026-02-19: delivery status and action plan
  - [P0] [Trading] gateway-api-listener-restore-20260227: Restore IB Gateway API listener ports
  - [P0] [Trading] raw-bars-manifest-loop-closure-20260227: Close Ask #1 raw bars confirmation loop
  - [P0] [Trading] production-readiness-staged-path-20260318: Staged production readiness execution

## In-Progress Tasks (across all repos)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P1] [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [P2] [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

## Coordination Warnings
  Overlaps:
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] release-owner-seconds-rc-20260318: both touch: seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: paper_trading, seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] inspect-schema-ml-paths-20260209: both touch: contracts_schema
  - [HIGH] [Trading] release-owner-seconds-rc-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: seconds_model
  - [HIGH] [Trading] tf1-l2-depth-regression-20260118 OVERLAPS [Trading] tf1-l2-depth-delivery-window-20251213: both touch: l2_orderbook
  Drifts:
  - [MEDIUM] [Trading] recapture-l2-shallow-databento-20260122: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] markdownlint-review-20260221: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] tf1-openbid-openask-investigation-20260222: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] backlog-reconciliation-focus-window-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] option-b-default-option-a-rehearsal-plan-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "

## Instructions for Incoming Agent
You are taking over the Trading repo panel from a previous agent session.
Read the above context carefully, then:
  1. Confirm you understand the North Star goal and your repo boundaries.
  2. Review the in-progress tasks — pick up where the previous agent left off.
  3. Check for any coordination warnings and avoid duplicating work.
  4. Begin with a brief status report: what you know, what you plan to do next.
  5. Stay strictly within Trading/ — redirect out-of-scope work to the correct repo.


========================================================================

# Agent Handover Document
Generated: 2026-03-21T13:34:14   Repo: desktop-agent-automation


## North Star Goal
## NORTH STAR — STAY ON GOAL

**Primary goal:** Lead phased execution to reach repeatable seconds-model paper-trading readiness first, then close highest-risk data/infra/contract gaps for hourly/gap reliability, stock-finder progression, and RL offline foundation.

**Work currently in-flight (DO NOT duplicate):**
  - [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

**Repo ownership:**
  - **contracts**: JSON Schemas (manifest, bars, L2, gap-opener); JSON-Logic promotion rules; canonical fixtures and checksums
  - **TF**: ML model training and evaluation; feature and label engineering; experiment tracking (W&B)
  - **Trading**: data acquisition and orchestration; IB gateway lifecycle (headless, paper, live); market data pipelines (IBKR, DataBento)

Confirm that your work targets the correct repo and does not overlap with any in-flight task listed above before proceeding.

## Your Repo: desktop-agent-automation
Automation control plane — orchestrates Copilot agents, panel management, task discovery.

  Boundaries (do not cross):
    * This is the meta-repo — changes here affect all other agents
    * Tests must not mutate TF, Trading, or contracts directly
    * Dry-run flag must default to True in all new tests

## P0 Tasks (highest priority)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P0] [Trading] tf1-l2-depth-delivery-window-20251213: TF1 Level 2 depth delivery window
  - [P0] [Trading] tf1-gap-opener-migration-20251209: TF_1 gap opener migration
  - [P0] [Trading] tf1-l2-depth-investigation-followup: TF_1 L2 depth investigation followup
  - [P0] [Trading] tw-alignment-delivery-20260224: TF_1 alignment 2026-02-19: delivery status and action plan
  - [P0] [Trading] gateway-api-listener-restore-20260227: Restore IB Gateway API listener ports
  - [P0] [Trading] raw-bars-manifest-loop-closure-20260227: Close Ask #1 raw bars confirmation loop
  - [P0] [Trading] production-readiness-staged-path-20260318: Staged production readiness execution

## In-Progress Tasks (across all repos)
  - [P0] [Trading] seconds-paper-prod-readiness-20260318: Drive production-ready seconds paper trading
  - [P0] [Trading] release-owner-seconds-rc-20260318: Drive seconds-model release-owner path
  - [P0] [Trading] tf1-l2-depth-regression-20260118: Fix: L2 depth regression (missing levels)
  - [P0] [Trading] oom-crash-investigation-20260319: Investigate repeated OOM crashes
  - [P1] [Trading] recapture-l2-shallow-databento-20260122: Recapture shallow L2 files via DataBento
  - [P2] [Trading] hourly-bars-databento-fallback-20260123: Hourly bars DataBento fallback

## Coordination Warnings
  Overlaps:
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] release-owner-seconds-rc-20260318: both touch: seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: paper_trading, seconds_model
  - [HIGH] [Trading] seconds-paper-prod-readiness-20260318 OVERLAPS [Trading] inspect-schema-ml-paths-20260209: both touch: contracts_schema
  - [HIGH] [Trading] release-owner-seconds-rc-20260318 OVERLAPS [Trading] production-readiness-staged-path-20260318: both touch: seconds_model
  - [HIGH] [Trading] tf1-l2-depth-regression-20260118 OVERLAPS [Trading] tf1-l2-depth-delivery-window-20251213: both touch: l2_orderbook
  Drifts:
  - [MEDIUM] [Trading] recapture-l2-shallow-databento-20260122: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] markdownlint-review-20260221: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] tf1-openbid-openask-investigation-20260222: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] backlog-reconciliation-focus-window-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "
  - [MEDIUM] [Trading] option-b-default-option-a-rehearsal-plan-20260214: no keywords matching current North Star goal (score=0.00). Verify this task actually advances: "Lead phased execution to reach repeatable seconds-model paper-trading readiness "

## Recent Panel Activity (transcript snippet)
  > Agent Panel Coordination and Management Strategy - desktop-agent-automation - Visual Studio Code Agent Panel Coordinatio

## Instructions for Incoming Agent
You are taking over the desktop-agent-automation repo panel from a previous agent session.
Read the above context carefully, then:
  1. Confirm you understand the North Star goal and your repo boundaries.
  2. Review the in-progress tasks — pick up where the previous agent left off.
  3. Check for any coordination warnings and avoid duplicating work.
  4. Begin with a brief status report: what you know, what you plan to do next.
  5. Stay strictly within desktop-agent-automation/ — redirect out-of-scope work to the correct repo.


========================================================================
