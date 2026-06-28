from flask import Flask, request, abort
import os
import json
import base64
import re
import hmac
import hashlib
from datetime import datetime
import pytz
import requests as http_requests
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from groq import Groq

app = Flask(__name__)

JST = pytz.timezone("Asia/Tokyo")
SPREADSHEET_ID = "1YSxAEyP0SmE6V_NlZDShtAb0XyboA_aGbs4LS6v8g_M"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

COLUMN_MAP = {
    "status": "D",
    "last_contact": "E",
    "next_mtg": "F",
    "next_action": "G",
    "issues": "H",
}

FIELD_NAMES = {
    "status": "ステータス",
    "last_contact": "最終対話日",
    "next_mtg": "次回MTG",
    "next_action": "次回アクション",
    "issues": "課題",
}

CLIENTS = [
    {"name": "カラーズ", "row": 2},
    {"name": "パンスール", "row": 3},
    {"name": "兎屋", "row": 4},
    {"name": "For", "row": 5},
]

TASK_PREFIXES = ("タスク:", "タスク：", "todo:", "todo：", "task:", "task：")
LIST_KEYWORDS = ("一覧", "クライアント一覧", "状況", "ステータス", "リスト")
CLIENT_NAME_MAP = {"カラーズ": 0, "パンスール": 1, "兎屋": 2, "for": 3, "For": 3}


def close_github_issue(number):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        return False
    resp = http_requests.patch(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={"state": "closed"},
    )
    return resp.status_code == 200


def create_github_issue(title, body=""):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        return None
    resp = http_requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={"title": title, "body": body, "labels": ["task"]},
    )
    return resp.json() if resp.status_code == 201 else None


def read_all_clients():
    creds = get_google_creds()
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheets()[0]
    result = []
    for c in CLIENTS:
        row = ws.row_values(c["row"])
        result.append({
            "name": c["name"],
            "status": row[3] if len(row) > 3 else "—",
            "last_contact": row[4] if len(row) > 4 else "—",
            "next_mtg": row[5] if len(row) > 5 else "—",
            "next_action": row[6] if len(row) > 6 else "—",
            "issues": row[7] if len(row) > 7 else "—",
        })
    return result


def get_google_creds():
    token_data = os.environ["GOOGLE_TOKEN_JSON"]
    creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
    return creds


def send_line_reply(reply_token, message):
    http_requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": message}],
        },
    )


def update_sheet(row, updates):
    creds = get_google_creds()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheets()[0]

    updated = []
    for field, col in COLUMN_MAP.items():
        value = updates.get(field)
        if value:
            ws.update(values=[[value]], range_name=f"{col}{row}")
            updated.append(FIELD_NAMES[field])
    return updated


def build_prompt(text, today, is_image=False):
    base = f"""SNSコンサル事業のクライアント管理スプレッドシートを更新するためのAIです。

クライアント一覧：
- カラーズ様（行2）: Instagram運用代行
- パンスール様（行3）: Instagram運用代行（神戸龍谷中学・高校）
- 兎屋様（行4）: Instagram/TikTok運用代行（BAR）
- For様（行5）: TikTok運用代行（キャバクラ）

今日の日付: {today}

{"画像（LINEのスクショ）から" if is_image else "以下のメッセージから"}スプレッドシートに記録すべき具体的な更新情報（MTG日程・ステータス変更・次回アクション・課題等）を読み取ってください。
{"" if is_image else f"メッセージ: {text}"}

【重要ルール】
- 質問・確認・雑談・感想など、スプシに書き込む具体的な情報がない場合は必ず null のみを返すこと
- updatesの全フィールドがnullになる場合も null を返すこと
- 推測や憶測で情報を補完しないこと

JSON形式（更新情報がある場合のみ、必ずこの形式で返すこと）:
{{
  "client": "クライアント名",
  "row": 行番号（2〜5の整数）,
  "updates": {{
    "status": null または "🔴 要対応" または "🟡 進行中" または "🟢 順調" または "🔵 確認待ち" または "⚪ 準備中",
    "last_contact": null または "YYYY-MM-DD",
    "next_mtg": null または "次回MTG日時文字列",
    "next_action": null または "次回アクション内容",
    "issues": null または "課題・懸念点"
  }},
  "reply": "更新完了の報告文（日本語・2〜3行）"
}}"""
    return base


def analyze_message(text, reply_token, image_data=None):
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    today = datetime.now(JST).strftime("%Y-%m-%d")

    if image_data:
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                    },
                    {"type": "text", "text": build_prompt("", today, is_image=True)},
                ],
            }
        ]
    else:
        model = "llama-3.3-70b-versatile"
        messages = [
            {"role": "user", "content": build_prompt(text, today)}
        ]

    response = groq_client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1000,
    )

    result_text = response.choices[0].message.content.strip()

    # null返答の場合
    if result_text.lower().strip() == "null":
        send_line_reply(reply_token, "このBOTはクライアント情報のスプシ更新専用です。\nMTG日程・ステータス・次回アクションなどの情報をお送りください。")
        return

    # JSONを抽出
    json_match = re.search(r'\{[\s\S]*\}', result_text)
    if not json_match:
        send_line_reply(reply_token, "解析できませんでした。もう少し具体的に送ってみてください。")
        return

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError:
        send_line_reply(reply_token, "解析エラーが発生しました。もう一度試してください。")
        return

    if not result or result.get("row") is None:
        send_line_reply(reply_token, "このBOTはクライアント情報のスプシ更新専用です。\nMTG日程・ステータス・次回アクションなどの情報をお送りください。")
        return

    updated_fields = update_sheet(result["row"], result.get("updates", {}))

    if updated_fields:
        reply = result.get("reply", f"✅ {result.get('client', '不明')}のスプシを更新しました！\n更新: {', '.join(updated_fields)}")
    else:
        reply = "ℹ️ 受け取りましたが、更新すべき新しい情報はありませんでした。"

    send_line_reply(reply_token, reply)


@app.route("/webhook", methods=["POST"])
def webhook():
    body_bytes = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")

    if channel_secret:
        expected = base64.b64encode(
            hmac.new(channel_secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
        ).decode()
        if signature != expected:
            abort(400)

    body = json.loads(body_bytes.decode("utf-8"))

    for event in body.get("events", []):
        if event["type"] != "message":
            continue

        reply_token = event["replyToken"]
        msg = event["message"]

        if msg["type"] == "text":
            text = msg["text"].strip()

            # タスク完了 #N
            close_match = re.match(r'^(タスク完了|完了|close)\s*#?(\d+)', text, re.IGNORECASE)
            if close_match:
                num = int(close_match.group(2))
                if close_github_issue(num):
                    send_line_reply(reply_token, f"✅ タスク #{num} を完了にしました！")
                else:
                    send_line_reply(reply_token, f"⚠️ タスク #{num} のクローズに失敗しました。")
                continue

            # タスク登録
            task_title = next(
                (text[len(p):].strip() for p in TASK_PREFIXES if text.lower().startswith(p.lower())),
                None,
            )
            if task_title:
                issue = create_github_issue(task_title)
                if issue:
                    send_line_reply(
                        reply_token,
                        f"✅ タスクを登録しました！\n📌 #{issue['number']} {issue['title']}\n🔗 {issue['html_url']}",
                    )
                else:
                    send_line_reply(reply_token, "⚠️ GitHub Issue の作成に失敗しました。\nGITHUB_TOKEN / GITHUB_REPO の設定を確認してください。")

            # クライアント個別確認（例: 「カラーズ 状況」）
            elif matched_client := next((name for name in CLIENT_NAME_MAP if name.lower() in text.lower()), None):
                clients = read_all_clients()
                c = clients[CLIENT_NAME_MAP[matched_client]]
                lines = [
                    f"📋 {c['name']} の状況\n",
                    f"ステータス: {c['status']}",
                    f"最終対話: {c['last_contact']}",
                    f"次回MTG: {c['next_mtg']}",
                    f"次回アクション: {c['next_action']}",
                    f"課題: {c['issues']}",
                ]
                send_line_reply(reply_token, "\n".join(lines))

            # クライアント一覧
            elif any(k in text for k in LIST_KEYWORDS):
                clients = read_all_clients()
                lines = ["📊 クライアント状況一覧\n"]
                for c in clients:
                    lines.append(f"{c['status']} {c['name']}")
                    if c["next_action"] and c["next_action"] != "—":
                        lines.append(f"  → {c['next_action']}")
                    if c["next_mtg"] and c["next_mtg"] != "—":
                        lines.append(f"  📅 {c['next_mtg']}")
                    lines.append("")
                send_line_reply(reply_token, "\n".join(lines).strip())

            # スプシ更新（既存）
            else:
                analyze_message(text, reply_token)

        elif msg["type"] == "image":
            message_id = msg["id"]
            img_resp = http_requests.get(
                f"https://api-data.line.me/v2/bot/message/{message_id}/content",
                headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}"},
            )
            image_b64 = base64.b64encode(img_resp.content).decode()
            analyze_message("", reply_token, image_data=image_b64)

    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
