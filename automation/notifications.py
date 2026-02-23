"""
Notification utilities for Desktop Agent Automation.
Handles sending alerts via centralized Telegram Notifications system.
"""

from pathlib import Path
import os
from automation.core.logging import log_normal

# Attempt to import the centralized notification agent
HAS_TELEGRAM_LIB = False
NotifierClient = None
NotifierConfig = None

try:
    from tbs_utils.notifier import NotifierClient, NotifierConfig
    HAS_TELEGRAM_LIB = True
except ImportError:
    pass


def send_telegram_alert(message: str) -> None:
    """
    Send a message via the centralized TelegramNotifications system.
    Using 'ERROR' stage for alerts to ensure visibility.
    """
    if not HAS_TELEGRAM_LIB:
        log_normal("TelegramNotifications library (tbs_utils) not found. Skipping alert.")
        return

    try:
        tbs_url = os.environ.get("TBS_URL")
        secret = os.environ.get("TBS_REPO_SHARED_SECRET")
        agent_name = os.environ.get("AGENT_NAME", "desktop-agent-automation")
        
        if not tbs_url or not secret:
            log_normal("Missing TBS_URL or TBS_REPO_SHARED_SECRET. Skipping alert.")
            return

        config = NotifierConfig(
            url=tbs_url,
            secret=secret,
            repo=agent_name,
            state_path=Path("state/state.json")
        )
        
        client = NotifierClient(config)
        
        payload = client.build_payload(
             task="alert",
             stage="ERROR",
             summary=message[:100] if len(message) > 100 else message,
             details=message,
             next_actions=["await:command"],
             repo=agent_name
        )
        
        client.send(payload)
        log_normal(f"Sent Telegram alert: {message[:50]}...")
            
    except Exception as e:
        log_normal(f"Failed to send Telegram alert: {e}")

