import os
import json
from datetime import datetime, timedelta
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic
import requests

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

JST = pytz.timezone("Asia/Tokyo")


def get_google_credentials():
    token_data = os.environ.get("GOOGLE_TOKEN_JSON")
    if not token_data:
        raise Exception("GOOGLE_TOKEN_JSON が設定されていません")

    creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def get_today_events(calendar_service):
    now = datetime.now(JST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    result = (
        calendar_service.events()
        .list(
            calendarId="primary",
            timeMin=today_start.isoformat(),
            timeMax=today_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for e in result.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        end = e["end"].get("dateTime", e["end"].get("date", ""))
        events.append({"title": e.get("summary", "(無題)"), "start": start, "end": end})

    return events


def get_tasks(tasks_service):
    tasklists = tasks_service.tasklists().list().execute()
    all_tasks = []

    for tl in tasklists.get("items", []):
        result = (
            tasks_service.tasks()
            .list(tasklist=tl["id"], showCompleted=False, showHidden=False)
            .execute()
        )
        for t in result.get("items", []):
            due = t.get("due", "")
            if due:
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(JST)
                due_str = due_dt.strftime("%m/%d")
            else:
                due_str = "期限なし"
            all_tasks.append({"title": t.get("title", ""), "due": due_str})

    return all_tasks


def generate_schedule(events, tasks):
    now = datetime.now(JST)
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    today_str = f"{now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}）"

    if events:
        events_text = "\n".join(
            f"- {e['start']} 〜 {e['end']}：{e['title']}" for e in events
        )
    else:
        events_text = "今日の予定はありません"

    if tasks:
        tasks_text = "\n".join(f"- {t['title']}（期限：{t['due']}）" for t in tasks)
    else:
        tasks_text = "未完了タスクはありません"

    prompt = f"""今日は{today_str}です。

【Googleカレンダー（今日の予定）】
{events_text}

【Googleタスク（未完了）】
{tasks_text}

上記をもとに今日の1日のスケジュール案を作成してください。
優先順位：締切が近いもの → クイックタスク → 制作系 → 事務系
LINEに通知するので、シンプルで見やすい箇条書きにしてください。
今日のスケジュールに入らないタスクは「今日は見送り」として末尾に記載してください。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def send_line_message(text):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()


def main():
    print("Google認証中...")
    creds = get_google_credentials()

    calendar_service = build("calendar", "v3", credentials=creds)
    tasks_service = build("tasks", "v1", credentials=creds)

    print("カレンダーとタスクを取得中...")
    events = get_today_events(calendar_service)
    tasks = get_tasks(tasks_service)

    print(f"取得完了 - 予定:{len(events)}件 / タスク:{len(tasks)}件")

    print("スケジュール案を生成中...")
    schedule_text = generate_schedule(events, tasks)

    print("LINEに送信中...")
    send_line_message(schedule_text)

    print("完了!")
    print("=" * 50)
    print(schedule_text)


if __name__ == "__main__":
    main()
