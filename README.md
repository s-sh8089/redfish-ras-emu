# Redfish RAS Emulator

ラック全体の電源（PDU/UPS）とセンサーを管理するための Redfish API シミュレータ。
DSP2056（UPS/PDU Redfish Integration）に準拠したエンドポイントを提供する。

## 技術スタック

- Python 3.11
- FastAPI + Uvicorn
- SQLite3
- Docker / Docker Compose
- requests（Webhook送信用）

## 起動方法

```bash
docker compose up --build
```

起動後、`http://localhost:8009` でAPIが利用可能になる。

### データリセット

```bash
docker compose down
rm -f data/redfish.db
docker compose up
```

## API エンドポイント

### Service Root

| Method | Path |
|--------|------|
| GET | `/redfish/v1/` |

### PowerEquipment

| Method | Path | 説明 |
|--------|------|------|
| GET | `/redfish/v1/PowerEquipment` | PowerEquipment リソース |
| GET | `/redfish/v1/PowerEquipment/RackPDUs` | PDU コレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/RackPDUs/{id}` | PDU 個別リソース |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Mains` | 入力主回路コレクション |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Mains/{mid}` | 入力主回路 |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Branches` | 分岐回路コレクション |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Branches/{bid}` | 分岐回路 |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets` | アウトレットコレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets/{oid}` | アウトレット個別 |
| POST | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets/{oid}/Actions/Outlet.PowerControl` | 電源制御 |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Sensors` | センサーコレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Sensors/{sid}` | センサー個別 |
| GET | `/redfish/v1/PowerEquipment/RackPDUs/{id}/Metrics` | メトリクス |

### UPS

| Method | Path | 説明 |
|--------|------|------|
| GET | `/redfish/v1/PowerEquipment/UPSs` | UPS コレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/UPSs/{id}` | UPS 個別リソース |
| GET | `/redfish/v1/PowerEquipment/UPSs/{id}/Mains` | 入力回路コレクション |
| GET | `/redfish/v1/PowerEquipment/UPSs/{id}/Mains/{mid}` | 入力回路 |
| GET | `/redfish/v1/PowerEquipment/UPSs/{id}/Outlets` | アウトレットコレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/UPSs/{id}/Outlets/{oid}` | アウトレット個別 |
| POST | `/redfish/v1/PowerEquipment/UPSs/{id}/Outlets/{oid}/Actions/Outlet.PowerControl` | 電源制御 |
| GET | `/redfish/v1/PowerEquipment/UPSs/{id}/Sensors` | センサーコレクション |
| GET, PATCH | `/redfish/v1/PowerEquipment/UPSs/{id}/Sensors/{sid}` | センサー個別 |
| GET | `/redfish/v1/PowerEquipment/UPSs/{id}/Metrics` | メトリクス |

### Chassis

| Method | Path | 説明 |
|--------|------|------|
| GET | `/redfish/v1/Chassis` | シャーシコレクション |
| GET, PATCH | `/redfish/v1/Chassis/{id}` | シャーシ個別 |
| GET | `/redfish/v1/Chassis/{id}/Sensors` | センサーコレクション |
| GET, PATCH | `/redfish/v1/Chassis/{id}/Sensors/{sid}` | センサー個別 |
| GET | `/redfish/v1/Chassis/{id}/Power` | 電力サマリ（レガシー） |
| GET | `/redfish/v1/Chassis/{id}/Thermal` | 温熱サマリ（レガシー） |

### Managers

| Method | Path | 説明 |
|--------|------|------|
| GET | `/redfish/v1/Managers` | マネージャーコレクション |
| GET | `/redfish/v1/Managers/{id}` | マネージャー個別 |
| GET | `/redfish/v1/Managers/{id}/NetworkProtocol` | ネットワークプロトコル |
| GET | `/redfish/v1/Managers/{id}/EthernetInterfaces` | NICコレクション |
| GET | `/redfish/v1/Managers/{id}/EthernetInterfaces/{nic_id}` | NIC個別 |

### EventService

| Method | Path | 説明 |
|--------|------|------|
| GET | `/redfish/v1/EventService` | イベントサービス |
| GET | `/redfish/v1/EventService/Subscriptions` | 購読コレクション |
| POST | `/redfish/v1/EventService/Subscriptions` | 購読作成 |
| GET | `/redfish/v1/EventService/Subscriptions/{id}` | 購読個別 |
| DELETE | `/redfish/v1/EventService/Subscriptions/{id}` | 購読削除 |
| POST | `/redfish/v1/EventService/Actions/EventService.SubmitTestEvent` | テストイベント送信 |

## 使用例

### アウトレット電源制御

```bash
# 電源オフ
curl -X POST http://localhost:8009/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/A1/Actions/Outlet.PowerControl \
  -H "Content-Type: application/json" \
  -d '{"PowerState": "Off"}'

# 電源オン
curl -X POST http://localhost:8009/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/A1/Actions/Outlet.PowerControl \
  -H "Content-Type: application/json" \
  -d '{"PowerState": "On"}'

# 電源サイクル（再起動）
curl -X POST http://localhost:8009/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/A1/Actions/Outlet.PowerControl \
  -H "Content-Type: application/json" \
  -d '{"PowerState": "PowerCycle"}'
```

`PowerState` の有効値: `On` / `Off` / `PowerCycle` / `GracefulShutdown`

### センサー値の更新（シミュレーション用）

```bash
# 温度センサーの値を更新
curl -X PATCH http://localhost:8009/redfish/v1/Chassis/Rack1/Sensors/Temp1 \
  -H "Content-Type: application/json" \
  -d '{"Reading": 45.0}'

# UPS バッテリー残量を更新
curl -X PATCH http://localhost:8009/redfish/v1/PowerEquipment/UPSs/1/Sensors/BattCharge \
  -H "Content-Type: application/json" \
  -d '{"Reading": 20.0}'
```

### UPS 状態変更

```bash
# 停電シミュレーション
curl -X PATCH http://localhost:8009/redfish/v1/PowerEquipment/UPSs/1 \
  -H "Content-Type: application/json" \
  -d '{"LineInputStatus": "OutOfPower", "BackupEstimatedMinutes": 30}'
```

### イベント購読と Webhook 通知

購読を登録しておくと、状態変化が起きたタイミングで登録先URLへ自動的にPOSTが送信される。

```bash
# 購読登録
curl -X POST http://localhost:8009/redfish/v1/EventService/Subscriptions \
  -H "Content-Type: application/json" \
  -d '{
    "Destination": "http://192.168.1.100:9000/events",
    "Context": "MyMonitor",
    "EventTypes": ["Alert", "StatusChange"]
  }'

# 購読一覧
curl http://localhost:8009/redfish/v1/EventService/Subscriptions

# テストイベント手動送信
curl -X POST http://localhost:8009/redfish/v1/EventService/Actions/EventService.SubmitTestEvent \
  -H "Content-Type: application/json" \
  -d '{"EventType": "Alert", "Message": "Test alert", "Severity": "Warning"}'
```

**EventTypes フィルター:** 購読時に `EventTypes` を指定すると、合致するイベントのみ配信される。空配列または未指定の場合は全種別を受信する。

## Webhook イベント通知

### イベント発火条件

| 操作 | EventType | Severity |
|------|-----------|----------|
| アウトレット電源制御（PDU/UPS） | `StatusChange` | `OK` |
| UPS `LineInputStatus` → `OutOfPower` / `LossOfInput` | `Alert` | `Critical` |
| UPS その他ステータス変化 | `StatusChange` | `OK` |
| センサー値が警告閾値（UpperCaution/LowerCaution）を超過 | `Alert` | `Warning` |
| センサー値が危険閾値（UpperCritical/LowerCritical）を超過 | `Alert` | `Critical` |
| `SubmitTestEvent` アクション | 任意 | 任意 |

### 通知ペイロード形式

購読先URLへPOSTされるJSONの例：

```json
{
  "@odata.type": "#Event.v1_7_0.Event",
  "Id": "c2820d39",
  "Name": "Event Array",
  "Context": "MyMonitor",
  "Events": [
    {
      "EventType": "StatusChange",
      "EventId": "c2820d39",
      "EventTimestamp": "2026-06-08T03:10:11Z",
      "Severity": "OK",
      "Message": "Outlet A1 PowerState changed to Off via Off",
      "MessageId": "Base.1.0.PropertyValueChanged",
      "OriginOfCondition": {
        "@odata.id": "/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/A1"
      }
    }
  ]
}
```

### 動作の仕組み

1. 状態変化後、FastAPI `BackgroundTasks` に `dispatch_event()` を登録
2. レスポンス返却後にバックグラウンドで実行（リクエストをブロックしない）
3. `event_subscriptions` テーブルから有効な購読を取得し、`EventTypes` フィルターを適用
4. 合致した購読先へ `requests.post(timeout=5)` でPOST（失敗は無視）

## シードデータ

起動時に以下のデータが自動投入される。

### RackPDU (`/redfish/v1/PowerEquipment/RackPDUs/1`)

| リソース | 内容 |
|---------|------|
| アウトレット | A1〜A4（Branch1）、B1〜B4（Branch2）、各15A IEC_60320_C13 |
| 主回路 | Main1（100V / 21.1A / 2060W） |
| 分岐回路 | Branch1、Branch2（各20A） |
| センサー | 電流、電圧、電力、電力量、周波数、温度 |

### UPS (`/redfish/v1/PowerEquipment/UPSs/1`)

| リソース | 内容 |
|---------|------|
| 定格 | 5000VA / 4500W |
| アウトレット | OUT1〜OUT4（各20A IEC_60320_C19） |
| バッテリー | 95% / 残45分 |
| センサー | 入力電力、出力電力、バッテリー電圧・残量、入出力電圧 |

### Chassis (`/redfish/v1/Chassis/Rack1`)

| リソース | 内容 |
|---------|------|
| 構成 | 42U ラック |
| センサー | 温度×4（入口・中間・出口・上部）、湿度×2、総電力×1 |

### Manager (`/redfish/v1/Managers/BMC`)

| 項目 | 値 |
|------|----|
| タイプ | RackManager |
| IPアドレス | 192.168.1.1 |
| ホスト名 | rack-bmc-1 |

## 参照仕様

- [DSP2056_1.1.0](https://dmtf.org/sites/default/files/standards/documents/DSP2056_1.1.0.pdf) - UPS/PDU Redfish Integration
- [DSP2046_2020.3](https://redfish.dmtf.org/schemas/DSP2046_2020.3.html) - Redfish Interoperability Profiles
- [wipupspdu mockup](https://redfish.dmtf.org/redfish/mockups/wipupspdu) - WIP UPS/PDU mockup
