# Validation Report — master Launcher Parity (2025-12-09)

## Scope
Bring the desktop-agent-automation repository in line with the TF_1 launcher experience by vendoring the `master` script, wiring a Windows shim, exposing a fallback (`scripts/ml_master.sh`), and registering the console entry point via `pyproject.toml`.

## Evidence Summary
- `source .venv/bin/activate && export PATH="$PWD:$PATH" && master --describe` (WSL) prints the packaged JSON descriptor (see `logs/validation_master_launcher_2025-12-09.txt`).
- `TF1_LIST_TOOLS=1 ./scripts/ml_master.sh` lists workflows and gracefully exits when fed `q` via stdin.
- Windows shim `.venv\Scripts\master.exe --help` shows argparse metadata and matches README usage instructions.
- Full command transcripts are stored in `logs/validation_master_launcher_2025-12-09.txt` for auditing.

## Follow-ups / Next Steps
- Ensure operators add `master` (or `master.cmd`) to their PATHs per README instructions.
- If `master` resolves to a different repo on shared hosts, export `PATH="$PWD:$PATH"` or symlink the fallback script as documented.
