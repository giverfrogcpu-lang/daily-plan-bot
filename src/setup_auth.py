"""
ローカルで一度だけ実行してGoogle認証トークンを取得するスクリプト。
生成された token.json の中身を GitHub Secrets の GOOGLE_TOKEN_JSON に貼る。
"""
import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


def main():
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                print(f"ERROR: {CREDENTIALS_PATH} が見つかりません。")
                print("Google Cloud Console からダウンロードして同じフォルダに置いてください。")
                return
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    print("認証成功!")
    print()
    print("=" * 60)
    print("以下の内容を GitHub Secrets の GOOGLE_TOKEN_JSON に貼ってください:")
    print("=" * 60)
    with open(TOKEN_PATH) as f:
        token_data = json.load(f)
    print(json.dumps(token_data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
