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

{"画像（LINEのスクショ）から" if is_image else "以下のメッセージから"}クライアント情報を読み取り、更新すべき情報をJSONで返してください。
{"" if is_image else f"メッセージ: {text}"}

スプシ更新に無関係（雑談・質問等）の場合は null を返してください。

JSON形式（必ずこの形式のみ返すこと）:
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
        send_line_reply(reply_token, "📝 受け取りました。スプシ更新対象の情報ではなかったのでそのままにします。")
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
        send_line_reply(reply_token, "📝 受け取りました。スプシ更新対象の情報ではなかったのでそのままにします。")
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
            analyze_message(msg["text"], reply_token)

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
