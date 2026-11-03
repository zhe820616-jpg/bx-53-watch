import os
import sys
import requests
from urllib.parse import quote

topic = os.getenv("NTFY_TOPIC", "").strip()
if not topic:
    raise SystemExit("NTFY_TOPIC secret is not configured")

response = requests.post(
    "https://ntfy.sh/" + quote(topic, safe=""),
    data="這是 BX-53 監控系統的通知連線測試。若收到此訊息，代表 GitHub Actions 已成功送達 ntfy。",
    headers={
        "Title": "BX-53 notification test",
        "Priority": "default",
        "Tags": "white_check_mark",
    },
    timeout=(8, 20),
)
response.raise_for_status()
print(f"ntfy accepted test notification: HTTP {response.status_code}")
