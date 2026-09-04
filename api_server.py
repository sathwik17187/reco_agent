"""
Root entrypoint for api_server.py.
Delegates to recovery_agent/api_server.py.
"""
import os
import sys
import subprocess

TARGET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovery_agent")
TARGET_SCRIPT = os.path.join(TARGET_DIR, "api_server.py")

if not os.path.exists(TARGET_SCRIPT):
    print(f"Error: Target script {TARGET_SCRIPT} not found.")
    sys.exit(1)

cmd = [sys.executable, "-u", TARGET_SCRIPT] + sys.argv[1:]
result = subprocess.call(cmd, cwd=TARGET_DIR)
sys.exit(result)
