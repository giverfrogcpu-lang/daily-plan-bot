import requests
import os

token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
user_id = os.environ["LINE_USER_ID"]
message = os.environ["MESSAGE"]

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json={"to": user_id, "messages": [{"type": "text", "text": message}]},
)
resp.raise_for_status()
print("送信完了")
