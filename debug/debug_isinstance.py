"""Test if isinstance check vs ControlType check differ for Chrome buttons"""
import uiautomation as auto

def find_vscode_windows():
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name or ""
            if name.endswith(" - Visual Studio Code"):
                windows.append(win)
        except Exception:
            pass
    return windows

def test_button_detection(vs_win, max_depth=50):
    """Compare isinstance vs ControlType checks"""
    isinstance_buttons = []
    controltype_buttons = []
    mismatch = []
    
    def search(control, depth=0):
        if depth > max_depth:
            return
        
        try:
            name = control.Name or ""
            ct = control.ControlType
            is_button_isinstance = isinstance(control, auto.ButtonControl)
            is_button_ct = (ct == 50000)  # ButtonControl type ID
            
            if is_button_isinstance:
                isinstance_buttons.append((name, depth))
            
            if is_button_ct:
                controltype_buttons.append((name, depth))
            
            # Check for mismatch
            if is_button_isinstance != is_button_ct:
                mismatch.append({
                    'name': name[:60],
                    'isinstance': is_button_isinstance,
                    'controltype': ct,
                    'depth': depth
                })
            
            for child in control.GetChildren():
                search(child, depth + 1)
                
        except Exception:
            pass
    
    search(vs_win)
    
    return {
        'isinstance_count': len(isinstance_buttons),
        'controltype_count': len(controltype_buttons),
        'mismatches': mismatch,
        'isinstance_buttons': isinstance_buttons[:10],  # First 10
        'controltype_buttons': controltype_buttons[:10]
    }

print("="*70)
print("Testing isinstance vs ControlType for button detection")
print("="*70)

windows = find_vscode_windows()
print(f"Found {len(windows)} VS Code window(s)\n")

for i, win in enumerate(windows, 1):
    title = (win.Name or "Unknown")[:60]
    print(f"[{i}] {title}")
    print("-"*60)
    
    result = test_button_detection(win)
    
    print(f"  Buttons found via isinstance(): {result['isinstance_count']}")
    print(f"  Buttons found via ControlType==50000: {result['controltype_count']}")
    print(f"  Mismatches: {len(result['mismatches'])}")
    
    if result['mismatches']:
        print("\n  MISMATCHES (isinstance != ControlType):")
        for m in result['mismatches'][:5]:
            print(f"    Name: '{m['name']}'")
            print(f"      isinstance=ButtonControl: {m['isinstance']}")
            print(f"      ControlType: {m['controltype']}")
    
    print()

print("="*70)
