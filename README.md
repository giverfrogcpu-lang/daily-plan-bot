# 毎朝スケジュール自動提案ボット

Googleカレンダー + Googleタスクを毎朝7:00に読み取り、Claude AIがスケジュール案を作成してLINEに通知します。

## セットアップ手順

### STEP 1: Google Cloud Console で認証情報を作る

1. https://console.cloud.google.com にアクセス（Googleアカウントでログイン）
2. 左上のプロジェクト → 「新しいプロジェクト」で `daily-plan-bot` を作成
3. 左メニュー「APIとサービス」→「ライブラリ」から以下を有効化：
   - **Google Calendar API**
   - **Google Tasks API**
4. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」
   - アプリケーションの種類：**デスクトップアプリ**
   - 名前：`daily-plan-bot`
5. 作成したら「JSONをダウンロード」→ ファイル名を `credentials.json` に変更

### STEP 2: ローカルで認証してトークンを取得

```bash
cd ~/Desktop/daily-plan-bot

# 仮想環境を作成
python3 -m venv venv
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# credentials.json を src フォルダに置く
cp ~/Downloads/credentials.json src/

# 認証スクリプトを実行（ブラウザが開くのでGoogleアカウントを許可）
cd src
python setup_auth.py
```

表示された JSON を全部コピーしておく（GitHub Secretsに貼る）

### STEP 3: LINE Messaging API のトークンを取得

1. https://developers.line.biz にアクセス（LINEアカウントでログイン）
2. 「コンソール」→「プロバイダーを作成」
3. 「チャンネルを作成」→「Messaging API」を選択
4. チャンネル設定→「Messaging API設定」タブ
5. 「チャンネルアクセストークン」→「発行」ボタンを押してコピー
6. 同ページの「あなたのユーザーID」もコピー（LINE公式アカウントに友達追加しておく）

### STEP 4: GitHubリポジトリを作って Secrets を設定

1. https://github.com で新規リポジトリを作成（名前：`daily-plan-bot`、Privateでも可）
2. ローカルからプッシュ：

```bash
cd ~/Desktop/daily-plan-bot
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/あなたのユーザー名/daily-plan-bot.git
git push -u origin main
```

3. GitHub リポジトリの「Settings」→「Secrets and variables」→「Actions」→「New repository secret」で以下を追加：

| 名前 | 値 |
|------|-----|
| `GOOGLE_TOKEN_JSON` | STEP 2 でコピーしたJSONをそのまま貼る |
| `ANTHROPIC_API_KEY` | Anthropic APIキー（https://console.anthropic.com） |
| `LINE_CHANNEL_ACCESS_TOKEN` | STEP 3 で取得したトークン |
| `LINE_USER_ID` | STEP 3 で確認したユーザーID（`U` から始まる文字列） |

### STEP 5: 動作確認

GitHub のリポジトリページ → 「Actions」タブ → 「毎朝のスケジュール通知」→ 「Run workflow」で手動実行してテスト。

LINEにメッセージが届けば完了！

---

## 仕組み

- **毎朝7:00 JST** に GitHub Actions が自動起動
- Googleカレンダー（今日の予定）+ Googleタスク（未完了タスク）を取得
- Claude AI（Sonnet 4.6）がスケジュール案を生成
- LINE Messaging API でプッシュ通知
- カレンダーへの登録は手動（通知はあくまで「案」）

## 注意事項

- GitHub Actions は個人利用なら無料枠内で動きます
- Google Token は有効期限があるので、1年に1回ほど STEP 2 をやり直す必要があります
- LINE Messaging API の無料プランは月1000通まで（個人利用では十分）
