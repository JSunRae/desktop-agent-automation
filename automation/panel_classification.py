"""Panel output classification helpers."""

from __future__ import annotations

from typing import Any, cast

# OpenAI dependency is optional.
openai_module: Any
try:
    import openai as _openai_module
except ImportError:
    _openai_module = cast(Any, None)
openai_module = _openai_module


def classify_panel_output(panel_text: str) -> str:
    """Classify panel output to decide if it's safe to seed new prompts.

    Returns "IDLE_SAFE" on API errors to maintain backward compatibility.
    """
    if not panel_text or not panel_text.strip():
        return "IDLE_SAFE"

    text_to_analyze = panel_text[-1000:].strip()

    if openai_module is None:
        print("[PanelTracker] OpenAI client not available, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"

    import os

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[PanelTracker] OPENAI_API_KEY not set, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"

    try:
        client = openai_module.OpenAI(api_key=api_key)
        system_prompt = """You are an expert at analyzing Copilot chat panel output to determine if it's safe to send new prompts.

Classify the panel output into exactly one of these categories:

IDLE_SAFE: The panel appears to be idle and it's safe to send a new prompt.
ACTIVE_WORKING: The agent is currently working on a task.
COMPLETED: A task has been completed successfully.
AWAITING_USER: The agent is waiting for user input or clarification.

Respond with ONLY the classification category name, no explanation."""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Panel output:\n{text_to_analyze}"},
            ],
            max_tokens=10,
            temperature=0.1,
        )
        message_content = response.choices[0].message.content or ""
        classification = message_content.strip().upper()

        # Lazily record cost if available.
        try:
            from automation.cost_tracker import get_cost_tracker

            cost_tracker = get_cost_tracker()
            if hasattr(response, "usage"):
                cost_tracker.record_text_usage(
                    source="panel_tracker",
                    event="panel_classification",
                    model="gpt-4o-mini",
                    usage=response.usage,
                    details={"classification": classification},
                )
        except Exception:
            pass

        valid_categories = {"IDLE_SAFE", "ACTIVE_WORKING", "COMPLETED", "AWAITING_USER"}
        if classification in valid_categories:
            print(f"[PanelTracker] Classified panel output as: {classification}")
            return classification
        print(f"[PanelTracker] Unexpected classification: {classification}, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"
    except Exception as e:
        print(f"[PanelTracker] Error classifying panel output: {e}, defaulting to IDLE_SAFE")
        return "IDLE_SAFE"


def check_output_for_next_steps(output_text: str) -> bool:
    lower = output_text.lower()
    return "next steps" in lower or "next step" in lower


def check_output_for_task_completed(output_text: str) -> bool:
    lower = output_text.lower()
    return "task completed" in lower


def is_prompt_generator_panel(output_text: str) -> bool:
    lower = output_text.lower()
    return "prompt" in lower or "agent" in lower
