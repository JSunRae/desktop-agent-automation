
import re
from pathlib import Path

file_path = Path(r"c:\Users\Pilot\Documents\Vs Code Projects\desktop-agent-automation\automation\desktop_auto_allow_agent.py")
content = file_path.read_text(encoding="utf-8")

# Replace self._log(msg) with log_message(msg, LOG_PATH)
# We need to handle multi-line calls if any, but grep showed mostly single lines.
# Regex: self\._log\((.*)\) -> log_message(\1, LOG_PATH)

new_content = re.sub(r'self\._log\((.*)\)', r'log_message(\1, LOG_PATH)', content)

file_path.write_text(new_content, encoding="utf-8")
print("Refactoring complete.")
