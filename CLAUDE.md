# カスタマイズ

## 基本ルール

- 必ず日本語で応答すること。
- 必ず計画を立てて文書化すること。
- 変更完了後は必ず結果に関するレポートを作成すること。

## プロジェクト概要

下記のリンクに記載されたRedfishAPIのリクエスト、レスポンス、エンドポイントを再現するためのシミュレータ。
RASとしてラック全体の電源やセンサー類を主に管理するためのAPI。
https://dmtf.org/sites/default/files/standards/documents/DSP2056_1.1.0.pdf
https://redfish.dmtf.org/schemas/DSP2046_2020.3.html
https://redfish.dmtf.org/redfish/mockups/wipupspdu

## 技術スタック

- Python 3.11
- FastAPI + Uvicorn
- SQLite3
- Docker / Docker Compose

## 開発環境

コンテナを使い、localhost:8009でHTTP通信をする。

```bash
docker compose up --build
```

## アーキテクチャルール

- ルートは `app/routes/` 配下にリソース単位で1ファイル。
- 新規ルートを追加したら `app/main.py` の `include_router()` に必ず追記する。
- DBスキーマ変更は `app/database.py` の `_create_tables()` と `_seed_data()` を編集する。
- 状態変化を伴う操作（電源制御・センサー更新・UPS状態変化）は `BackgroundTasks` 経由で `dispatch_event()` を呼び出し、購読済み宛先にWebhook POSTを送信する。
- 認証は `app/main.py` の `auth_middleware` で全エンドポイントに適用する。認証不要パスは `_AUTH_EXEMPT` に追加し、ログインエンドポイント（`POST /SessionService/Sessions`）も明示的に除外する。
- アウトレット電源変更後は必ず集計ヘルパー（`_recalculate_pdu_aggregates` / `_recalculate_ups_aggregates`）を呼び出して Branch・Mains・センサーの集計値を同期させる。コミットは集計ヘルパー呼び出し後に1回だけ行う。
- センサーの `Reading` を更新する際は `check_threshold()` の結果を `status_health` にも反映する（`Warning` / `Critical` / `OK`）。
- 個別リソースの GET ハンドラーは `response: Response` パラメータを追加して `ETag` ヘッダーを返す。PATCH ハンドラーは `request: Request` で `If-Match` を検査し不一致なら `precondition_failed_response()` を返す。
- コレクション GET ハンドラーは `$top` / `$skip` クエリパラメータ（`alias` で指定）と `odata_pagination()` ヘルパーを使いページネーションする。`Members@odata.count` は常に全件数を返す。
- `PowerCycle` / `GracefulShutdown` は同期応答せず `tasks` テーブルにタスクを作成して `202 Accepted` を返す。`BackgroundTasks` でアウトレット状態を変更後、タスクを `Completed` に更新する。
- SSE クライアントは `app/sse_manager.py` の `SSEManager` が管理する。`dispatch_event()` は Webhook 送信と同時に `sse_manager.broadcast()` を呼び出す。SSE エンドポイントは認証不要パスに含め、ハンドラー内で `X-Auth-Token` ヘッダーまたは `?token=` クエリパラメータを検証する。

## コーディング規約

- **言語:** Python 3.11
- **フレームワーク:** FastAPI
- **Router 命名:** ファイル名と同じ snake_case のモジュールに `router = APIRouter()` を定義する。
- **ルート関数名:** リソースを表す簡潔な snake_case（例: `def rack_pdu():`, `def pdu_outlets():`）
- **DB アクセス:** `db: sqlite3.Connection = Depends(get_db)` を引数で受け取る。
- **JSON 格納フィールド:** SQLite に JSON 配列・オブジェクトを保存する列は `json.loads()` / `json.dumps()` で変換する。
- **エラー:** 存在しないリソースは `not_found_response()` を返す。不正リクエストは `bad_request_response(message)` を返す。
- **レスポンス:** ルート関数は `dict` を return する（FastAPIが自動でJSONシリアライズ）。エラーのみ `JSONResponse` を使う。例外として `POST /SessionService/Sessions` はレスポンスヘッダー（`X-Auth-Token`）が必要なため `JSONResponse` を直接返す。
- **イベント通知:** 状態変化後に `background_tasks.add_task(dispatch_event, ...)` で非同期POSTを行う。`dispatch_event` は独自にDB接続を開く（`get_db` の接続はレスポンス返却時にクローズ済みのため）。
- **コメント:** 原則不要。処理の意図が自明でない箇所のみ 1 行で記述する。

## ディレクトリ構成

```
redfish-ras-emu/
├── app/
│   ├── __init__.py          # 空ファイル
│   ├── main.py              # FastAPI アプリ定義、lifespan (init_db)、auth_middleware、全ルーター登録
│   ├── auth.py              # validate_token() / unauthorized_response() — トークン検証・未認証レスポンス
│   ├── sse_manager.py       # SSEManager — SSEクライアント管理・broadcast() — dispatch_event から呼ばれる
│   ├── config.py            # DB_PATH / EVENT_RETRY_ATTEMPTS / EVENT_RETRY_INTERVAL 設定（環境変数で上書き可）
│   ├── database.py          # SQLite 初期化 (init_db)、get_db()、シードデータ
│   ├── helpers.py           # not_found_response / bad_request_response / compute_etag / check_etag / precondition_failed_response / odata_pagination 等の共通関数
│   ├── event_dispatcher.py  # dispatch_event() / check_threshold() / _deliver_with_retry() — Webhook送信・リトライ・閾値判定・ログ記録・SSEブロードキャスト
│   └── routes/              # APIRouter（リソース単位で1ファイル）
│       ├── __init__.py
│       ├── service_root.py       # GET /redfish/v1/
│       ├── metadata.py           # GET /redfish/v1/$metadata / /redfish/v1/odata
│       ├── session_service.py    # SessionService / Sessions CRUD — ログイン・ログアウト・セッション管理
│       ├── power_equipment.py    # PowerEquipment / RackPDUs / Mains / Branches / Outlets / Sensors / Metrics / FloorPDUs / PowerShelves
│       ├── ups.py                # UPSs / Mains / Outlets / Sensors / Metrics
│       ├── chassis.py            # Chassis / Sensors / Power / Thermal / LogServices
│       ├── managers.py           # Managers / NetworkProtocol / EthernetInterfaces / LogServices
│       ├── log_service.py        # LogServices / LogEntries / ClearLog (Manager・Chassis 共用)
│       ├── task_service.py       # TaskService / Tasks CRUD — タスク参照・削除
│       └── event_service.py      # EventService / Subscriptions / SubmitTestEvent / SSE
├── data/                    # SQLite DB 保存先 (コンテナ volume mount: ./data:/data)
│   └── redfish.db           # 自動生成される。git管理対象外
├── docs/
│   └── plan.md              # 実装計画書
├── Dockerfile               # python:3.11-slim ベース、port 8009
├── docker-compose.yml       # port 8009:8009、./data:/data ボリューム
├── requirements.txt         # fastapi==0.115.0, uvicorn[standard]==0.30.6, pydantic==2.9.2, requests==2.32.3
├── README.md                # 環境構築・使用方法
└── CLAUDE.md                # このファイル
```

## 重要ファイル

| ファイル | 役割 |
|---|---|
| `app/main.py` | `FastAPI` インスタンス生成。`lifespan` で `init_db()` を呼び出す。全 `APIRouter` を `include_router()` で登録する。新規ルート追加時は必ずここに追記する。 |
| `app/database.py` | `_create_tables()` でテーブル定義、`_seed_data()` で初期データ投入。テーブル追加時は両関数を編集する。`get_db()` は FastAPI の `Depends` 経由でリクエストごとに接続を管理する。 |
| `app/helpers.py` | `not_found_response()` / `bad_request_response(msg)` / `created_response(data, location)` / `no_content_response()` を提供する。 |
| `app/auth.py` | `validate_token(token)`: セッションテーブルを参照しトークンの有効性を検証する（有効期限チェック込み）。`unauthorized_response()`: 401 レスポンスを返す。`app/main.py` の `auth_middleware` から呼ばれる。 |
| `app/event_dispatcher.py` | `dispatch_event(event_type, origin, message, severity, message_id)`: 購読一覧取得・ログ記録・Webhook送信（リトライ付き）を行う。`_deliver_with_retry(destination, payload)`: `EVENT_RETRY_ATTEMPTS` 回まで再送し、5xx またはコネクションエラー時のみ `EVENT_RETRY_INTERVAL` 秒待って再試行する。`check_threshold(row, new_reading)`: センサー閾値超過を判定し `(exceeded, severity, message)` を返す。 |
| `app/routes/session_service.py` | SessionService / Sessions CRUD。`POST /Sessions` はパスワードを SHA-256 でハッシュして `accounts` テーブルと照合し、一致したら `sessions` テーブルにセッションを登録して `X-Auth-Token` ヘッダーを返す。 |
| `app/sse_manager.py` | `SSEManager` シングルトン。`set_loop(loop)` で FastAPI の asyncio ループを登録し、`broadcast(data)` でスレッドセーフに全接続クライアントにイベントを送信する。`subscribe()` は async context manager で接続中キューを管理する。 |
| `app/routes/task_service.py` | TaskService / Tasks CRUD。PowerCycle・GracefulShutdown の非同期操作が作成するタスクを参照・削除する。 |
| `app/routes/metadata.py` | `GET /redfish/v1/$metadata`（EDMX XML）と `GET /redfish/v1/odata`（OData サービスドキュメント JSON）を提供する。 |
| `app/routes/log_service.py` | Manager・Chassis 両リソースの `LogServices` / `LogEntries` / `ClearLog` を提供する。ログエントリは `event_dispatcher` が自動生成する。 |
| `app/config.py` | `DB_PATH` / `EVENT_RETRY_ATTEMPTS`（デフォルト3）/ `EVENT_RETRY_INTERVAL`（デフォルト60秒）は環境変数で上書き可能。`EVENT_RETRY_INTERVAL` はテスト時に短縮できる。 |

## データベーステーブル

| テーブル | 内容 |
|---|---|
| `rack_pdus` | PDU 本体情報 |
| `pdu_outlets` | PDU アウトレット（コンセント）|
| `pdu_mains` | PDU 入力主回路 |
| `pdu_branches` | PDU 分岐回路 |
| `pdu_sensors` | PDU センサー |
| `upss` | UPS 本体情報 |
| `ups_outlets` | UPS アウトレット |
| `ups_mains` | UPS 入力回路 |
| `ups_sensors` | UPS センサー |
| `chassis` | ラックシャーシ |
| `chassis_sensors` | ラックセンサー |
| `managers` | 管理コントローラ |
| `event_subscriptions` | イベント購読 |
| `log_entries` | ログエントリ。`owner_type`（'manager' / 'chassis'）と `owner_id` で所有者を識別する。`dispatch_event()` が呼ばれるたびに自動生成される（`owner_id='BMC'`）。 |
| `accounts` | ユーザーアカウント。パスワードは SHA-256 ハッシュで保存。初期シードは `admin` / `redfish`（`_seed_data()` で `accounts` テーブルが空の場合のみ投入）。 |
| `sessions` | セッション。`token`（UUID）と `expires_at`（作成から24時間）で管理する。ミドルウェアが `token` と `expires_at > now()` で有効性を検証する。 |
| `tasks` | 非同期操作タスク。`task_state`（Running / Completed / Exception）で進捗を管理する。PowerCycle・GracefulShutdown 実行時に作成される。 |

## 禁止事項

- `data/redfish.db` を git にコミットしない（シードデータは `database.py` で管理する）。
- ルート内で `JSONResponse` を直接生成しない（正常レスポンスは `dict` を return し、エラーは `helpers.py` の関数を使う）。
- テーブルの直接 DROP / TRUNCATE を行わない（データリセットはコンテナ外から `data/redfish.db` を削除して `docker compose up` で再起動する）。
- `uvicorn` を Docker 外で直接実行しない（`DB_PATH` が未設定になりパスが変わる）。

## Git運用

- `data/redfish.db` は `.gitignore` に追加済み。
- コミットメッセージは日本語可。変更内容が分かる簡潔な記述にする。
- ブランチ戦略は未定義（現状 main 直コミット）。
