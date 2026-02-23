from automation.cli.master import _ensure_orchestrator
import time
import socket

print("Testing _ensure_orchestrator...")
_ensure_orchestrator()

# Verify port is open
TBS_HOST = "127.0.0.1"
TBS_PORT = 8777
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex((TBS_HOST, TBS_PORT))
if result == 0:
    print("Success: Port 8777 is open.")
else:
    print(f"Failure: Port 8777 is closed (result {result}).")
s.close()