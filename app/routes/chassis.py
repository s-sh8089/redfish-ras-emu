import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import BaseModel

from app.database import get_db
from app.event_dispatcher import check_threshold, dispatch_event
from app.helpers import (
    check_etag,
    compute_etag,
    not_found_response,
    odata_pagination,
    precondition_failed_response,
)

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
        "LogServices": {"@odata.id": f"{base}/LogServices"},
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
def chassis_collection(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM chassis").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, "/redfish/v1/Chassis")
    rows = db.execute("SELECT id FROM chassis ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    result = {
        "@odata.id": "/redfish/v1/Chassis",
        "@odata.type": "#ChassisCollection.ChassisCollection",
        "@odata.context": "/redfish/v1/$metadata#ChassisCollection.ChassisCollection",
        "Name": "Chassis Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"/redfish/v1/Chassis/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/Chassis/{chassis_id}")
def chassis(chassis_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    if not row:
        return not_found_response(f"Chassis {chassis_id}")
    resource = _chassis_resource(row)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class ChassisPatch(BaseModel):
    Status: Optional[dict] = None


@router.patch("/redfish/v1/Chassis/{chassis_id}")
def patch_chassis(
    chassis_id: str,
    body: ChassisPatch,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    if not row:
        return not_found_response(f"Chassis {chassis_id}")
    if not check_etag(request.headers.get("If-Match"), compute_etag(_chassis_resource(row))):
        return precondition_failed_response()
    if body.Status:
        state = body.Status.get("State", row["status_state"])
        health = body.Status.get("Health", row["status_health"])
        db.execute(
            "UPDATE chassis SET status_state=?, status_health=? WHERE id=?",
            (state, health, chassis_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM chassis WHERE id=?", (chassis_id,)).fetchone()
    resource = _chassis_resource(row)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


# --- Sensors ---

@router.get("/redfish/v1/Chassis/{chassis_id}/Sensors")
def chassis_sensors(
    chassis_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    total = db.execute("SELECT COUNT(*) FROM chassis_sensors WHERE chassis_id=?", (chassis_id,)).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"/redfish/v1/Chassis/{chassis_id}/Sensors")
    rows = db.execute(
        "SELECT id FROM chassis_sensors WHERE chassis_id=? ORDER BY id LIMIT ? OFFSET ?",
        (chassis_id, limit, offset),
    ).fetchall()
    result = {
        "@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Sensors",
        "@odata.type": "#SensorCollection.SensorCollection",
        "@odata.context": "/redfish/v1/$metadata#SensorCollection.SensorCollection",
        "Name": "Chassis Sensor Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"/redfish/v1/Chassis/{chassis_id}/Sensors/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/Chassis/{chassis_id}/Sensors/{sensor_id}")
def chassis_sensor(chassis_id: str, sensor_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    resource = _chassis_sensor_resource(row, chassis_id)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class ChassisSensorPatch(BaseModel):
    Reading: Optional[float] = None
    Thresholds: Optional[dict] = None


@router.patch("/redfish/v1/Chassis/{chassis_id}/Sensors/{sensor_id}")
def patch_chassis_sensor(
    chassis_id: str,
    sensor_id: str,
    body: ChassisSensorPatch,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    if not check_etag(
        request.headers.get("If-Match"),
        compute_etag(_chassis_sensor_resource(row, chassis_id)),
    ):
        return precondition_failed_response()
    if body.Reading is not None:
        exceeded, severity, msg = check_threshold(row, body.Reading)
        new_health = severity if exceeded else "OK"
        db.execute(
            "UPDATE chassis_sensors SET reading=?, status_health=? WHERE chassis_id=? AND id=?",
            (body.Reading, new_health, chassis_id, sensor_id),
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
    if body.Thresholds is not None:
        threshold_map = {
            "UpperCaution": "threshold_upper_caution",
            "UpperCritical": "threshold_upper_critical",
            "LowerCaution": "threshold_lower_caution",
            "LowerCritical": "threshold_lower_critical",
        }
        t_updates: dict[str, Any] = {}
        for rf_key, db_col in threshold_map.items():
            if rf_key in body.Thresholds:
                val = body.Thresholds[rf_key]
                t_updates[db_col] = val.get("Reading") if isinstance(val, dict) else None
        if t_updates:
            set_clause = ", ".join(f"{k}=?" for k in t_updates)
            db.execute(
                f"UPDATE chassis_sensors SET {set_clause} WHERE chassis_id=? AND id=?",
                (*t_updates.values(), chassis_id, sensor_id),
            )
            db.commit()
    row = db.execute(
        "SELECT * FROM chassis_sensors WHERE chassis_id=? AND id=?", (chassis_id, sensor_id)
    ).fetchone()
    resource = _chassis_sensor_resource(row, chassis_id)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


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
