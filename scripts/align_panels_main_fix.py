    args = parser.parse_args()
    
    # Get monitor information
    monitors = get_monitor_info()
    print("\nDetected monitors:")
    for monitor in monitors:
        print(f"  {monitor}")
    print()
    
    # CONFIGURE MODE - handle early and return
    if args.configure:
        # Switch to desktop if needed
        if args.desktop != "current" and needs_desktop_switch(args.desktop):
            print(f"Switching to desktop: {args.desktop}")
            switch_to_desktop(args.desktop)
            import time
            time.sleep(1.0)
        
        # Find VS Code windows
        print("Scanning for VS Code windows...")
        windows = find_all_vscode_windows()
        
        if not windows:
            print("⚠️  No VS Code windows found")
            return 1
        
        print(f"Found {len(windows)} VS Code window(s)\n")
        
        layouts = configure_layouts_interactive(windows, monitors)
        
        if not layouts:
            print("\n⚠️  No layouts captured")
            return 1
        
        print(f"\n✅ Captured {len(layouts)} layout(s)")
        
        # Save configuration
        config_name = args.config_name
        if args.desktop != "current":
            config_name = args.desktop
        
        if save_layout_config(layouts, config_name):
            print(f"\n✅ Configuration saved as '{config_name}'")
            return 0
        else:
            return 1
    
    # ALIGN MODE - process one or more desktops
    # Determine which desktops to process
    desktops_to_process = []
    if args.all_desktops:
        print("Getting all virtual desktops...")
        try:
            import pyvda
            all_desktops = pyvda.get_virtual_desktops()
            desktops_to_process = [d.name for d in all_desktops]
            print(f"Found {len(desktops_to_process)} virtual desktops: {', '.join(desktops_to_process)}\n")
        except Exception as e:
            print(f"⚠️  Error getting virtual desktops: {e}")
            print("Falling back to single desktop mode\n")
            desktops_to_process = [args.desktop]
    else:
        desktops_to_process = [args.desktop]
    
    # Process each desktop
    total_aligned = 0
    total_skipped = 0
    
    for desktop_name in desktops_to_process:
        if len(desktops_to_process) > 1:
            print(f"\n{'='*80}")
            print(f"Processing desktop: {desktop_name}")
            print(f"{'='*80}\n")
        
        # Switch to desktop if needed
        if desktop_name != "current" and needs_desktop_switch(desktop_name):
            print(f"Switching to desktop: {desktop_name}")
            switch_to_desktop(desktop_name)
            import time
            time.sleep(1.0)  # Wait for desktop switch
        
        # Find VS Code windows on this desktop
        print("Scanning for VS Code windows...")
        windows = find_all_vscode_windows()
        
        if not windows:
            print(f"⚠️  No VS Code windows found on desktop '{desktop_name}'")
            continue
        
        print(f"Found {len(windows)} VS Code window(s)\n")
        
        # Determine config name for this desktop
        config_name = args.config_name
        if desktop_name != "current":
            config_name = desktop_name
        
        # For optimize mode, always create new layout from current positions
        layouts = []
        if args.optimize:
            print("\n✨ Optimizing current window arrangement...")
            layouts = optimize_current_layout(windows, monitors, args.monitor, args.limit)
            
            if layouts:
                print(f"\n✅ Created {len(layouts)} optimized layout(s)")
                
                # Save with monitor+count key
                if monitors and args.monitor < len(monitors):
                    monitor = monitors[args.monitor]
                    panel_count = len(layouts)
                    config_key = f"{monitor.width}x{monitor.height}_{panel_count}"
                    print(f"Saving as '{config_key}' (monitor size + panel count)")
                    if save_layout_config(layouts, config_key):
                        print(f"✅ Optimized configuration saved as '{config_key}'")
                        print(f"   This layout will auto-apply for {panel_count} panels on {monitor.width}x{monitor.height} monitor")
                    else:
                        print("⚠️  Warning: Could not save optimized configuration")
            else:
                print("⚠️  Failed to create optimized layout")
                if len(desktops_to_process) == 1:
                    return 1
                continue
        
        # Try loading by monitor+count first for auto-matching
        if not layouts and not args.auto_grid and not args.smart_pack:
            if args.monitor < len(monitors):
                # Count windows on target monitor to try auto-match
                monitor = monitors[args.monitor]
                window_count = 0
                for window in windows:
                    pos = get_window_position(window)
                    if pos:
                        center_x = pos.x + pos.width // 2
                        center_y = pos.y + pos.height // 2
                        if (monitor.x <= center_x < monitor.x + monitor.width and
                            monitor.y <= center_y < monitor.y + monitor.height):
                            window_count += 1
                
                if args.limit and window_count > args.limit:
                    window_count = args.limit
                
                # Try loading by monitor size + count
                if window_count > 0:
                    auto_key = f"{monitor.width}x{monitor.height}_{window_count}"
                    print(f"Looking for layout: {auto_key}")
                    layouts = load_layout_config(auto_key)
                    if layouts:
                        print(f"✅ Found matching layout for {window_count} panels on {monitor.width}x{monitor.height}")
        
        # Fall back to desktop name config
        if not layouts:
            layouts = load_layout_config(config_name)
        
        if not layouts:
            if args.auto_grid or args.smart_pack:
                if args.smart_pack:
                    print("\n🧩 No configuration found - creating smart pack layout...")
                    layouts = create_smart_pack_layout(windows, monitors, args.monitor, args.limit)
                else:
                    print("\n📐 No configuration found - creating auto-grid layout...")
                    layouts = create_auto_grid_layout(windows, monitors, args.monitor, args.limit)
                
                if layouts:
                    print(f"\n✅ Created {len(layouts)} layout(s) in grid arrangement")
                    
                    # Save the auto-generated layout with desktop name
                    if save_layout_config(layouts, config_name):
                        print(f"✅ Auto-grid configuration saved as '{config_name}'")
                    else:
                        print("⚠️  Warning: Could not save auto-grid configuration")
                else:
                    print("⚠️  Failed to create auto-grid layout")
                    if len(desktops_to_process) == 1:
                        return 1
                    continue
            else:
                print(f"\n⚠️  No layout configuration found for '{config_name}'")
                if len(desktops_to_process) == 1:
                    print("\nOptions:")
                    print("  1. Smart pack layout (preserves sizes):")
                    print("     python scripts/align_panels.py --smart-pack")
                    print("  2. Auto-create grid layout:")
                    print("     python scripts/align_panels.py --auto-grid")
                    print("  3. Interactive configuration:")
                    print(f"     python scripts/align_panels.py --configure --config-name {config_name}")
                    return 1
                continue
        
        print(f"Loaded {len(layouts)} layout configuration(s)\n")
        
        # Align windows on this desktop
        if args.dry_run and len(desktops_to_process) == 1:
            print("DRY RUN MODE - No changes will be made\n")
        
        aligned, skipped = align_panels(windows, layouts, monitors, dry_run=args.dry_run)
        total_aligned += aligned
        total_skipped += skipped
        
        if len(desktops_to_process) > 1:
            print(f"\nDesktop '{desktop_name}' results: {aligned} aligned, {skipped} skipped")
    
    # Final summary
    print(f"\n{'='*80}")
    if len(desktops_to_process) > 1:
        print(f"TOTAL RESULTS across {len(desktops_to_process)} desktops:")
    print(f"Results: {total_aligned} aligned, {total_skipped} skipped")
    if args.dry_run:
        print("(DRY RUN - no actual changes made)")
    print(f"{'='*80}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
