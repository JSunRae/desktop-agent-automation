"""
Investigate signals to identify the 'main' VS Code window.
Prints all visible VS Code windows annotated with various heuristics.
"""
import ctypes
import ctypes.wintypes as wt

import psutil

EnumWindows = ctypes.windll.user32.EnumWindows
GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
IsWindowVisible = ctypes.windll.user32.IsWindowVisible
GetWindowTextW = ctypes.windll.user32.GetWindowTextW
GetWindowLongW = ctypes.windll.user32.GetWindowLongW
GetWindow = ctypes.windll.user32.GetWindow
GetClassNameW = ctypes.windll.user32.GetClassNameW
GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
GetWindowRect = ctypes.windll.user32.GetWindowRect
IsIconic = ctypes.windll.user32.IsIconic  # minimized?
IsZoomed = ctypes.windll.user32.IsZoomed  # maximized?
MonitorFromWindow = ctypes.windll.user32.MonitorFromWindow

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_OVERLAPPEDWINDOW = 0x00CF0000
GW_OWNER = 4
MONITOR_DEFAULTTONULL = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def get_process_info():
    """Build map of PID -> process info for Code.exe processes."""
    procs = {}
    for p in psutil.process_iter(['pid', 'name', 'ppid', 'create_time', 'cmdline', 'exe']):
        if p.info['name'] == 'Code.exe':
            try:
                parent_name = psutil.Process(p.info['ppid']).name() if p.info['ppid'] else 'N/A'
            except Exception:
                parent_name = 'N/A'
            procs[p.info['pid']] = {
                'ppid': p.info['ppid'],
                'parent_name': parent_name,
                'create_time': p.info['create_time'],
                'cmdline': ' '.join(p.info.get('cmdline') or [])[:120],
            }
    return procs

def enumerate_vscode_windows(code_pids):
    """Win32 EnumWindows to find all visible VS Code windows."""
    infos = []

    def callback(hwnd, lParam):
        pid = wt.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in code_pids:
            return True
        if not IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if not title:
            return True
        cls_buf = ctypes.create_unicode_buffer(64)
        GetClassNameW(hwnd, cls_buf, 64)
        ex_style = GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = GetWindowLongW(hwnd, GWL_STYLE)
        owner = GetWindow(hwnd, GW_OWNER)
        rect = wt.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL)
        infos.append({
            'hwnd': hwnd,
            'pid': pid.value,
            'title': title,
            'cls': cls_buf.value,
            'ex_style': ex_style,
            'style': style,
            'owner': owner,
            'width': width,
            'height': height,
            'minimized': bool(IsIconic(hwnd)),
            'maximized': bool(IsZoomed(hwnd)),
            'on_monitor': bool(monitor),
        })
        return True

    EnumWindows(WNDENUMPROC(callback), 0)
    return infos

def main():
    proc_info = get_process_info()
    code_pids = set(proc_info.keys())
    print(f"Code.exe processes found: {len(code_pids)}")

    fg_hwnd = GetForegroundWindow()
    windows = enumerate_vscode_windows(code_pids)

    print(f"Visible titled VS Code windows: {len(windows)}\n")
    print("=" * 100)

    for w in windows:
        pid = w['pid']
        pinfo = proc_info.get(pid, {})
        is_appwindow = bool(w['ex_style'] & WS_EX_APPWINDOW)
        is_toolwindow = bool(w['ex_style'] & WS_EX_TOOLWINDOW)
        has_no_owner = (w['owner'] == 0)
        is_fg = (w['hwnd'] == fg_hwnd)
        parent_is_vscode = pinfo.get('ppid') in code_pids
        cmdline = pinfo.get('cmdline', '')

        # Detect known non-main signals
        is_dev_host = '[Extension Development Host]' in w['title']
        is_devtools = 'Developer Tools' in w['title']
        title_ends_vscode = w['title'].endswith(' - Visual Studio Code') or w['title'].endswith(' - VS Code')
        is_main_candidate = (
            title_ends_vscode
            and has_no_owner
            and not is_toolwindow
            and not is_dev_host
            and not is_devtools
            and w['on_monitor']
        )

        print(f"HWND={w['hwnd']}  PID={pid}  FG={is_fg}")
        print(f"  Title   : {w['title'][:90]}")
        print(f"  Class   : {w['cls']}")
        print(f"  Size    : {w['width']}x{w['height']}  Minimized={w['minimized']}  Maximized={w['maximized']}")
        print(f"  Styles  : WS_EX_APPWINDOW={is_appwindow}  WS_EX_TOOLWINDOW={is_toolwindow}  Owner={'none' if has_no_owner else w['owner']}")
        print(f"  Process : ppid={pinfo.get('ppid')}  parent={pinfo.get('parent_name')}  parent_is_vscode={parent_is_vscode}")
        print(f"  CmdLine : {cmdline[:100]}")
        print(f"  Title-ends-vscode={title_ends_vscode}  DevHost={is_dev_host}  DevTools={is_devtools}")
        print(f"  >>> MAIN CANDIDATE: {is_main_candidate}")
        print("-" * 100)

if __name__ == '__main__':
    main()
