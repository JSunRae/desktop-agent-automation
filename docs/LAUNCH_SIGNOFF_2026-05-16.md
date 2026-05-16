# Launch Sign-Off 2026-05-16

## Release Source

- Launch source of truth: `C:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation-launch-rc`
- Branch: `codex/launch-rc`
- Parent repo release-hardening baseline: `9a4767a` (`Harden launch release validation`)
- Declared submodule pin: `tools/TelegramNotifications` at `2edf97a5ab026c264264505189453bf542286723`

Capture the exact launch head with `git rev-parse HEAD` immediately before push or promotion.

## Verified Local State

- `python master.py --run launch-preflight` now exercises the documented operator path correctly.
- `python -m pytest tests` passes in the release candidate.
- `python scripts/check_submodule_state.py --json` reports the declared submodule clean.
- `contracts/docs` is present under the live trading-system checkout at `\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system\contracts\docs`.
- The current `contracts` repo root is a live Git checkout. Observed remote on 2026-05-16:
  - `git@github.com:JSunRae/ml-contracts.git`

## Remaining External Blockers

1. OpenAI credential readiness is still blocked by project quota or billing.
   - The launch-candidate `.env` contains the current `OPENAI_API_KEY`.
   - The key authenticates, but `python -m automation.master_prompt_orchestrator --check-openai-credentials` returns `429 insufficient_quota`.
   - Launch is blocked until the connected OpenAI project has usable quota or a funded replacement key is installed.
2. The parent repo has no configured Git remote.
   - `git remote -v` is empty in the release candidate.
   - Upstream push, hosted CI verification, and branch protection are blocked until the canonical remote URL is provided and attached.

## Deferred Before Launch

- The original parent worktree at `C:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation` remains frozen on `codex/original-worktree-freeze` and is not part of the release path.
- The original Telegram repo at `C:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation\tools\TelegramNotifications` remains frozen on `codex/original-telegram-freeze`.
- The 4 deferred Telegram changes are:
  - `orchestrator/bridge.py`
  - `scripts/master_cli.py`
  - `tbs_app.py`
  - `tools/agent_runner.py`
- These changes were not promoted into the launch candidate because they primarily affect Windows Python invocation helpers and the preview remote agent-runner path documented in the Telegram repo README.
- The parent repo still starts the Telegram orchestrator directly via `python -m uvicorn tbs_app:app` in `automation/cli/master.py`, so the deferred changes were not treated as launch-critical for this release.

## Release Rehearsal Commands

Run these from the launch-candidate worktree after quota and remote are fixed:

```powershell
python master.py --run launch-preflight
python -m automation.master_prompt_orchestrator --check-openai-credentials
git remote -v
git rev-parse HEAD
```

Launch is ready only when the preflight reports all checks passed and the release branch is pushed to the canonical upstream with green hosted workflows.
