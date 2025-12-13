#!/usr/bin/env bash
# Fallback wrapper so operators can run ./scripts/ml_master.sh when console scripts are missing.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"

exec "${REPO_ROOT}/master" "$@"
