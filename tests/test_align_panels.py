"""
Test script for panel alignment functionality.

This script tests the panel alignment utilities without requiring
actual VS Code windows.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.align_panels import (
    WindowPosition,
    PanelLayout,
    MonitorInfo,
    get_monitor_info,
    find_matching_layout,
    _split_monitor_left_right,
)


def test_window_position():
    """Test WindowPosition dataclass."""
    print("Testing WindowPosition...")
    
    pos = WindowPosition(x=100, y=200, width=800, height=600)
    
    # Test to_dict
    pos_dict = pos.to_dict()
    assert pos_dict == {"x": 100, "y": 200, "width": 800, "height": 600}
    
    # Test from_dict
    pos2 = WindowPosition.from_dict(pos_dict)
    assert pos2.x == 100
    assert pos2.y == 200
    assert pos2.width == 800
    assert pos2.height == 600
    
    print("  ✓ WindowPosition works correctly")


def test_panel_layout():
    """Test PanelLayout dataclass."""
    print("Testing PanelLayout...")
    
    layout = PanelLayout(
        pattern="Priority: P1",
        position=WindowPosition(x=0, y=0, width=960, height=1080),
        monitor_index=0
    )
    
    # Test to_dict
    layout_dict = layout.to_dict()
    assert layout_dict["pattern"] == "Priority: P1"
    assert layout_dict["monitor_index"] == 0
    
    # Test from_dict
    layout2 = PanelLayout.from_dict(layout_dict)
    assert layout2.pattern == "Priority: P1"
    assert layout2.position.width == 960
    assert layout2.monitor_index == 0
    
    print("  ✓ PanelLayout works correctly")


def test_monitor_detection():
    """Test monitor detection."""
    print("Testing monitor detection...")
    
    try:
        monitors = get_monitor_info()
        
        if monitors:
            print(f"  Detected {len(monitors)} monitor(s):")
            for monitor in monitors:
                print(f"    {monitor}")
            print("  ✓ Monitor detection works")
        else:
            print("  ⚠️  No monitors detected (fallback mode)")
            
    except Exception as e:
        print(f"  ⚠️  Monitor detection error: {e}")


def test_pattern_matching():
    """Test pattern matching logic."""
    print("Testing pattern matching...")
    
    layouts = [
        PanelLayout(
            pattern="Priority: P1",
            position=WindowPosition(0, 0, 960, 1080),
            monitor_index=0
        ),
        PanelLayout(
            pattern="tf_1",
            position=WindowPosition(960, 0, 960, 1080),
            monitor_index=0
        ),
        PanelLayout(
            pattern="Trading",
            position=WindowPosition(0, 0, 1920, 1080),
            monitor_index=1
        ),
    ]
    
    # Test exact matches
    test_cases = [
        ("Priority: P1 - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code", "Priority: P1"),
        ("Priority: P2 - tf_1 [WSL: Ubuntu-24.04] - Visual Studio Code", "tf_1"),
        ("You are assigned task: manifest… - Trading - Visual Studio Code", "Trading"),
        ("Some other window - Visual Studio Code", None),
    ]
    
    for window_title, expected_pattern in test_cases:
        matched = find_matching_layout(window_title, layouts)
        if expected_pattern is None:
            assert matched is None, f"Expected no match for '{window_title}'"
            print(f"  ✓ Correctly found no match for: {window_title[:50]}")
        else:
            assert matched is not None, f"Expected match for '{window_title}'"
            assert matched.pattern == expected_pattern
            print(f"  ✓ Correctly matched '{window_title[:50]}' to '{expected_pattern}'")


def test_config_serialization():
    """Test configuration file serialization."""
    print("Testing config serialization...")
    
    from scripts.align_panels import save_layout_config, load_layout_config
    import tempfile
    from pathlib import Path
    
    # Create temporary config directory
    temp_dir = Path(tempfile.mkdtemp())
    temp_config = temp_dir / "test_config.json"
    
    try:
        # Temporarily override config path
        import scripts.align_panels as align_module
        original_path = align_module.LAYOUT_CONFIG_PATH
        align_module.LAYOUT_CONFIG_PATH = temp_config
        
        # Create test layouts
        layouts = [
            PanelLayout(
                pattern="Test Window",
                position=WindowPosition(100, 200, 800, 600),
                monitor_index=0
            )
        ]
        
        # Save
        assert save_layout_config(layouts, "test_desktop")
        assert temp_config.exists()
        
        # Load
        loaded = load_layout_config("test_desktop")
        assert len(loaded) == 1
        assert loaded[0].pattern == "Test Window"
        assert loaded[0].position.x == 100
        
        print("  ✓ Config serialization works")
        
        # Restore original path
        align_module.LAYOUT_CONFIG_PATH = original_path
        
    finally:
        # Cleanup
        if temp_config.exists():
            temp_config.unlink()
        if temp_dir.exists():
            temp_dir.rmdir()


def test_three_way_split_ratio():
    """Test 60/40 split behavior used for middle-monitor 3-way heuristic layout."""
    print("Testing 60/40 middle-monitor split...")

    m = MonitorInfo(index=2, x=100, y=50, width=2500, height=1400, is_primary=False)
    left, right = _split_monitor_left_right(m, 0.60)

    assert left.x == 100 and left.y == 50
    assert left.width == 1500
    assert left.height == 1400

    assert right.index == 2
    assert right.x == 1600 and right.y == 50
    assert right.width == 1000
    assert right.height == 1400

    print("  ✓ 60/40 split works correctly")


def main():
    """Run all tests."""
    print("="*80)
    print("PANEL ALIGNMENT UTILITY TESTS")
    print("="*80)
    print()
    
    try:
        test_window_position()
        test_panel_layout()
        test_monitor_detection()
        test_pattern_matching()
        test_config_serialization()
        test_three_way_split_ratio()
        
        print()
        print("="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        return 0
        
    except AssertionError as e:
        print()
        print("="*80)
        print(f"❌ TEST FAILED: {e}")
        print("="*80)
        return 1
    except Exception as e:
        print()
        print("="*80)
        print(f"❌ ERROR: {e}")
        print("="*80)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
