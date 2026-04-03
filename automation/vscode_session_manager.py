"""Capture and restore VS Code repos per virtual desktop."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from automation.desktop import switch_to_desktop
from automation.title_parsing import extract_repo_name_from_vscode_window_title
from automation.ui.vscode_windows import find_all_vscode_windows

_DEFAULT_STATE_PATH = Path("state") / "vscode_desktop_sessions.json"
_DEFAULT_MAX_SNAPSHOTS = 120
_DEFAULT_OPEN_DELAY_SECONDS = 0.55
_WORKSPACE_SUFFIX_RE = re.compile(r"\s*\(workspace\)\s*$", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_state_path(raw_path: str | None) -> Path:
    if not raw_path:
        return (_repo_root() / _DEFAULT_STATE_PATH).resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = _repo_root() / candidate
    return candidate.resolve()


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": _utc_iso_now(), "snapshots": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated_at": _utc_iso_now(), "snapshots": []}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": _utc_iso_now(), "snapshots": []}
    snapshots = data.get("snapshots")
    if not isinstance(snapshots, list):
        data["snapshots"] = []
    data.setdefault("version", 1)
    data.setdefault("updated_at", _utc_iso_now())
    return data


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _current_desktop_name() -> Optional[str]:
    try:
        import pyvda

        current = pyvda.VirtualDesktop.current()
        name = (current.name or "").strip() if current else ""
        return name or None
    except Exception:
        return None


def _list_virtual_desktops() -> List[Tuple[str, int]]:
    try:
        import pyvda

        desktops = pyvda.get_virtual_desktops()
    except Exception:
        current = _current_desktop_name() or "current"
        return [(current, 1)]

    result: List[Tuple[str, int]] = []
    for idx, desktop in enumerate(desktops, start=1):
        name = (desktop.name or "").strip() if desktop else ""
        result.append((name or f"Desktop {idx}", idx))
    return result or [(_current_desktop_name() or "current", 1)]


def _normalize_path_string(raw_path: str) -> Optional[str]:
    value = (raw_path or "").strip().strip('"').strip("'")
    if not value:
        return None

    if value.startswith("file://"):
        value = value[7:]
        if value.startswith("/") and len(value) >= 3 and value[2] == ":":
            value = value[1:]
        value = value.replace("%20", " ")

    value = value.replace("/", "\\")
    value = value.rstrip("\\")
    if re.match(r"^[A-Za-z]:\\", value):
        return value
    if value.startswith("\\\\"):
        return value
    return None


def _canonical_repo_name(repo_name: str) -> str:
    value = (repo_name or "").strip()
    if not value:
        return ""
    return _WORKSPACE_SUFFIX_RE.sub("", value).strip()


def _repo_lookup_keys(repo_name: str) -> List[str]:
    keys: List[str] = []
    raw = (repo_name or "").strip().lower()
    canonical = _canonical_repo_name(repo_name).lower()
    if raw:
        keys.append(raw)
    if canonical and canonical not in keys:
        keys.append(canonical)
    return keys


def _known_repo_path_candidates(repo_name: str) -> List[Path]:
    canonical = _canonical_repo_name(repo_name).lower()
    if not canonical:
        return []

    trading_system_root = Path(
        os.environ.get(
            "TRADING_SYSTEM_ROOT_WIN",
            r"\\wsl.localhost\Ubuntu-24.04\home\jrae\wsl_projects\trading-system",
        )
    )

    candidates_by_key: Dict[str, List[Path]] = {
        "desktop-agent-automation": [_repo_root()],
        "trading-system": [trading_system_root],
        "trading": [Path(os.environ.get("TRADING_REPO_ROOT", str(trading_system_root / "Trading")))],
        "tf": [Path(os.environ.get("TF_REPO_ROOT", str(trading_system_root / "TF")))],
        "contracts": [Path(os.environ.get("CONTRACTS_REPO_ROOT", str(trading_system_root / "contracts")))],
    }
    return candidates_by_key.get(canonical, [])


def _extract_windows_paths_from_obj(value: Any, found: Set[str]) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _extract_windows_paths_from_obj(nested, found)
        return
    if isinstance(value, list):
        for nested in value:
            _extract_windows_paths_from_obj(nested, found)
        return
    if not isinstance(value, str):
        return

    normalized = _normalize_path_string(value)
    if normalized:
        found.add(normalized)

    for match in re.findall(r"[A-Za-z]:\\[^\n\r\t\"']+", value):
        normalized_match = _normalize_path_string(match)
        if normalized_match:
            found.add(normalized_match)


def _load_recent_vscode_paths() -> Set[str]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return set()
    storage_path = Path(appdata) / "Code" / "User" / "globalStorage" / "storage.json"
    if not storage_path.exists():
        return set()

    try:
        raw = json.loads(storage_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    found: Set[str] = set()
    _extract_windows_paths_from_obj(raw, found)

    existing: Set[str] = set()
    for item in found:
        try:
            candidate = Path(item)
            if candidate.exists() and candidate.is_dir():
                existing.add(str(candidate.resolve()))
        except Exception:
            continue
    return existing


def _build_repo_path_index(state: dict[str, Any]) -> Dict[str, List[str]]:
    by_repo: Dict[str, Set[str]] = {}

    def _index_path(repo_name: str, path: str) -> None:
        normalized_path = (path or "").strip()
        if not normalized_path:
            return
        for key in _repo_lookup_keys(repo_name):
            by_repo.setdefault(key, set()).add(normalized_path)

    snapshots = state.get("snapshots") if isinstance(state, dict) else None
    if isinstance(snapshots, list):
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            for desktop in snapshot.get("desktops", []):
                if not isinstance(desktop, dict):
                    continue
                for repo in desktop.get("repos", []):
                    if not isinstance(repo, dict):
                        continue
                    repo_name = (repo.get("repo_name") or "").strip()
                    path = (repo.get("path") or "").strip()
                    if not repo_name or not path:
                        continue
                    _index_path(repo_name, path)

    for path in _load_recent_vscode_paths():
        repo_name = Path(path).name.strip().lower()
        if not repo_name:
            continue
        _index_path(repo_name, path)

    return {key: sorted(values, key=len) for key, values in by_repo.items()}


def _resolve_repo_path(repo_name: str, repo_path_index: Dict[str, List[str]]) -> Optional[str]:
    combined_candidates: List[str] = []
    seen: Set[str] = set()
    for key in _repo_lookup_keys(repo_name):
        for candidate in repo_path_index.get(key, []):
            if candidate not in seen:
                combined_candidates.append(candidate)
                seen.add(candidate)

    for path_candidate in _known_repo_path_candidates(repo_name):
        candidate = str(path_candidate)
        if candidate not in seen:
            combined_candidates.append(candidate)
            seen.add(candidate)

    if not combined_candidates:
        return None

    for candidate in combined_candidates:
        try:
            candidate_path = Path(candidate)
            if candidate_path.exists() and candidate_path.is_dir():
                return str(candidate_path.resolve())
        except Exception:
            continue
    return combined_candidates[0]


def capture_snapshot(state_path: Path, max_snapshots: int) -> int:
    state = _load_state(state_path)
    repo_path_index = _build_repo_path_index(state)

    desktops = _list_virtual_desktops()
    original_desktop = _current_desktop_name()
    captured_desktops: List[dict[str, Any]] = []

    print(f"[session] Capturing VS Code repos across {len(desktops)} desktop(s)...")
    for desktop_name, desktop_index in desktops:
        try:
            switch_to_desktop(desktop_name)
            time.sleep(0.5)
        except Exception as exc:
            print(f"[session] Warning: could not switch to '{desktop_name}': {exc}")

        repos_by_name: Dict[str, dict[str, Any]] = {}
        for window in find_all_vscode_windows(timeout=0.4):
            title = (getattr(window, "Name", None) or "").strip()
            if not title:
                continue
            repo_name = extract_repo_name_from_vscode_window_title(title)
            if not repo_name:
                continue

            entry = repos_by_name.setdefault(
                repo_name,
                {
                    "repo_name": repo_name,
                    "path": _resolve_repo_path(repo_name, repo_path_index),
                    "window_count": 0,
                    "titles": [],
                },
            )
            entry["window_count"] = int(entry["window_count"]) + 1
            titles = entry["titles"]
            if title not in titles and len(titles) < 3:
                titles.append(title)

        repo_list = sorted(repos_by_name.values(), key=lambda item: str(item.get("repo_name", "")).lower())
        captured_desktops.append(
            {
                "desktop_name": desktop_name,
                "desktop_index": desktop_index,
                "repos": repo_list,
            }
        )
        print(f"[session] {desktop_name}: {len(repo_list)} repo(s)")

    if original_desktop:
        try:
            switch_to_desktop(original_desktop)
        except Exception:
            pass

    snapshot = {
        "captured_at": _utc_iso_now(),
        "machine": os.environ.get("COMPUTERNAME", "unknown"),
        "desktops": captured_desktops,
    }

    snapshots = state.get("snapshots", [])
    if not isinstance(snapshots, list):
        snapshots = []
    snapshots.append(snapshot)
    if max_snapshots > 0 and len(snapshots) > max_snapshots:
        snapshots = snapshots[-max_snapshots:]
    state["snapshots"] = snapshots
    state["updated_at"] = _utc_iso_now()
    _save_state(state_path, state)

    total_repos = sum(len(d.get("repos", [])) for d in captured_desktops)
    print(f"[session] Capture saved to {state_path}")
    print(f"[session] Snapshot includes {total_repos} repo entries across {len(captured_desktops)} desktop(s)")
    return 0


def _history_repo_catalog(state: dict[str, Any]) -> Dict[str, dict[str, Any]]:
    catalog: Dict[str, dict[str, Any]] = {}
    snapshots = state.get("snapshots")
    if not isinstance(snapshots, list):
        return catalog

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        captured_at = snapshot.get("captured_at") or ""
        for desktop in snapshot.get("desktops", []):
            if not isinstance(desktop, dict):
                continue
            desktop_name = (desktop.get("desktop_name") or "").strip() or "current"
            for repo in desktop.get("repos", []):
                if not isinstance(repo, dict):
                    continue
                repo_name = (repo.get("repo_name") or "").strip()
                if not repo_name:
                    continue
                key = repo_name.lower()
                slot = catalog.setdefault(
                    key,
                    {
                        "repo_name": repo_name,
                        "count": 0,
                        "path": None,
                        "last_seen": "",
                        "last_desktop": "current",
                    },
                )
                slot["count"] = int(slot["count"]) + 1
                path = (repo.get("path") or "").strip()
                if path:
                    slot["path"] = path
                if captured_at and str(slot["last_seen"]) <= captured_at:
                    slot["last_seen"] = captured_at
                    slot["last_desktop"] = desktop_name
    return catalog


def _parse_repo_selection(raw: str, max_index: int) -> Optional[Set[int]]:
    value = (raw or "").strip().lower()
    if not value or value == "latest":
        return None
    if value == "all":
        return set(range(1, max_index + 1))

    selected: Set[int] = set()
    for chunk in value.split(","):
        token = chunk.strip()
        if not token:
            continue
        if not token.isdigit():
            continue
        index = int(token)
        if 1 <= index <= max_index:
            selected.add(index)
    return selected if selected else None


def _parse_desktop_selection(raw: str, available_indexes: Set[int]) -> Optional[Set[int]]:
    value = (raw or "").strip().lower()
    if not value:
        return None

    selected: Set[int] = set()
    for chunk in value.split(","):
        token = chunk.strip()
        if not token:
            continue
        if token.startswith("d"):
            token = token[1:]
        if not token.isdigit():
            return None
        idx = int(token)
        if idx in available_indexes:
            selected.add(idx)
    return selected if selected else None


def _choose_repos_for_startup(latest_snapshot: dict[str, Any], catalog: Dict[str, dict[str, Any]]) -> Set[str]:
    latest_repo_names: Set[str] = set()
    for desktop in latest_snapshot.get("desktops", []):
        for repo in desktop.get("repos", []):
            repo_name = (repo.get("repo_name") or "").strip()
            if repo_name:
                latest_repo_names.add(repo_name.lower())

    rows = sorted(catalog.values(), key=lambda item: (-int(item.get("count", 0)), str(item.get("repo_name", "")).lower()))
    if not rows:
        return latest_repo_names

    desktop_rows: List[Tuple[int, str, int]] = []
    for desktop in latest_snapshot.get("desktops", []):
        if not isinstance(desktop, dict):
            continue
        desktop_index = int(desktop.get("desktop_index") or 0)
        desktop_name = (desktop.get("desktop_name") or "").strip() or f"Desktop {desktop_index or '?'}"
        repos = desktop.get("repos") if isinstance(desktop.get("repos"), list) else []
        if desktop_index > 0 and repos:
            desktop_rows.append((desktop_index, desktop_name, len(repos)))

    if desktop_rows:
        print("[session] Latest snapshot desktops (enter desktop numbers, e.g. 4,6):")
        for desktop_index, desktop_name, repo_count in sorted(desktop_rows, key=lambda item: item[0]):
            print(f"  {desktop_index:>2}. {desktop_name} | repos={repo_count}")
        print("[session] Tip: prefix with 'r:' to select by repo list indexes instead (e.g. r:4,6).")

    print("[session] Historical VS Code repos:")
    for idx, row in enumerate(rows, start=1):
        marker = "*" if str(row.get("repo_name", "")).lower() in latest_repo_names else " "
        path = row.get("path") or "(path unknown)"
        print(
            f"  {idx:>2}. [{marker}] {row['repo_name']} | seen={row['count']} | last_desktop={row['last_desktop']} | {path}"
        )
    print("[session] Enter desktop numbers, 'all', 'r:<indexes>', or press Enter for latest snapshot set.")

    try:
        raw = input("Select repos to open: ")
    except (KeyboardInterrupt, EOFError):
        print("\n[session] Cancelled")
        return set()

    normalized_raw = (raw or "").strip()
    if not normalized_raw:
        return latest_repo_names

    if normalized_raw.lower() == "all":
        return latest_repo_names

    desktop_indexes = {idx for idx, _, _ in desktop_rows}
    if normalized_raw.lower().startswith("r:"):
        repo_selection_raw = normalized_raw[2:]
    else:
        repo_selection_raw = normalized_raw
        desktop_selection = _parse_desktop_selection(normalized_raw, desktop_indexes)
        if desktop_selection:
            selected_repo_keys: Set[str] = set()
            for desktop in latest_snapshot.get("desktops", []):
                if not isinstance(desktop, dict):
                    continue
                desktop_index = int(desktop.get("desktop_index") or 0)
                if desktop_index not in desktop_selection:
                    continue
                for repo in desktop.get("repos", []):
                    if not isinstance(repo, dict):
                        continue
                    repo_name = (repo.get("repo_name") or "").strip()
                    if repo_name:
                        selected_repo_keys.add(repo_name.lower())
            return selected_repo_keys

    selected_indexes = _parse_repo_selection(repo_selection_raw, len(rows))
    if selected_indexes is None:
        return latest_repo_names

    result: Set[str] = set()
    for idx in selected_indexes:
        result.add(str(rows[idx - 1]["repo_name"]).lower())
    return result


def _find_code_cli() -> Optional[str]:
    env_override = os.environ.get("VSCODE_CLI")
    if env_override:
        return env_override
    for command in ("code.cmd", "code", "codium.cmd", "codium"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def _launch_vscode_repo(code_cli: str, repo_path: str, dry_run: bool) -> bool:
    path = Path(repo_path)
    if not path.exists() or not path.is_dir():
        print(f"[session] Skip missing path: {repo_path}")
        return False

    command = [code_cli, "-n", str(path)]
    if dry_run:
        print(f"[dry-run] {' '.join(command)}")
        return True

    try:
        subprocess.Popen(command, cwd=str(path))
        return True
    except Exception as exc:
        print(f"[session] Failed to open {repo_path}: {exc}")
        return False


def _build_restore_plan(
    latest_snapshot: dict[str, Any],
    selected_repo_keys: Set[str],
    catalog: Dict[str, dict[str, Any]],
    repo_path_index: Dict[str, List[str]],
) -> List[Tuple[str, List[Tuple[str, str]]]]:
    planned: Dict[str, List[Tuple[str, str]]] = {}
    desktop_order: List[str] = []
    seen_repos: Set[str] = set()

    for desktop in latest_snapshot.get("desktops", []):
        if not isinstance(desktop, dict):
            continue
        desktop_name = (desktop.get("desktop_name") or "").strip() or "current"
        if desktop_name not in planned:
            planned[desktop_name] = []
            desktop_order.append(desktop_name)

        for repo in desktop.get("repos", []):
            if not isinstance(repo, dict):
                continue
            repo_name = (repo.get("repo_name") or "").strip()
            if not repo_name:
                continue
            key = repo_name.lower()
            if key not in selected_repo_keys:
                continue
            path = (repo.get("path") or "").strip() or str(catalog.get(key, {}).get("path") or "").strip()
            if not path:
                path = _resolve_repo_path(repo_name, repo_path_index) or ""
            if not path:
                continue
            planned[desktop_name].append((repo_name, path))
            seen_repos.add(key)

    for key in selected_repo_keys:
        if key in seen_repos:
            continue
        row = catalog.get(key)
        if not row:
            continue
        path = str(row.get("path") or "").strip() or (_resolve_repo_path(str(row.get("repo_name") or key), repo_path_index) or "")
        if not path:
            continue
        desktop_name = str(row.get("last_desktop") or "current").strip() or "current"
        if desktop_name not in planned:
            planned[desktop_name] = []
            desktop_order.append(desktop_name)
        planned[desktop_name].append((str(row.get("repo_name") or key), path))

    return [(desktop, planned[desktop]) for desktop in desktop_order if planned.get(desktop)]


def restore_snapshot(
    state_path: Path,
    startup_mode: bool,
    dry_run: bool,
    delay_seconds: float,
    repos_csv: str | None,
) -> int:
    state = _load_state(state_path)
    snapshots = state.get("snapshots") if isinstance(state, dict) else None
    if not isinstance(snapshots, list) or not snapshots:
        print(f"[session] No snapshot history found at {state_path}")
        return 1

    latest_snapshot = snapshots[-1]
    if not isinstance(latest_snapshot, dict):
        print("[session] Invalid latest snapshot format")
        return 1

    catalog = _history_repo_catalog(state)
    repo_path_index = _build_repo_path_index(state)
    latest_repo_keys: Set[str] = set()
    for desktop in latest_snapshot.get("desktops", []):
        for repo in desktop.get("repos", []):
            repo_name = (repo.get("repo_name") or "").strip()
            if repo_name:
                latest_repo_keys.add(repo_name.lower())

    if repos_csv:
        selected_repo_keys = {part.strip().lower() for part in repos_csv.split(",") if part.strip()}
    elif startup_mode:
        selected_repo_keys = _choose_repos_for_startup(latest_snapshot, catalog)
    else:
        selected_repo_keys = latest_repo_keys

    if not selected_repo_keys:
        print("[session] Nothing selected to open")
        return 0

    restore_plan = _build_restore_plan(latest_snapshot, selected_repo_keys, catalog, repo_path_index)
    if not restore_plan:
        print("[session] No restorable repo paths found for selected repos")
        return 1

    code_cli = _find_code_cli()
    if not code_cli:
        print("[session] Could not find VS Code CLI ('code'). Set VSCODE_CLI to override.")
        return 1

    open_count = 0
    switched_desktops = 0

    for desktop_name, repos in restore_plan:
        try:
            switch_to_desktop(desktop_name)
            switched_desktops += 1
            time.sleep(max(0.2, delay_seconds))
        except Exception as exc:
            print(f"[session] Warning: could not switch to '{desktop_name}': {exc}")

        print(f"[session] Opening {len(repos)} repo(s) on desktop '{desktop_name}'")
        for repo_name, repo_path in repos:
            if _launch_vscode_repo(code_cli, repo_path, dry_run=dry_run):
                open_count += 1
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    print(f"[session] Completed restore. Opened {open_count} repo(s) across {switched_desktops} desktop switch(es)")
    return 0


def install_startup_runner() -> int:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        print("[session] APPDATA not set; cannot install startup runner")
        return 1

    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    startup_cmd = startup_dir / "desktop-agent-vscode-restore.cmd"

    root = _repo_root()
    script = f"""@echo off
cd /d "{root}"
if exist ".venv\\Scripts\\python.exe" (
  ".venv\\Scripts\\python.exe" -m automation.vscode_session_manager restore --startup
) else (
  python -m automation.vscode_session_manager restore --startup
)
"""

    startup_cmd.write_text(script, encoding="utf-8")
    print(f"[session] Startup runner installed at {startup_cmd}")
    print("[session] It will prompt which historical VS Code repos to reopen after login.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m automation.vscode_session_manager",
        description="Capture and restore VS Code repos per virtual desktop.",
    )
    parser.add_argument(
        "--state-file",
        default=str(_DEFAULT_STATE_PATH),
        help="Path to session state JSON (default: state/vscode_desktop_sessions.json)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="Capture currently open VS Code repos by desktop")
    capture.add_argument("--max-snapshots", type=int, default=_DEFAULT_MAX_SNAPSHOTS)

    restore = subparsers.add_parser("restore", help="Restore VS Code repos from captured history")
    restore.add_argument("--startup", action="store_true", help="Prompt selection from historical repos")
    restore.add_argument("--repos", help="Comma-separated repo names to open")
    restore.add_argument("--dry-run", action="store_true", help="Print commands without opening windows")
    restore.add_argument("--delay", type=float, default=_DEFAULT_OPEN_DELAY_SECONDS)

    subparsers.add_parser("install-startup", help="Install startup .cmd to run restore --startup at login")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    state_path = _resolve_state_path(getattr(args, "state_file", None))

    if args.command == "capture":
        max_snapshots = max(1, int(getattr(args, "max_snapshots", _DEFAULT_MAX_SNAPSHOTS)))
        return capture_snapshot(state_path=state_path, max_snapshots=max_snapshots)
    if args.command == "restore":
        return restore_snapshot(
            state_path=state_path,
            startup_mode=bool(getattr(args, "startup", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            delay_seconds=max(0.0, float(getattr(args, "delay", _DEFAULT_OPEN_DELAY_SECONDS))),
            repos_csv=getattr(args, "repos", None),
        )
    if args.command == "install-startup":
        return install_startup_runner()

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())