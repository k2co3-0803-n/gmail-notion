# 三井住友カード利用額 → Notion

Gmailに届く三井住友カードのデビット利用通知をmessage単位で取得し、Gmailの`internalDate`をEurope/Amsterdamに変換した日ごとに合計してNotionへ記録します。同じ日を再実行した場合は全メールを再集計して上書きするため、二重加算しません。

## Notionデータベース

次のプロパティを用意します（名前はGitHub Variablesで変更可能です）。

| 名前 | 型 | 用途 |
|---|---|---|
| `日付` | タイトル | `YYYY/M/D`形式（例：`2026/8/23`）の集計日（一意にしてください） |
| `合計額` | Number | その日のJPY合計 |

Notion Integrationを作り、対象データベースの接続先に追加して、Internal Integration SecretとDatabase IDを控えます。

## Gmail OAuth

Google CloudでGmail APIを有効化し、OAuthクライアントを作成します。対象Googleアカウントで`https://www.googleapis.com/auth/gmail.readonly`を許可して、オフラインアクセス用refresh tokenを取得してください。OAuth同意画面がテスト中の場合は、そのアカウントをテストユーザーに追加します。

## GitHub設定

Repository Settings → Secrets and variables → Actions に以下のSecretsを登録します。

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

Notionのプロパティ名が異なる場合だけ、Variablesに`NOTION_DATE_PROPERTY`と`NOTION_AMOUNT_PROPERTY`を登録します。日付列はタイトル型、金額列は数値型として処理します。

ワークフローは毎日UTC 02:15（Amsterdamの03:15/冬時間、04:15/夏時間）に起動し、Amsterdamの前日分を同期します。GitHub Actionsの開始が多少遅れても対象日は変わりません。Run workflowの`target_date`で対象日を明示でき、空欄で手動実行した場合はAmsterdamの当日分を同期します。

## ローカル実行・テスト

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python card_to_notion.py --date 2026-08-22
```

対象メールは件名が完全一致するものだけです。Gmail検索では直近2日を取得し、本文の「利用日」は日付判定に使いません。本文を解析できない対象メールがあれば処理を失敗させ、黙って少ない合計をNotionへ書かない設計です。
