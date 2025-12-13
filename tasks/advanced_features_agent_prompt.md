# Advanced Features Implementation Plan - Dual Agent Prompt

We are implementing the "Advanced Features" from `docs/Todo.md` for the Desktop Agent Automation project. This work is split between two agents to ensure modularity and focus.

## Context
The project automates VS Code Copilot interactions. We currently have a single prompt queue and basic panel tracking. We need to scale this to support multiple repositories simultaneously, track exactly what work is assigned where, understand agent responses better, and track costs.

## Agent 1: Core Architecture & Multi-Repo Support
**Role:** Systems Architect & Core Logic Developer
**Focus:** Data structures, State Management, and Prompt Routing.

### Tasks
1.  **Multi-Repo Support**:
    *   **Goal:** Allow different VS Code windows (different repos) to pull from different prompt batch files.
    *   **Implementation:**
        *   Modify `automation/config.py` to define a mapping (e.g., `REPO_PROMPT_MAP`) linking Repo Names (detected from window titles) to specific prompt file paths.
        *   Update `automation/panel_tracker.py` or `automation/orchestrator.py` to use the window title to look up the correct prompt file instead of using the global `FINISHED_PANEL_PROMPT_PATH`.
        *   Ensure the "Round Robin" queue logic works *per repository* so prompts are distributed correctly within their specific context.

2.  **Agent Assignment Tracking**:
    *   **Goal:** Know exactly which prompt is running in which panel.
    *   **Implementation:**
        *   Enhance the `PanelState` dataclass in `automation/panel_tracker.py`.
        *   Add fields: `assigned_prompt_id` (hash or index), `assigned_prompt_text` (truncated), `repo_name`, and `assignment_time`.
        *   Ensure this data is persisted in `panel_state.json`.

### Deliverables
*   Updated `automation/config.py` with repo mapping configuration.
*   Updated `automation/panel_tracker.py` with enhanced `PanelState` and repo-aware prompt selection logic.
*   Tests verifying that a window titled "ProjectA - VS Code" pulls from `project_a_prompts.txt`.

---

## Agent 2: Intelligence & Metrics
**Role:** Data Analyst & Integration Specialist
**Focus:** Text Analysis, Feedback Loops, and Cost Monitoring.

### Tasks
1.  **Feedback Loop (Response Parsing)**:
    *   **Goal:** Intelligently decide next steps based on what the Copilot Agent says.
    *   **Implementation:**
        *   Create a new module `automation/response_parser.py`.
        *   Implement logic to classify panel output into categories: `COMPLETED`, `ASKING_CLARIFICATION`, `ERROR`, `WORKING`, `SUGGESTING_NEXT_STEPS`.
        *   Integrate this into `automation/panel_tracker.py`'s `update_panel_status` or `get_finished_panels_needing_attention` methods.
        *   *Example:* If agent says "I need the file path", status should be `BLOCKED` or `NEEDS_INPUT` rather than just `IDLE`.

2.  **Cost Tracking**:
    *   **Goal:** Monitor OpenAI API spend for the Auto-Allow Agent (Vision) and Master Orchestrator (Text).
    *   **Implementation:**
        *   Create `automation/cost_tracker.py` to calculate costs based on model usage (e.g., GPT-4o-mini input/output tokens, Vision API per-image costs).
        *   Update `automation/desktop_auto_allow_agent.py` to log the cost of each screenshot analysis.
        *   Update `automation/master_prompt_orchestrator.py` to log the cost of prompt generation.
        *   Save metrics to `logs/cost_metrics.jsonl`.

### Deliverables
*   New `automation/response_parser.py` with unit tests for classification.
*   New `automation/cost_tracker.py` and integration into existing agents.
*   Updated `automation/panel_tracker.py` that uses the parser to make smarter decisions.

---

## Coordination
*   **Agent 1** should start by defining the data structures in `PanelState`.
*   **Agent 2** can work in parallel on `response_parser.py` and `cost_tracker.py` as they are largely independent modules.
*   **Integration Point:** `automation/panel_tracker.py` will eventually use Agent 1's repo logic AND Agent 2's parsing logic.
