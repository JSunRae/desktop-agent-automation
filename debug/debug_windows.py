"""
Debug script to list all top-level windows to find the VS Code window title.
"""
import uiautomation as auto

output = []
output.append("Listing all top-level windows:\n")
output.append("-" * 80)

vscode_candidates = []

for w in auto.GetRootControl().GetChildren():
    if isinstance(w, auto.WindowControl):
        try:
            name = w.Name
            if name:  # Only show windows with names
                output.append(f"Window: {name}")
                # Check if it might be VS Code
                if "code" in name.lower() or "visual studio" in name.lower():
                    output.append("  -> Possible VS Code match!")
                    vscode_candidates.append(name)
        except Exception as e:
            output.append(f"Error reading window: {e}")

output.append("-" * 80)
output.append("\nVS Code candidate windows found:")
for candidate in vscode_candidates:
    output.append(f"  - {candidate}")
output.append("\nLook for your VS Code window in the list above.")

# Print everything
for line in output:
    print(line)

# Also save to file
with open("window_list.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
