"""Diagnose VS Code workspace storage and cache bloat.

Scans VS Code storage/cache roots, maps workspace hashes back to repo
paths where possible, and reports top offenders with severity levels.

Usage (standalone):
    python -m automation.diagnose_storage
    python -m automation.diagnose_storage --top 20 --deep --json

Wired into the master CLI as ``diagnose-storage``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IS_WINDOWS = platform.system() == "Windows"

# VS Code stores workspace data under these roots (Windows paths; Linux/macOS
# equivalents are added dynamically).
_APPDATA = Path(os.environ.get("APPDATA", "")) if _IS_WINDOWS else Path.home() / ".config"
_LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", "")) if _IS_WINDOWS else Path.home() / ".cache"

VSCODE_STORAGE_ROOTS: list[Path] = [
    _APPDATA / "Code" / "User" / "workspaceStorage",
    _APPDATA / "Code" / "User" / "globalStorage",
    _LOCAL_APPDATA / "Code" / "Cache",
    _LOCAL_APPDATA / "Code" / "CachedData",
    _LOCAL_APPDATA / "Code" / "CachedExtensions",
    _LOCAL_APPDATA / "Code" / "CachedExtensionVSIXs",
    _LOCAL_APPDATA / "Code" / "logs",
    _LOCAL_APPDATA / "Code" / "CrashpadMetrics-active.pma",
]

APPROVED_STORAGE_ROOTS: set[Path] = set()  # populated at init

SEVERITY_THRESHOLDS_MB = {"ok": 100, "warn": 500}  # <100 ok, 100-500 warn, >500 critical


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SubfolderInfo:
    """Size breakdown for a subfolder within a workspace entry."""
    name: str
    size_bytes: int
    file_count: int
    last_modified: Optional[str] = None


@dataclass
class WorkspaceEntry:
    """Diagnosis result for a single workspace storage folder."""
    folder_name: str
    folder_path: str
    size_bytes: int
    file_count: int
    last_modified: Optional[str] = None
    repo_path: Optional[str] = None
    repo_name: Optional[str] = None
    severity: str = "ok"
    heavy_subfolders: list[SubfolderInfo] = field(default_factory=list)
    root_category: str = "workspaceStorage"


@dataclass
class ProcessDiagnostic:
    """Optional running-process diagnostic."""
    pid: int
    name: str
    memory_mb: float
    cpu_percent: float


@dataclass
class CrashInfo:
    """Optional crash-report diagnostic."""
    file_path: str
    size_bytes: int
    modified: str


@dataclass
class DiagnosisReport:
    """Full diagnosis report."""
    timestamp: str
    hostname: str
    roots_scanned: list[str]
    total_size_bytes: int
    workspace_count: int
    entries: list[WorkspaceEntry]
    repos_flagged: int = 0
    severity_counts: Dict[str, int] = field(default_factory=dict)
    process_diagnostics: list[ProcessDiagnostic] = field(default_factory=list)
    crash_reports: list[CrashInfo] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> Tuple[int, int, Optional[datetime]]:
    """Return (total_bytes, file_count, newest_mtime) for *path* recursively."""
    total = 0
    count = 0
    newest: Optional[datetime] = None
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    stat = entry.stat()
                    total += stat.st_size
                    count += 1
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    if newest is None or mtime > newest:
                        newest = mtime
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total, count, newest


def _resolve_repo_from_workspace_json(ws_dir: Path) -> Optional[str]:
    """Try to read workspace.json inside a workspaceStorage entry."""
    ws_json = ws_dir / "workspace.json"
    if not ws_json.is_file():
        return None
    try:
        data = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
        folder = data.get("folder")
        if folder:
            # URI like file:///c%3A/Users/Pilot/... -> path
            if folder.startswith("file:///"):
                folder = folder[len("file:///"):]
                folder = folder.replace("%3A", ":").replace("%20", " ")
            return folder
        configuration = data.get("configuration")
        if configuration and isinstance(configuration, dict):
            return configuration.get("path")
    except Exception:
        pass
    return None


def _resolve_repo_from_state_db(ws_dir: Path) -> Optional[str]:
    """Try reading the state.vscdb SQLite database for workspace folder info."""
    db_path = ws_dir / "state.vscdb"
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        cursor = conn.execute(
            "SELECT value FROM ItemTable WHERE key = 'workspaceIdentifier' LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            data = json.loads(row[0])
            return data.get("configPath") or data.get("id")
    except Exception:
        pass
    return None


def _repo_name_from_path(repo_path: Optional[str]) -> Optional[str]:
    if not repo_path:
        return None
    return Path(repo_path.rstrip("/\\")).name or None


def _severity(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb >= SEVERITY_THRESHOLDS_MB["warn"]:
        return "critical"
    if mb >= SEVERITY_THRESHOLDS_MB["ok"]:
        return "warn"
    return "ok"


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / (1024**2):.1f} MB"
    return f"{n / (1024**3):.2f} GB"


def _heavy_subfolders(ws_dir: Path, top_n: int = 5) -> list[SubfolderInfo]:
    """Return the top-N heaviest immediate children of *ws_dir*."""
    subs: list[SubfolderInfo] = []
    try:
        for child in ws_dir.iterdir():
            if child.is_dir():
                sz, fc, newest = _dir_size(child)
                subs.append(SubfolderInfo(
                    name=child.name,
                    size_bytes=sz,
                    file_count=fc,
                    last_modified=newest.isoformat() if newest else None,
                ))
    except (OSError, PermissionError):
        pass
    subs.sort(key=lambda s: s.size_bytes, reverse=True)
    return subs[:top_n]


# ---------------------------------------------------------------------------
# Optional diagnostics: processes + crash reports
# ---------------------------------------------------------------------------

def _process_diagnostics() -> list[ProcessDiagnostic]:
    """Return VS Code-related processes with memory/cpu info."""
    results: list[ProcessDiagnostic] = []
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return results
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            name = proc.info["name"] or ""
            if "code" not in name.lower():
                continue
            mem = proc.info.get("memory_info")
            results.append(ProcessDiagnostic(
                pid=proc.info["pid"],
                name=name,
                memory_mb=(mem.rss / (1024 ** 2)) if mem else 0.0,
                cpu_percent=proc.info.get("cpu_percent") or 0.0,
            ))
        except Exception:
            pass
    results.sort(key=lambda p: p.memory_mb, reverse=True)
    return results


def _crash_reports() -> list[CrashInfo]:
    """List crash-related files in VS Code storage."""
    results: list[CrashInfo] = []
    search_roots = [
        _LOCAL_APPDATA / "Code" / "logs",
        _LOCAL_APPDATA / "Code" / "CrashpadMetrics-active.pma",
    ]
    for root in search_roots:
        if root.is_file():
            try:
                stat = root.stat()
                results.append(CrashInfo(
                    file_path=str(root),
                    size_bytes=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                ))
            except OSError:
                pass
        elif root.is_dir():
            for path in root.rglob("*crash*"):
                if path.is_file():
                    try:
                        stat = path.stat()
                        results.append(CrashInfo(
                            file_path=str(path),
                            size_bytes=stat.st_size,
                            modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        ))
                    except OSError:
                        pass
    return results


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def _init_approved_roots() -> None:
    global APPROVED_STORAGE_ROOTS
    APPROVED_STORAGE_ROOTS = {r.resolve() for r in VSCODE_STORAGE_ROOTS if r.exists()}


def scan_workspaces(
    *,
    top_n: int = 10,
    deep: bool = False,
    include_processes: bool = False,
    include_crashes: bool = False,
    extra_roots: Sequence[Path] | None = None,
) -> DiagnosisReport:
    """Scan VS Code storage roots and return a :class:`DiagnosisReport`."""
    _init_approved_roots()

    roots_to_scan: list[Path] = list(VSCODE_STORAGE_ROOTS)
    if extra_roots:
        roots_to_scan.extend(extra_roots)

    entries: list[WorkspaceEntry] = []
    roots_scanned: list[str] = []
    total_size = 0

    for root in roots_to_scan:
        if not root.exists():
            continue
        roots_scanned.append(str(root))

        if root.is_file():
            # Single file root (e.g., CrashpadMetrics)
            try:
                stat = root.stat()
                total_size += stat.st_size
            except OSError:
                pass
            continue

        # Category name from the root folder
        category = root.name

        # For workspaceStorage, each child folder is a workspace hash
        if "workspacestorage" in root.name.lower():
            try:
                children = sorted(root.iterdir())
            except (OSError, PermissionError):
                continue
            for child in children:
                if not child.is_dir():
                    continue
                sz, fc, newest = _dir_size(child)
                total_size += sz
                repo_path = _resolve_repo_from_workspace_json(child) or _resolve_repo_from_state_db(child)
                repo_name = _repo_name_from_path(repo_path)
                heavy = _heavy_subfolders(child) if deep else []
                entries.append(WorkspaceEntry(
                    folder_name=child.name,
                    folder_path=str(child),
                    size_bytes=sz,
                    file_count=fc,
                    last_modified=newest.isoformat() if newest else None,
                    repo_path=repo_path,
                    repo_name=repo_name,
                    severity=_severity(sz),
                    heavy_subfolders=heavy,
                    root_category=category,
                ))
        else:
            # Aggregate the whole root into one entry
            sz, fc, newest = _dir_size(root)
            total_size += sz
            heavy = _heavy_subfolders(root) if deep else []
            entries.append(WorkspaceEntry(
                folder_name=root.name,
                folder_path=str(root),
                size_bytes=sz,
                file_count=fc,
                last_modified=newest.isoformat() if newest else None,
                severity=_severity(sz),
                heavy_subfolders=heavy,
                root_category=category,
            ))

    entries.sort(key=lambda e: e.size_bytes, reverse=True)
    top_entries = entries[:top_n] if top_n > 0 else entries

    severity_counts = {"ok": 0, "warn": 0, "critical": 0}
    for e in entries:
        severity_counts[e.severity] = severity_counts.get(e.severity, 0) + 1

    recommendations = _build_recommendations(entries, total_size)

    report = DiagnosisReport(
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
        hostname=platform.node(),
        roots_scanned=roots_scanned,
        total_size_bytes=total_size,
        workspace_count=len(entries),
        entries=top_entries,
        repos_flagged=severity_counts.get("warn", 0) + severity_counts.get("critical", 0),
        severity_counts=severity_counts,
        process_diagnostics=_process_diagnostics() if include_processes else [],
        crash_reports=_crash_reports() if include_crashes else [],
        recommendations=recommendations,
    )
    return report


def _build_recommendations(entries: list[WorkspaceEntry], total_size: int) -> list[str]:
    recs: list[str] = []
    total_mb = total_size / (1024 ** 2)
    critical = [e for e in entries if e.severity == "critical"]
    warn = [e for e in entries if e.severity == "warn"]
    if total_mb > 2000:
        recs.append(f"Total VS Code storage is {_format_bytes(total_size)} — consider running cleanup.")
    if critical:
        names = ", ".join(e.repo_name or e.folder_name for e in critical[:5])
        recs.append(f"{len(critical)} critical workspace(s): {names}. Run cleanup --repo <name> to reclaim space.")
    if warn:
        recs.append(f"{len(warn)} workspace(s) at warning level. Review with --deep for subfolder breakdown.")
    if not critical and not warn:
        recs.append("All workspaces within healthy size limits.")
    recs.append("Use `master --run cleanup-storage --execute` to reclaim space (dry-run is default).")
    return recs


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_report(report: DiagnosisReport, *, as_json: bool = False) -> None:
    """Pretty-print or JSON-dump the diagnosis report."""
    if as_json:
        print(json.dumps(asdict(report), indent=2, default=str))
        return

    print(f"\n{'='*72}")
    print(f"  VS Code Storage Diagnosis  —  {report.timestamp}")
    print(f"  Host: {report.hostname}")
    print(f"{'='*72}")
    print(f"  Roots scanned:   {len(report.roots_scanned)}")
    print(f"  Workspaces:      {report.workspace_count}")
    print(f"  Total size:      {_format_bytes(report.total_size_bytes)}")
    print(f"  Severity:        ok={report.severity_counts.get('ok', 0)}  "
          f"warn={report.severity_counts.get('warn', 0)}  "
          f"critical={report.severity_counts.get('critical', 0)}")
    print(f"{'='*72}\n")

    # Table header
    sev_w = 8
    size_w = 12
    files_w = 8
    name_w = 30
    repo_w = 40
    header = (f"  {'Severity':<{sev_w}}  {'Size':>{size_w}}  {'Files':>{files_w}}  "
              f"{'Folder/Hash':<{name_w}}  {'Repo':<{repo_w}}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    for entry in report.entries:
        sev_label = entry.severity.upper()
        size_str = _format_bytes(entry.size_bytes)
        repo_label = entry.repo_name or entry.repo_path or "—"
        folder_short = entry.folder_name[:name_w]
        print(f"  {sev_label:<{sev_w}}  {size_str:>{size_w}}  {entry.file_count:>{files_w}}  "
              f"{folder_short:<{name_w}}  {repo_label:<{repo_w}}")

        if entry.heavy_subfolders:
            for sf in entry.heavy_subfolders[:3]:
                sf_size = _format_bytes(sf.size_bytes)
                print(f"           └─ {sf.name:<25} {sf_size:>10}  ({sf.file_count} files)")

    # Process diagnostics
    if report.process_diagnostics:
        print("\n--- VS Code Processes ---")
        for p in report.process_diagnostics[:10]:
            print(f"  PID {p.pid:>6}  {p.name:<25}  {p.memory_mb:.0f} MB  CPU {p.cpu_percent:.1f}%")

    # Crash reports
    if report.crash_reports:
        print("\n--- Crash Reports ---")
        for c in report.crash_reports[:10]:
            print(f"  {c.file_path}  ({_format_bytes(c.size_bytes)}, modified {c.modified})")

    # Recommendations
    if report.recommendations:
        print("\n--- Recommendations ---")
        for rec in report.recommendations:
            print(f"  • {rec}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diagnose-storage",
        description="Diagnose VS Code workspace storage bloat.",
    )
    parser.add_argument("--top", type=int, default=10,
                        help="Show top N offenders (0 = all). Default: 10.")
    parser.add_argument("--deep", action="store_true",
                        help="Include heavy subfolder breakdown per workspace.")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Emit machine-readable JSON instead of table.")
    parser.add_argument("--processes", action="store_true",
                        help="Include VS Code process memory diagnostics (requires psutil).")
    parser.add_argument("--crashes", action="store_true",
                        help="Include crash report file listing.")
    parser.add_argument("--extra-root", action="append", default=[], dest="extra_roots",
                        help="Additional storage root to scan (repeatable).")
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    extra = [Path(r) for r in args.extra_roots] if args.extra_roots else None
    report = scan_workspaces(
        top_n=args.top,
        deep=args.deep,
        include_processes=args.processes,
        include_crashes=args.crashes,
        extra_roots=extra,
    )
    print_report(report, as_json=args.json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
