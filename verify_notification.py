from automation.notifications import send_telegram_alert
import time

print("Sending test alert...")
try:
    send_telegram_alert("This is a test notification after auto-start.")
    print("Notification sent successfully (check logs if it went through).")
except Exception as e:
    print(f"Failed to send: {e}")
