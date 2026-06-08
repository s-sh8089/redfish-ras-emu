import json
import sqlite3
import uuid
from datetime import datetime, timezone

import requests

from app import config


def dispatch_event(
    event_type: str,
    origin_of_condition: str,
    message: str,
    severity: str = "OK",
    message_id: str = "Base.1.0.PropertyValueChanged",
):
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        subs = conn.execute(
            "SELECT * FROM event_subscriptions WHERE status_state='Enabled'"
        ).fetchall()
    finally:
        conn.close()

    if not subs:
        return

    event_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for sub in subs:
        if sub["event_types"]:
            allowed = json.loads(sub["event_types"])
            if allowed and event_type not in allowed:
                continue

        payload = {
            "@odata.type": "#Event.v1_7_0.Event",
            "Id": event_id,
            "Name": "Event Array",
            "Context": sub["context"] or "",
            "Events": [
                {
                    "EventType": event_type,
                    "EventId": event_id,
                    "EventTimestamp": timestamp,
                    "Severity": severity,
                    "Message": message,
                    "MessageId": message_id,
                    "OriginOfCondition": {"@odata.id": origin_of_condition},
                }
            ],
        }

        try:
            requests.post(sub["destination"], json=payload, timeout=5)
        except Exception:
            pass


def check_threshold(row, new_reading: float) -> tuple[bool, str, str]:
    """閾値チェック。(超過フラグ, 深刻度, メッセージ) を返す。"""
    name = row["name"]
    units = row["reading_units"]

    if row["threshold_upper_critical"] is not None and new_reading >= row["threshold_upper_critical"]:
        return (
            True,
            "Critical",
            f"{name} reading {new_reading}{units} exceeded upper critical threshold {row['threshold_upper_critical']}{units}",
        )
    if row["threshold_upper_caution"] is not None and new_reading >= row["threshold_upper_caution"]:
        return (
            True,
            "Warning",
            f"{name} reading {new_reading}{units} exceeded upper caution threshold {row['threshold_upper_caution']}{units}",
        )
    if row["threshold_lower_critical"] is not None and new_reading <= row["threshold_lower_critical"]:
        return (
            True,
            "Critical",
            f"{name} reading {new_reading}{units} fell below lower critical threshold {row['threshold_lower_critical']}{units}",
        )
    if row["threshold_lower_caution"] is not None and new_reading <= row["threshold_lower_caution"]:
        return (
            True,
            "Warning",
            f"{name} reading {new_reading}{units} fell below lower caution threshold {row['threshold_lower_caution']}{units}",
        )
    return False, "OK", ""
