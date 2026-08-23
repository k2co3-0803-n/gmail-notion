# 三井住友カード利用額 → Notion

Gmailに届く三井住友カードのデビット利用通知をmessage単位で取得し、Gmailの`internalDate`をEurope/Amsterdamに変換した日ごとに合計してNotionへ記録します。同じ日を再実行した場合は全メールを再集計して上書きするため、二重加算しません。

## Notionデータベース

次のプロパティを用意します（名前はGitHub Variablesで変更可能です）。

| 名前 | 型 | 用途 |
|---|---|---|
| `日付` | テキスト | `YYYY/M/D`形式（例：`2026/8/23`）の集計日（一意にしてください） |
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

Notionのプロパティ名が異なる場合だけ、Variablesに`NOTION_DATE_PROPERTY`と`NOTION_AMOUNT_PROPERTY`を登録します。日付列をNotionのDate型で使う場合は、`NOTION_DATE_PROPERTY_TYPE`に`date`を登録してください。省略時はテキスト型（`rich_text`）として処理します。

ワークフローはAmsterdamの23時台を夏時間・冬時間ともカバーするようUTC 21:55と22:55に起動し、実行時にもAmsterdamの時刻を確認します。該当しない側は何も更新せず終了します。Actionsの遅延や日付をまたいだ再処理には、Run workflowの`target_date`で対象日を明示できます。

## ローカル実行・テスト

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python card_to_notion.py --date 2026-08-22
```

対象メールは件名が完全一致するものだけです。Gmail検索では直近2日を取得し、本文の「利用日」は日付判定に使いません。本文を解析できない対象メールがあれば処理を失敗させ、黙って少ない合計をNotionへ書かない設計です。
