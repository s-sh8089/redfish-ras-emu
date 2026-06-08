# Redfish RAS Emulator 実装計画

## 目的

ラック全体の電源（PDU/UPS）・センサー類をRedfishプロトコルで管理するAPIシミュレータの実装。

## 参照仕様

- DSP2056_1.1.0: UPS/PDU Redfish Integration
- DSP2046_2020.3: Redfish Interoperability Profiles
- wipupspdu mockup

## 技術スタック

- Python 3.11
- FastAPI + Uvicorn
- SQLite3
- Docker / Docker Compose

## エンドポイント一覧

### Service Root
| Method | Path |
|--------|------|
| GET | /redfish/v1/ |

### PowerEquipment（電源管理）
| Method | Path |
|--------|------|
| GET | /redfish/v1/PowerEquipment |
| GET | /redfish/v1/PowerEquipment/RackPDUs |
| GET/PATCH | /redfish/v1/PowerEquipment/RackPDUs/{id} |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Mains |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Mains/{mid} |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Branches |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Branches/{bid} |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets |
| GET/PATCH | /redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets/{oid} |
| POST | /redfish/v1/PowerEquipment/RackPDUs/{id}/Outlets/{oid}/Actions/Outlet.PowerControl |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Sensors |
| GET/PATCH | /redfish/v1/PowerEquipment/RackPDUs/{id}/Sensors/{sid} |
| GET | /redfish/v1/PowerEquipment/RackPDUs/{id}/Metrics |
| GET | /redfish/v1/PowerEquipment/UPSs |
| GET/PATCH | /redfish/v1/PowerEquipment/UPSs/{id} |
| GET | /redfish/v1/PowerEquipment/UPSs/{id}/Mains |
| GET | /redfish/v1/PowerEquipment/UPSs/{id}/Mains/{mid} |
| GET | /redfish/v1/PowerEquipment/UPSs/{id}/Outlets |
| GET/PATCH | /redfish/v1/PowerEquipment/UPSs/{id}/Outlets/{oid} |
| POST | /redfish/v1/PowerEquipment/UPSs/{id}/Outlets/{oid}/Actions/Outlet.PowerControl |
| GET | /redfish/v1/PowerEquipment/UPSs/{id}/Sensors |
| GET/PATCH | /redfish/v1/PowerEquipment/UPSs/{id}/Sensors/{sid} |
| GET | /redfish/v1/PowerEquipment/UPSs/{id}/Metrics |

### Chassis（ラックエンクロージャ）
| Method | Path |
|--------|------|
| GET | /redfish/v1/Chassis |
| GET/PATCH | /redfish/v1/Chassis/{id} |
| GET | /redfish/v1/Chassis/{id}/Sensors |
| GET/PATCH | /redfish/v1/Chassis/{id}/Sensors/{sid} |
| GET | /redfish/v1/Chassis/{id}/Power |
| GET | /redfish/v1/Chassis/{id}/Thermal |

### Managers（管理コントローラ）
| Method | Path |
|--------|------|
| GET | /redfish/v1/Managers |
| GET | /redfish/v1/Managers/{id} |

### EventService（イベント購読）
| Method | Path |
|--------|------|
| GET | /redfish/v1/EventService |
| GET | /redfish/v1/EventService/Subscriptions |
| POST | /redfish/v1/EventService/Subscriptions |
| GET | /redfish/v1/EventService/Subscriptions/{id} |
| DELETE | /redfish/v1/EventService/Subscriptions/{id} |

## データベース設計

| テーブル | 内容 |
|---------|------|
| rack_pdus | PDU本体情報 |
| pdu_outlets | PDUアウトレット（コンセント）|
| pdu_mains | PDU主回路（入力） |
| pdu_branches | PDU分岐回路 |
| pdu_sensors | PDUセンサー |
| upss | UPS本体情報 |
| ups_outlets | UPSアウトレット |
| ups_mains | UPS入力回路 |
| ups_sensors | UPSセンサー |
| chassis | ラックシャーシ |
| chassis_sensors | ラックセンサー |
| managers | 管理コントローラ |
| event_subscriptions | イベント購読 |

## シードデータ

- RackPDU x1: アウトレット8本（A1-A4, B1-B4）、入力回路1本、分岐2本、センサー6本
- UPS x1: アウトレット4本（OUT1-OUT4）、入力回路1本、センサー6本
- Chassis x1: 42Uラック、センサー7本（温度x4, 湿度x2, 電力x1）
- Manager x1: ラック管理コントローラ

## ファイル構成

```
app/
├── __init__.py
├── main.py           # FastAPI アプリ + ライフサイクル
├── config.py         # DB_PATH 設定
├── database.py       # SQLite 初期化・シード・get_db()
├── helpers.py        # 共通レスポンス関数
└── routes/
    ├── __init__.py
    ├── service_root.py
    ├── power_equipment.py   # PowerEquipment + RackPDUs
    ├── ups.py               # UPSs
    ├── chassis.py           # Chassis + Sensors
    ├── managers.py          # Managers
    └── event_service.py     # EventService
```
