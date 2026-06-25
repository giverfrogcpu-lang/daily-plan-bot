import os
import json
from datetime import datetime, timedelta
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from groq import Groq
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


def format_time(dt_str):
    try:
        dt = datetime.fromisoformat(dt_str).astimezone(JST)
        return dt.strftime("%H:%M")
    except Exception:
        return dt_str


def generate_schedule(events, tasks):
    now = datetime.now(JST)
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    today_str = f"{now.strftime('%m/%d')}（{weekdays[now.weekday()]}）"

    if events:
        events_text = "\n".join(
            f"- {format_time(e['start'])}〜{format_time(e['end'])} {e['title']}"
            for e in events
        )
    else:
        events_text = "なし"

    if tasks:
        tasks_text = "\n".join(f"- {t['title']}（{t['due']}）" for t in tasks)
    else:
        tasks_text = "なし"

    prompt = f"""今日は{today_str}です。

【今日の予定】
{events_text}

【未完了タスク】
{tasks_text}

以下の形式でLINEに送る朝のスケジュール通知を作ってください。

形式（必ずこの通りに）:
🌅 {today_str} おはようございます！

📅 今日の予定
（時間順に箇条書き、例: ・10:00〜11:00 MTG）

✅ 今日やること（優先順）
（締切が近い順に最大5件、例: ・〇〇の作業（今日締切））

📌 今週中
（今週締切のタスク最大3件）

⬜ 今日は見送り
（入らなかったタスクを全部箇条書き、例: ・〇〇）

絵文字と箇条書きで見やすく。日本語のみ。余計な説明は不要。"""

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
    )

    return response.choices[0].message.content


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
