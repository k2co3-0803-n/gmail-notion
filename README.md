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

対象メールは件名が完全一致するものだけです。Gmail検索では指定日のAmsterdam時間の午前0時から翌日午前0時までを取得し（過去日・夏時間にも対応）、本文の「利用日」は日付判定に使いません。本文を解析できない対象メールがあれば処理を失敗させ、黙って少ない合計をNotionへ書かない設計です。

## アプリ紹介サイト（Google OAuthのリンク用）

`docs/` にビルド不要の日本語サイトを用意しています。

- `docs/index.html`：アプリのホームページ
- `docs/privacy.html`：プライバシーポリシー
- `docs/terms.html`：利用規約

ローカルで確認するには `python3 -m http.server 8000 --directory docs` を実行して、`http://localhost:8000` を開きます。

### GitHub Pagesで公開する

1. `docs/` をGitHubの公開対象ブランチにコミット・プッシュします。
2. リポジトリの **Settings → Pages → Build and deployment** で **Deploy from a branch** を選びます。
3. 公開対象ブランチと **/docs** を選択して保存します。
4. Pagesに表示される公開URLにアクセスし、3ページを確認します。

カスタムドメインを設定していない場合、このリポジトリの想定URLは以下です。公開操作は別途必要です。

| Google Auth Platformの入力欄 | 公開後のURL |
|---|---|
| アプリケーションのホームページ | `https://k2co3-0803-n.github.io/notion-gmail/` |
| プライバシーポリシー | `https://k2co3-0803-n.github.io/notion-gmail/privacy.html` |
| 利用規約 | `https://k2co3-0803-n.github.io/notion-gmail/terms.html` |

Google OAuth同意画面のアプリ名はサイトの `gmail-notion` と一致させてください。開発者表記と問い合わせ先はリポジトリ所有者のGitHubページにしています。専用の問い合わせ先を使用する場合は各HTMLを更新してください。実行ログには利用先・金額が含まれるため、実行環境のログ公開範囲を確認してください。サイトを公開するために、同期用リポジトリや既存の実行ログを公開する必要はありません。現在のリポジトリでPagesを利用できない場合は、`docs/` の内容だけを別の公開用リポジトリまたは静的ホスティングに配置できます。

本番のOAuth申請では、Googleはホームページの公開アクセス、所有権を確認できるドメイン、同一ドメイン内のプライバシーポリシーなどを要求します。必要に応じて所有するカスタムドメインを設定し、Google Search Consoleで確認したうえでGoogle側の承認済みドメインを設定してください。ページの作成・公開だけでOAuth審査が完了するわけではありません。

公式情報：[OAuth 2.0 Policies](https://developers.google.com/identity/protocols/oauth2/policies)、[Manage OAuth App Branding](https://support.google.com/cloud/answer/15549049?hl=en)。
