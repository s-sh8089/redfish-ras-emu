import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.database import get_db
from app.event_dispatcher import check_threshold, dispatch_event
from app.helpers import bad_request_response, not_found_response

router = APIRouter()


# ---------------------------------------------------------------------------
# Builders (shared structure with PDU outlets/sensors)
# ---------------------------------------------------------------------------

def _ups_resource(row) -> dict:
    uid = row["id"]
    base = f"/redfish/v1/PowerEquipment/UPSs/{uid}"
    resource = {
        "@odata.id": base,
        "@odata.type": "#PowerDistribution.v1_3_2.PowerDistribution",
        "@odata.context": "/redfish/v1/$metadata#PowerDistribution.PowerDistribution",
        "Id": uid,
        "Name": row["name"],
        "EquipmentType": "UPS",
        "Model": row["model"],
        "Manufacturer": row["manufacturer"],
        "SerialNumber": row["serial_number"],
        "FirmwareVersion": row["firmware_version"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "LineInputStatus": row["line_input_status"],
        "RatingVA": row["rating_va"],
        "RatingWatts": row["rating_watts"],
        "BackupEstimatedMinutes": row["battery_runtime_minutes"],
        "Batteries": {
            "ChargePercent": row["battery_charge_percent"],
            "Status": {
                "State": row["battery_status_state"],
                "Health": row["battery_status_health"],
            },
        },
        "Mains": {"@odata.id": f"{base}/Mains"},
        "Outlets": {"@odata.id": f"{base}/Outlets"},
        "Sensors": {"@odata.id": f"{base}/Sensors"},
        "Metrics": {"@odata.id": f"{base}/Metrics"},
    }
    if row["location_info"]:
        resource["Location"] = json.loads(row["location_info"])
    return resource


def _ups_outlet_resource(row, parent_base: str) -> dict:
    oid = row["id"]
    base = f"{parent_base}/Outlets/{oid}"
    return {
        "@odata.id": base,
        "@odata.type": "#Outlet.v1_4_2.Outlet",
        "@odata.context": "/redfish/v1/$metadata#Outlet.Outlet",
        "Id": oid,
        "Name": row["name"],
        "OutletType": row["outlet_type"],
        "PhaseWiringType": row["phase_wiring_type"],
        "PowerState": row["power_state"],
        "RatedCurrentAmps": row["rated_current_amps"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "CurrentAmps": {"Reading": row["current_amps"]},
        "Voltage": {"Reading": row["voltage_volts"]},
        "PowerWatts": {"Reading": row["power_watts"]},
        "EnergykWh": {"Reading": row["energy_kwh"]},
        "PowerFactor": {"Reading": row["power_factor"]},
        "Actions": {
            "#Outlet.PowerControl": {
                "target": f"{base}/Actions/Outlet.PowerControl"
            }
        },
    }


def _ups_circuit_resource(row, parent_base: str) -> dict:
    cid = row["id"]
    return {
        "@odata.id": f"{parent_base}/Mains/{cid}",
        "@odata.type": "#Circuit.v1_6_0.Circuit",
        "@odata.context": "/redfish/v1/$metadata#Circuit.Circuit",
        "Id": cid,
        "Name": row["name"],
        "CircuitType": "Mains",
        "PhaseWiringType": row["phase_wiring_type"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "Voltage": {"Reading": row["voltage_volts"]},
        "CurrentAmps": {"Reading": row["current_amps"]},
        "PowerWatts": {"Reading": row["power_watts"]},
        "EnergykWh": {"Reading": row["energy_kwh"]},
        "PowerFactor": {"Reading": row["power_factor"]},
        "FrequencyHz": {"Reading": row["frequency_hz"]},
    }


def _ups_sensor_resource(row, parent_base: str) -> dict:
    sid = row["id"]
    resource = {
        "@odata.id": f"{parent_base}/Sensors/{sid}",
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
# Aggregate helper
# ---------------------------------------------------------------------------

def _recalculate_ups_aggregates(ups_id: str, db: sqlite3.Connection) -> None:
    agg = db.execute(
        "SELECT COALESCE(SUM(current_amps),0) AS cur, COALESCE(SUM(power_watts),0) AS pwr "
        "FROM ups_outlets WHERE ups_id=?",
        (ups_id,),
    ).fetchone()
    db.execute(
        "UPDATE ups_mains SET current_amps=?, power_watts=? WHERE ups_id=?",
        (agg["cur"], agg["pwr"], ups_id),
    )
    db.execute(
        "UPDATE ups_sensors SET reading=? WHERE ups_id=? AND id='OutputPower'",
        (agg["pwr"], ups_id),
    )


# ---------------------------------------------------------------------------
# UPS Collection
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/PowerEquipment/UPSs")
def upss(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id FROM upss ORDER BY id").fetchall()
    return {
        "@odata.id": "/redfish/v1/PowerEquipment/UPSs",
        "@odata.type": "#PowerDistributionCollection.PowerDistributionCollection",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionCollection.PowerDistributionCollection",
        "Name": "UPS Collection",
        "Members@odata.count": len(rows),
        "Members": [
            {"@odata.id": f"/redfish/v1/PowerEquipment/UPSs/{r['id']}"} for r in rows
        ],
    }


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}")
def ups(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM upss WHERE id=?", (ups_id,)).fetchone()
    if not row:
        return not_found_response(f"UPS {ups_id}")
    return _ups_resource(row)


class UpsPatch(BaseModel):
    model_config = {"extra": "allow"}
    LineInputStatus: Optional[str] = None
    BackupEstimatedMinutes: Optional[float] = None
    Status: Optional[dict] = None
    Batteries: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/UPSs/{ups_id}")
def patch_ups(ups_id: str, body: UpsPatch, background_tasks: BackgroundTasks, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM upss WHERE id=?", (ups_id,)).fetchone()
    if not row:
        return not_found_response(f"UPS {ups_id}")
    updates: dict[str, Any] = {}
    if body.LineInputStatus is not None:
        valid = ("Normal", "OutOfRange", "OutOfPower", "LossOfInput", "OutOfFrequencyRange")
        if body.LineInputStatus not in valid:
            return bad_request_response(f"LineInputStatus must be one of: {', '.join(valid)}")
        updates["line_input_status"] = body.LineInputStatus
    if body.BackupEstimatedMinutes is not None:
        updates["battery_runtime_minutes"] = body.BackupEstimatedMinutes
    if body.Batteries:
        if "ChargePercent" in body.Batteries:
            updates["battery_charge_percent"] = body.Batteries["ChargePercent"]
    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(f"UPDATE upss SET {set_clause} WHERE id=?", (*updates.values(), ups_id))
        db.commit()
        if body.LineInputStatus in ("OutOfPower", "LossOfInput"):
            background_tasks.add_task(
                dispatch_event,
                "Alert",
                f"/redfish/v1/PowerEquipment/UPSs/{ups_id}",
                f"UPS {ups_id} LineInputStatus changed to {body.LineInputStatus}",
                "Critical",
                "Base.1.0.ConditionInRelatedResource",
            )
        elif body.LineInputStatus is not None:
            background_tasks.add_task(
                dispatch_event,
                "StatusChange",
                f"/redfish/v1/PowerEquipment/UPSs/{ups_id}",
                f"UPS {ups_id} LineInputStatus changed to {body.LineInputStatus}",
            )
    row = db.execute("SELECT * FROM upss WHERE id=?", (ups_id,)).fetchone()
    return _ups_resource(row)


# --- UPS Mains ---

@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Mains")
def ups_mains(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM upss WHERE id=?", (ups_id,)).fetchone():
        return not_found_response(f"UPS {ups_id}")
    rows = db.execute("SELECT id FROM ups_mains WHERE ups_id=? ORDER BY id", (ups_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/UPSs/{ups_id}"
    return {
        "@odata.id": f"{base}/Mains",
        "@odata.type": "#CircuitCollection.CircuitCollection",
        "Name": "Mains Circuit Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Mains/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Mains/{circuit_id}")
def ups_main(ups_id: str, circuit_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM ups_mains WHERE ups_id=? AND id=?", (ups_id, circuit_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Main circuit {circuit_id}")
    return _ups_circuit_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


# --- UPS Outlets ---

@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets")
def ups_outlets(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM upss WHERE id=?", (ups_id,)).fetchone():
        return not_found_response(f"UPS {ups_id}")
    rows = db.execute("SELECT id FROM ups_outlets WHERE ups_id=? ORDER BY id", (ups_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/UPSs/{ups_id}"
    return {
        "@odata.id": f"{base}/Outlets",
        "@odata.type": "#OutletCollection.OutletCollection",
        "Name": "Outlet Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Outlets/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets/{outlet_id}")
def ups_outlet(ups_id: str, outlet_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM ups_outlets WHERE ups_id=? AND id=?", (ups_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    return _ups_outlet_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


class UpsOutletPatch(BaseModel):
    PowerState: Optional[str] = None


@router.patch("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets/{outlet_id}")
def patch_ups_outlet(
    ups_id: str,
    outlet_id: str,
    body: UpsOutletPatch,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM ups_outlets WHERE ups_id=? AND id=?", (ups_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    if body.PowerState is not None:
        if body.PowerState not in ("On", "Off"):
            return bad_request_response("PowerState must be 'On' or 'Off'")
        if body.PowerState == "Off":
            voltage, current, power = 0.0, 0.0, 0.0
        else:
            voltage = row["voltage_volts"] or 100.0
            current = row["current_amps"]
            power = row["power_watts"]
        db.execute(
            "UPDATE ups_outlets SET power_state=?, voltage_volts=?, current_amps=?, power_watts=? WHERE ups_id=? AND id=?",
            (body.PowerState, voltage, current, power, ups_id, outlet_id),
        )
        _recalculate_ups_aggregates(ups_id, db)
        db.commit()
        background_tasks.add_task(
            dispatch_event,
            "StatusChange",
            f"/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets/{outlet_id}",
            f"UPS Outlet {outlet_id} PowerState changed to {body.PowerState}",
        )
    row = db.execute(
        "SELECT * FROM ups_outlets WHERE ups_id=? AND id=?", (ups_id, outlet_id)
    ).fetchone()
    return _ups_outlet_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


class UpsOutletPowerControl(BaseModel):
    PowerState: str


@router.post("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets/{outlet_id}/Actions/Outlet.PowerControl")
def ups_outlet_power_control(
    ups_id: str,
    outlet_id: str,
    body: UpsOutletPowerControl,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM ups_outlets WHERE ups_id=? AND id=?", (ups_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    valid_states = ("On", "Off", "PowerCycle", "GracefulShutdown")
    if body.PowerState not in valid_states:
        return bad_request_response(f"PowerState must be one of: {', '.join(valid_states)}")

    if body.PowerState in ("Off", "GracefulShutdown"):
        new_state, voltage, current, power = "Off", 0.0, 0.0, 0.0
    else:
        new_state = "On"
        voltage = row["voltage_volts"] or 100.0
        current = row["current_amps"]
        power = row["power_watts"]

    db.execute(
        "UPDATE ups_outlets SET power_state=?, voltage_volts=?, current_amps=?, power_watts=? WHERE ups_id=? AND id=?",
        (new_state, voltage, current, power, ups_id, outlet_id),
    )
    _recalculate_ups_aggregates(ups_id, db)
    db.commit()
    background_tasks.add_task(
        dispatch_event,
        "StatusChange",
        f"/redfish/v1/PowerEquipment/UPSs/{ups_id}/Outlets/{outlet_id}",
        f"UPS Outlet {outlet_id} PowerState changed to {new_state} via {body.PowerState}",
    )
    row = db.execute(
        "SELECT * FROM ups_outlets WHERE ups_id=? AND id=?", (ups_id, outlet_id)
    ).fetchone()
    return _ups_outlet_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


# --- UPS Sensors ---

@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Sensors")
def ups_sensors(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM upss WHERE id=?", (ups_id,)).fetchone():
        return not_found_response(f"UPS {ups_id}")
    rows = db.execute("SELECT id FROM ups_sensors WHERE ups_id=? ORDER BY id", (ups_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/UPSs/{ups_id}"
    return {
        "@odata.id": f"{base}/Sensors",
        "@odata.type": "#SensorCollection.SensorCollection",
        "Name": "UPS Sensor Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Sensors/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Sensors/{sensor_id}")
def ups_sensor(ups_id: str, sensor_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM ups_sensors WHERE ups_id=? AND id=?", (ups_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    return _ups_sensor_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


class UpsSensorPatch(BaseModel):
    Reading: Optional[float] = None
    Thresholds: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Sensors/{sensor_id}")
def patch_ups_sensor(
    ups_id: str,
    sensor_id: str,
    body: UpsSensorPatch,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM ups_sensors WHERE ups_id=? AND id=?", (ups_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    if body.Reading is not None:
        exceeded, severity, msg = check_threshold(row, body.Reading)
        new_health = severity if exceeded else "OK"
        db.execute(
            "UPDATE ups_sensors SET reading=?, status_health=? WHERE ups_id=? AND id=?",
            (body.Reading, new_health, ups_id, sensor_id),
        )
        db.commit()
        if exceeded:
            background_tasks.add_task(
                dispatch_event,
                "Alert",
                f"/redfish/v1/PowerEquipment/UPSs/{ups_id}/Sensors/{sensor_id}",
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
                f"UPDATE ups_sensors SET {set_clause} WHERE ups_id=? AND id=?",
                (*t_updates.values(), ups_id, sensor_id),
            )
            db.commit()
    row = db.execute(
        "SELECT * FROM ups_sensors WHERE ups_id=? AND id=?", (ups_id, sensor_id)
    ).fetchone()
    return _ups_sensor_resource(row, f"/redfish/v1/PowerEquipment/UPSs/{ups_id}")


# --- UPS Metrics ---

@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/Metrics")
def ups_metrics(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM upss WHERE id=?", (ups_id,)).fetchone()
    if not row:
        return not_found_response(f"UPS {ups_id}")
    base = f"/redfish/v1/PowerEquipment/UPSs/{ups_id}"
    input_p = db.execute(
        "SELECT reading FROM ups_sensors WHERE ups_id=? AND id='InputPower'", (ups_id,)
    ).fetchone()
    output_p = db.execute(
        "SELECT reading FROM ups_sensors WHERE ups_id=? AND id='OutputPower'", (ups_id,)
    ).fetchone()
    return {
        "@odata.id": f"{base}/Metrics",
        "@odata.type": "#PowerDistributionMetrics.v1_3_0.PowerDistributionMetrics",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionMetrics.PowerDistributionMetrics",
        "Id": "Metrics",
        "Name": f"Metrics for UPS {ups_id}",
        "InputPowerWatts": {
            "DataSourceUri": f"{base}/Sensors/InputPower",
            "Reading": input_p["reading"] if input_p else None,
        },
        "OutputPowerWatts": {
            "DataSourceUri": f"{base}/Sensors/OutputPower",
            "Reading": output_p["reading"] if output_p else None,
        },
        "BatteryChargePercent": row["battery_charge_percent"],
        "BackupEstimatedMinutes": row["battery_runtime_minutes"],
    }
