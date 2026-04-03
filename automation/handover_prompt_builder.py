"""Handover prompt builder.

Generates a structured handover document / prompt that can be pasted into a
new Copilot chat to give a fresh agent full context about:
  - The North Star goal
  - Which repo it is working in and what its boundaries are
  - What the current panel's agent was doing (transcript summary)
  - What tasks are in-progress across the trading system
  - Any overlaps or drift warnings from the coordination ledger

The handover prompt is printed to stdout and/or saved to a file.

Usage (CLI):
    python scripts/generate_handover.py --repo Trading
    python scripts/generate_handover.py --repo TF --summarise
    python scripts/generate_handover.py --all-repos --out handover.md

OpenAI summarisation (optional, requires OPENAI_API_KEY):
    python scripts/generate_handover.py --repo TF --summarise

Module API:
    from automation.handover_prompt_builder import build_handover_prompt
    text = build_handover_prompt(repo="Trading")
    print(text)
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# ---------------------------------------------------------------------------
# Optional imports (graceful degradation when coordination modules missing)
# ---------------------------------------------------------------------------


def _try_north_star():
    try:
        from automation.north_star import get_north_star
        return get_north_star()
    except Exception:
        return None


def _try_ledger():
    try:
        from automation.repo_task_ledger import get_ledger_report
        return get_ledger_report()
    except Exception:
        return None


def _try_panel_transcript(repo: str) -> str:
    """Attempt to read the most recent visible panel transcript for *repo*."""
    try:
        import uiautomation as auto  # type: ignore

        _VSCODE_KEYWORDS = (" - Visual Studio Code", " - VS Code")

        def _is_vs(w) -> bool:
            try:
                return any(k in (w.Name or "") for k in _VSCODE_KEYWORDS)
            except Exception:
                return False

        def _iter(ctrl, max_depth=60):
            stack = [(ctrl, 0)]
            while stack:
                node, d = stack.pop()
                if d >= max_depth:
                    continue
                yield node
                try:
                    for c in node.GetChildren():
                        stack.append((c, d + 1))
                except Exception:
                    continue

        windows = [w for w in auto.GetRootControl().GetChildren() if _is_vs(w)]
        for win in windows:
            title = ""
            try:
                title = win.Name or ""
            except Exception:
                pass
            if repo.lower() not in title.lower():
                continue
            parts: List[str] = []
            for ctrl in _iter(win):
                try:
                    name = ctrl.Name or ""
                    if len(name) > 30 and not any(s in name for s in ["Ctrl+", "Alt+", "button", "Button"]):
                        parts.append(name[:300])
                    if sum(len(p) for p in parts) > 1200:
                        break
                except Exception:
                    continue
            if parts:
                return "\n".join(parts[:10])
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class HandoverContext:
    """All data collected for a handover prompt."""

    repo: str
    north_star_header: str = ""
    repo_role: str = ""
    repo_boundaries: List[str] = field(default_factory=list)
    in_progress_tasks: List[str] = field(default_factory=list)
    p0_tasks: List[str] = field(default_factory=list)
    overlaps: List[str] = field(default_factory=list)
    drifts: List[str] = field(default_factory=list)
    boundary_violations: List[str] = field(default_factory=list)
    transcript_snippet: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


_REPO_ROLE_MAP = {
    "TF": (
        "ML model development, feature engineering, W&B experiment tracking, model export.",
        [
            "Stay within TF/ — do NOT write trading execution code",
            "Export models to contracts/ schema format only",
            "Use W&B for all experiment logging",
            "Do NOT commit changes to Trading/ or contracts/ directly",
        ],
    ),
    "Trading": (
        "Execution control plane — data acquisition, order routing, paper-trading orchestration.",
        [
            "Stay within Trading/ — do NOT train ML models here",
            "Consume model outputs via contracts/ schema interfaces only",
            "All data pipeline changes must preserve contracts/ compatibility",
            "Do NOT import TF training code directly",
        ],
    ),
    "contracts": (
        "Shared schema definitions — data contracts between TF and Trading.",
        [
            "Schemas only — no model training, no execution logic",
            "Every schema change must be backward-compatible or versioned",
            "Changes here affect BOTH TF and Trading — coordinate carefully",
        ],
    ),
    "desktop-agent-automation": (
        "Automation control plane — orchestrates Copilot agents, panel management, task discovery.",
        [
            "This is the meta-repo — changes here affect all other agents",
            "Tests must not mutate TF, Trading, or contracts directly",
            "Dry-run flag must default to True in all new tests",
        ],
    ),
}


def _build_context(repo: str, include_transcript: bool = True) -> HandoverContext:
    ctx = HandoverContext(repo=repo)

    # North Star
    ns = _try_north_star()
    if ns:
        ctx.north_star_header = ns.prompt_header()
        ctx.p0_tasks = [
            f"[{t.priority}] [{t.repo}] {t.task_id}: {t.title}"
            for t in ns.p0_tasks()
        ]
        ctx.in_progress_tasks = [
            f"[{t.priority}] [{t.repo}] {t.task_id}: {t.title}"
            for t in ns.in_progress_tasks()
        ]
        # Repo role from north star (repo_roles is a Dict[str, RepoRole])
        role_obj = ns.role_for_repo(repo)
        if role_obj is not None:
            ctx.repo_role = f"Owns: {', '.join(role_obj.owns)}"
            ctx.repo_boundaries = [f"Must NOT do: {item}" for item in role_obj.must_not_do]

    # Fallback / boundary info from static map
    if not ctx.repo_role and repo in _REPO_ROLE_MAP:
        ctx.repo_role, ctx.repo_boundaries = _REPO_ROLE_MAP[repo]
    elif repo in _REPO_ROLE_MAP:
        _, ctx.repo_boundaries = _REPO_ROLE_MAP[repo]

    # Ledger
    ledger = _try_ledger()
    if ledger:
        ctx.overlaps = [
            f"  [{o.severity.upper()}] [{o.task_a.repo}] {o.task_a.task_id} OVERLAPS "
            f"[{o.task_b.repo}] {o.task_b.task_id}: {o.reason}"
            for o in ledger.overlap_warnings[:5]
        ]
        ctx.drifts = [
            f"  [{d.severity.upper()}] [{d.task.repo}] {d.task.task_id}: {d.reason}"
            for d in ledger.drift_warnings[:5]
        ]
        ctx.boundary_violations = [
            f"  [{v.severity.upper()}] [{v.task.repo}] {v.task.task_id}: {v.rule_broken}"
            for v in ledger.boundary_violations[:5]
        ]

    # Transcript
    if include_transcript:
        ctx.transcript_snippet = _try_panel_transcript(repo)

    return ctx


# ---------------------------------------------------------------------------
# Prompt renderer
# ---------------------------------------------------------------------------


def _render_handover(ctx: HandoverContext, summarise: bool = False) -> str:
    lines: List[str] = []

    def h(title: str) -> None:
        lines.append(f"\n## {title}")

    def li(items: List[str], empty_msg: str = "(none)") -> None:
        if items:
            for item in items:
                lines.append(f"  - {item.strip()}")
        else:
            lines.append(f"  {empty_msg}")

    def para(text: str) -> None:
        if text:
            lines.append(textwrap.fill(text.strip(), width=90, subsequent_indent="  "))

    lines.append("# Agent Handover Document")
    lines.append(f"Generated: {ctx.generated_at}   Repo: {ctx.repo}")
    lines.append("")

    # --- North Star ---
    if ctx.north_star_header:
        h("North Star Goal")
        for line in ctx.north_star_header.strip().splitlines():
            lines.append(line)
    else:
        h("North Star Goal")
        lines.append("  (North Star not loaded — run `python scripts/coord_cli.py north-star`)")

    # --- Repo context ---
    h(f"Your Repo: {ctx.repo}")
    if ctx.repo_role:
        para(ctx.repo_role)
    if ctx.repo_boundaries:
        lines.append("\n  Boundaries (do not cross):")
        for b in ctx.repo_boundaries:
            lines.append(f"    * {b}")

    # --- Active P0 tasks ---
    h("P0 Tasks (highest priority)")
    li(ctx.p0_tasks, "(no P0 tasks found)")

    # --- In-progress ---
    h("In-Progress Tasks (across all repos)")
    li(ctx.in_progress_tasks, "(none found)")

    # --- Coordination issues ---
    if ctx.overlaps or ctx.drifts or ctx.boundary_violations:
        h("Coordination Warnings")
        if ctx.overlaps:
            lines.append("  Overlaps:")
            li(ctx.overlaps)
        if ctx.drifts:
            lines.append("  Drifts:")
            li(ctx.drifts)
        if ctx.boundary_violations:
            lines.append("  Boundary violations:")
            li(ctx.boundary_violations)

    # --- Transcript ---
    if ctx.transcript_snippet:
        h("Recent Panel Activity (transcript snippet)")
        snippet = textwrap.shorten(ctx.transcript_snippet, width=800, placeholder="...")
        for chunk in snippet.split(" | ")[:6]:
            if chunk.strip():
                lines.append(f"  > {chunk.strip()[:120]}")

    # --- OpenAI summarisation ---
    if summarise and ctx.transcript_snippet:
        summary = _openai_summarise(ctx.transcript_snippet, ctx.repo)
        if summary:
            h("AI Summary of Panel Activity")
            lines.append(summary)

    # --- Continuation instruction ---
    h("Instructions for Incoming Agent")
    lines.append(textwrap.dedent(f"""\
  You are taking over the {ctx.repo} repo panel from a previous agent session.
  Read the above context carefully, then:
    1. Confirm you understand the North Star goal and your repo boundaries.
    2. Review the in-progress tasks — pick up where the previous agent left off.
    3. Check for any coordination warnings and avoid duplicating work.
    4. Begin with a brief status report: what you know, what you plan to do next.
    5. Stay strictly within {ctx.repo}/ — redirect out-of-scope work to the correct repo.
    """))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optional OpenAI summarisation
# ---------------------------------------------------------------------------


def _openai_summarise(transcript: str, repo: str) -> str:
    """Use OpenAI to produce a 2-3 sentence summary (returns '' if unavailable)."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    try:
        import openai  # type: ignore

        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a technical summariser for the {repo} repo in a "
                        "trading system project. Write 2-3 concise sentences summarising "
                        "what the agent was working on, suitable for a handover document."
                    ),
                },
                {"role": "user", "content": f"Panel transcript:\n{transcript[:1200]}"},
            ],
            max_tokens=180,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        return f"  (OpenAI summarisation failed: {exc})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_handover_prompt(
    repo: str,
    *,
    include_transcript: bool = True,
    summarise: bool = False,
) -> str:
    """Return a handover prompt string for the given repo.

    Parameters
    ----------
    repo:
        The repo name, e.g. "TF", "Trading", "contracts", "desktop-agent-automation".
    include_transcript:
        If True, attempts to read the live panel transcript via uiautomation.
    summarise:
        If True and OPENAI_API_KEY is set, calls OpenAI to summarise transcript.

    Returns
    -------
    str
        The formatted handover prompt ready to paste into a new Copilot chat.
    """
    ctx = _build_context(repo, include_transcript=include_transcript)
    return _render_handover(ctx, summarise=summarise)


def build_all_handover_prompts(
    repos: Optional[List[str]] = None,
    *,
    include_transcript: bool = True,
    summarise: bool = False,
) -> str:
    """Build handover prompts for multiple repos and concatenate."""
    if repos is None:
        repos = ["contracts", "TF", "Trading", "desktop-agent-automation"]
    sections: List[str] = []
    for repo in repos:
        sections.append(build_handover_prompt(repo, include_transcript=include_transcript, summarise=summarise))
        sections.append("\n" + "=" * 72 + "\n")
    return "\n".join(sections)
