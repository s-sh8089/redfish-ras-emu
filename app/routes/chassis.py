import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.database import get_db
from app.event_dispatcher import check_threshold, dispatch_event
from app.helpers import not_found_response

router = APIRouter()


def _chassis_resource(row) -> dict:
    cid = row["id"]
    base = f"/redfish/v1/Chassis/{cid}"
    resource = {
        "@odata.id": base,
        "@odata.type": "#Chassis.v1_25_0.Chassis",
        "@odata.context": "/redfish/v1/$metadata#Chassis.Chassis",
        "Id": cid,
        "Name": row["name"],
        "ChassisType": row["chassis_type"],
        "Model": row["model"],
        "Manufacturer": row["manufacturer"],
        "SerialNumber": row["serial_number"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "HeightMm": row["rack_units"] * 44.45 if row["rack_units"] else None,
        "Links": {
            "ManagedBy": [{"@odata.id": "/redfish/v1/Managers/BMC"}]
        },
        "Sensors": {"@odata.id": f"{base}/Sensors"},
        "Power": {"@odata.id": f"{base}/Power"},
        "Thermal": {"@odata.id": f"{base}/Thermal"},
    }
    if row["location_info"]:
        resource["Location"] = json.loads(row["location_info"])
    return resource


def _chassis_sensor_resource(row, chassis_id: str) -> dict:
    sid = row["id"]
    resource = {
        "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Sensors/{sid}",
        "@odata.type": "#Sensor.v1_9_0.Sensor",
        "@odata.context": "/redfish/v1/$metadata#Sensor.Sensor",
        "Id": sid,
        "Name": row["name"],
        "ReadingType": row["reading_type"],
        "Reading": row["reading"],
        "ReadingUnits": row["reading_units"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
    }
    thresholds: dict[str, Any] = {}
    if row["threshold_upper_caution"] is not None:
        thresholds["UpperCaution"] = {"Reading": row["threshold_upper_caution"]}
    if row["threshold_upper_critical"] is not None:
        thresholds["UpperCritical"] = {"Reading": row["threshold_upper_critical"]}
    if row["threshold_lower_caution"] is not None:
        thresholds["LowerCaution"] = {"Reading": row["threshold_lower_caution"]}
    if row["threshold_lower_critical"] is not None:
        thresholds["LowerCritical"] = {"Reading": row["threshold_lower_critical"]}
    if thresholds:
        resource["Thresholds"] = thresholds
    return resource


# ---------------------------------------------------------------------------
# Chassis Collection
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/Chassis")
def chassis_collection(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id FROM chassis ORDER BY id").fetchall()
    return {
        "@odata.id": "/redfish/v1/Chassis",
        "@odata.type": "#ChassisCollection.ChassisCollection",
        "@odata.context": "/redfish/v1/$metadata#ChassisCollection.ChassisCollection",
        "Name": "Chassis Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"/redfish/v1/Chassis/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/Chassis/{chassis_id}")
def chassis(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    if not row:
        return not_found_response(f"Chassis {chassis_id}")
    return _chassis_resource(row)


class ChassisPatch(BaseModel):
    Status: Optional[dict] = None


@router.patch("/redfish/v1/Chassis/{chassis_id}")
def patch_chassis(chassis_id: str, body: ChassisPatch, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    if not row:
        return not_found_response(f"Chassis {chassis_id}")
    if body.Status:
        state = body.Status.get("State", row["status_state"])
        health = body.Status.get("Health", row["status_health"])
        db.execute(
            "UPDATE chassis SET status_state=?, status_health=? WHERE id=?",
            (state, health, chassis_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    return _chassis_resource(row)


# --- Sensors ---

@router.get("/redfish/v1/Chassis/{chassis_id}/Sensors")
def chassis_sensors(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    rows = db.execute(
        "SELECT id FROM chassis_sensors WHERE chassis_id=? ORDER BY id", (chassis_id,)
    ).fetchall()
    return {
        "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Sensors",
        "@odata.type": "#SensorCollection.SensorCollection",
        "@odata.context": "/redfish/v1/$metadata#SensorCollection.SensorCollection",
        "Name": "Chassis Sensor Collection",
        "Members@odata.count": len(rows),
        "Members": [
            {"@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Sensors/{r['id']}"} for r in rows
        ],
    }


@router.get("/redfish/v1/Chassis/{chassis_id}/Sensors/{sensor_id}")
def chassis_sensor(chassis_id: str, sensor_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    return _chassis_sensor_resource(row, chassis_id)


class ChassisSensorPatch(BaseModel):
    Reading: Optional[float] = None


@router.patch("/redfish/v1/Chassis/{chassis_id}/Sensors/{sensor_id}")
def patch_chassis_sensor(
    chassis_id: str,
    sensor_id: str,
    body: ChassisSensorPatch,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    if body.Reading is not None:
        exceeded, severity, msg = check_threshold(row, body.Reading)
        db.execute(
            "UPDATE chassis_sensors SET reading=? WHERE chassis_id=? AND id=?",
            (body.Reading, chassis_id, sensor_id),
        )
        db.commit()
        if exceeded:
            background_tasks.add_task(
                dispatch_event,
                "Alert",
                f"/redfish/v1/Chassis/{chassis_id}/Sensors/{sensor_id}",
                msg,
                severity,
                "Base.1.0.ConditionInRelatedResource",
            )
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    return _chassis_sensor_resource(row, chassis_id)


# --- Power (legacy endpoint) ---

@router.get("/redfish/v1/Chassis/{chassis_id}/Power")
def chassis_power(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    power_sensor = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND reading_type='Power' LIMIT 1",
        (chassis_id,),
    ).fetchone()
    reading = power_sensor["reading"] if power_sensor else 0.0
    return {
        "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Power",
        "@odata.type": "#Power.v1_7_1.Power",
        "@odata.context": "/redfish/v1/$metadata#Power.Power",
        "Id": "Power",
        "Name": "Power",
        "PowerControl": [
            {
                "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Power#/PowerControl/0",
                "MemberId": "0",
                "Name": "Rack Total Power",
                "PowerConsumedWatts": reading,
                "PowerCapacityWatts": 10000.0,
                "Status": {"State": "Enabled", "Health": "OK"},
            }
        ],
    }


# --- Thermal (legacy endpoint) ---

@router.get("/redfish/v1/Chassis/{chassis_id}/Thermal")
def chassis_thermal(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    temp_rows = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND reading_type='Temperature' ORDER BY id",
        (chassis_id,),
    ).fetchall()
    humidity_rows = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND reading_type='Humidity' ORDER BY id",
        (chassis_id,),
    ).fetchall()

    temperatures = []
    for i, row in enumerate(temp_rows):
        entry: dict[str, Any] = {
            "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Thermal#/Temperatures/{i}",
            "MemberId": str(i),
            "Name": row["name"],
            "ReadingCelsius": row["reading"],
            "Status": {"State": row["status_state"], "Health": row["status_health"]},
        }
        if row["threshold_upper_caution"] is not None:
            entry["UpperThresholdNonCritical"] = row["threshold_upper_caution"]
        if row["threshold_upper_critical"] is not None:
            entry["UpperThresholdCritical"] = row["threshold_upper_critical"]
        temperatures.append(entry)

    fans = [
        {
            "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Thermal#/Fans/0",
            "MemberId": "0",
            "Name": "Rack Cooling Fan",
            "Reading": 3600,
            "ReadingUnits": "RPM",
            "Status": {"State": "Enabled", "Health": "OK"},
        }
    ]

    return {
        "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Thermal",
        "@odata.type": "#Thermal.v1_7_1.Thermal",
        "@odata.context": "/redfish/v1/$metadata#Thermal.Thermal",
        "Id": "Thermal",
        "Name": "Thermal",
        "Temperatures": temperatures,
        "Fans": fans,
        "Humidity": [
            {
                "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Thermal#/Humidity/{i}",
                "MemberId": str(i),
                "Name": row["name"],
                "Reading": row["reading"],
                "Status": {"State": row["status_state"], "Health": row["status_health"]},
            }
            for i, row in enumerate(humidity_rows)
        ],
    }
