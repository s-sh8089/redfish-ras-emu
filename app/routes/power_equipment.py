import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import config
from app.database import get_db
from app.event_dispatcher import check_threshold, dispatch_event
from app.helpers import (
    bad_request_response,
    check_etag,
    compute_etag,
    not_found_response,
    odata_pagination,
    precondition_failed_response,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _pdu_resource(row, db: sqlite3.Connection) -> dict:
    pid = row["id"]
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pid}"
    resource = {
        "@odata.id": base,
        "@odata.type": "#PowerDistribution.v1_3_2.PowerDistribution",
        "@odata.context": "/redfish/v1/$metadata#PowerDistribution.PowerDistribution",
        "Id": pid,
        "Name": row["name"],
        "EquipmentType": "RackPDU",
        "Model": row["model"],
        "Manufacturer": row["manufacturer"],
        "SerialNumber": row["serial_number"],
        "FirmwareVersion": row["firmware_version"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "RatedCurrentAmps": row["rated_current_amps"],
        "RatedVoltageVolts": row["rated_voltage_volts"],
        "RatedFrequencyHz": row["rated_frequency_hz"],
        "Mains": {"@odata.id": f"{base}/Mains"},
        "Branches": {"@odata.id": f"{base}/Branches"},
        "Outlets": {"@odata.id": f"{base}/Outlets"},
        "Sensors": {"@odata.id": f"{base}/Sensors"},
        "Metrics": {"@odata.id": f"{base}/Metrics"},
    }
    if row["location_info"]:
        resource["Location"] = json.loads(row["location_info"])
    return resource


def _outlet_resource(row, parent_base: str) -> dict:
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
        "FrequencyHz": {"Reading": row["frequency_hz"]},
        "Actions": {
            "#Outlet.PowerControl": {
                "target": f"{base}/Actions/Outlet.PowerControl"
            }
        },
    }


def _circuit_resource(row, parent_base: str, circuit_type: str) -> dict:
    cid = row["id"]
    base = f"{parent_base}/{circuit_type}/{cid}"
    resource = {
        "@odata.id": base,
        "@odata.type": "#Circuit.v1_6_0.Circuit",
        "@odata.context": "/redfish/v1/$metadata#Circuit.Circuit",
        "Id": cid,
        "Name": row["name"],
        "CircuitType": "Mains" if circuit_type == "Mains" else "Branch",
        "PhaseWiringType": row["phase_wiring_type"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "CurrentAmps": {"Reading": row["current_amps"]},
        "PowerWatts": {"Reading": row["power_watts"]},
        "EnergykWh": {"Reading": row["energy_kwh"]},
        "PowerFactor": {"Reading": row["power_factor"]},
    }
    keys = row.keys()
    if "voltage_volts" in keys:
        resource["Voltage"] = {"Reading": row["voltage_volts"]}
    if "frequency_hz" in keys:
        resource["FrequencyHz"] = {"Reading": row["frequency_hz"]}
    if "rated_current_amps" in keys and row["rated_current_amps"] is not None:
        resource["RatedCurrentAmps"] = row["rated_current_amps"]
    return resource


def _sensor_resource(row, parent_base: str) -> dict:
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
# Aggregate helpers
# ---------------------------------------------------------------------------

def _recalculate_pdu_aggregates(pdu_id: str, db: sqlite3.Connection) -> None:
    branch_ids = [
        r["branch_id"]
        for r in db.execute(
            "SELECT DISTINCT branch_id FROM pdu_outlets WHERE pdu_id=? AND branch_id IS NOT NULL",
            (pdu_id,),
        ).fetchall()
    ]
    for bid in branch_ids:
        agg = db.execute(
            "SELECT COALESCE(SUM(current_amps),0) AS cur, COALESCE(SUM(power_watts),0) AS pwr "
            "FROM pdu_outlets WHERE pdu_id=? AND branch_id=?",
            (pdu_id, bid),
        ).fetchone()
        db.execute(
            "UPDATE pdu_branches SET current_amps=?, power_watts=? WHERE pdu_id=? AND id=?",
            (agg["cur"], agg["pwr"], pdu_id, bid),
        )
    main_agg = db.execute(
        "SELECT COALESCE(SUM(current_amps),0) AS cur, COALESCE(SUM(power_watts),0) AS pwr "
        "FROM pdu_branches WHERE pdu_id=?",
        (pdu_id,),
    ).fetchone()
    db.execute(
        "UPDATE pdu_mains SET current_amps=?, power_watts=? WHERE pdu_id=?",
        (main_agg["cur"], main_agg["pwr"], pdu_id),
    )
    db.execute(
        "UPDATE pdu_sensors SET reading=? WHERE pdu_id=? AND reading_type='Current'",
        (main_agg["cur"], pdu_id),
    )
    db.execute(
        "UPDATE pdu_sensors SET reading=? WHERE pdu_id=? AND reading_type='Power'",
        (main_agg["pwr"], pdu_id),
    )


# ---------------------------------------------------------------------------
# Background tasks for async power operations
# ---------------------------------------------------------------------------

def _do_power_cycle_task(task_id: str, pdu_id: str, outlet_id: str) -> None:
    time.sleep(5)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE pdu_outlets SET power_state='On', voltage_volts=100.0 WHERE pdu_id=? AND id=?",
            (pdu_id, outlet_id),
        )
        _recalculate_pdu_aggregates(pdu_id, conn)
        conn.execute(
            "UPDATE tasks SET task_state='Completed', end_time=? WHERE id=?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), task_id),
        )
        conn.commit()
    finally:
        conn.close()
    dispatch_event(
        "StatusChange",
        f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}",
        f"Outlet {outlet_id} PowerCycle completed",
    )


def _do_graceful_shutdown_task(task_id: str, pdu_id: str, outlet_id: str) -> None:
    time.sleep(3)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE pdu_outlets SET power_state='Off', voltage_volts=0.0, current_amps=0.0, power_watts=0.0 WHERE pdu_id=? AND id=?",
            (pdu_id, outlet_id),
        )
        _recalculate_pdu_aggregates(pdu_id, conn)
        conn.execute(
            "UPDATE tasks SET task_state='Completed', end_time=? WHERE id=?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), task_id),
        )
        conn.commit()
    finally:
        conn.close()
    dispatch_event(
        "StatusChange",
        f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}",
        f"Outlet {outlet_id} GracefulShutdown completed",
    )


# ---------------------------------------------------------------------------
# PowerEquipment
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/PowerEquipment")
@router.get("/redfish/v1/PowerEquipment/")
def power_equipment():
    return {
        "@odata.id": "/redfish/v1/PowerEquipment",
        "@odata.type": "#PowerEquipment.v1_2_1.PowerEquipment",
        "@odata.context": "/redfish/v1/$metadata#PowerEquipment.PowerEquipment",
        "Id": "PowerEquipment",
        "Name": "Power Equipment",
        "RackPDUs": {"@odata.id": "/redfish/v1/PowerEquipment/RackPDUs"},
        "UPSs": {"@odata.id": "/redfish/v1/PowerEquipment/UPSs"},
        "FloorPDUs": {"@odata.id": "/redfish/v1/PowerEquipment/FloorPDUs"},
        "PowerShelves": {"@odata.id": "/redfish/v1/PowerEquipment/PowerShelves"},
        "Status": {"State": "Enabled", "Health": "OK"},
    }


# ---------------------------------------------------------------------------
# RackPDUs
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/PowerEquipment/RackPDUs")
def rack_pdus(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM rack_pdus").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, "/redfish/v1/PowerEquipment/RackPDUs")
    rows = db.execute("SELECT id FROM rack_pdus ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    result = {
        "@odata.id": "/redfish/v1/PowerEquipment/RackPDUs",
        "@odata.type": "#PowerDistributionCollection.PowerDistributionCollection",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionCollection.PowerDistributionCollection",
        "Name": "Rack PDU Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"/redfish/v1/PowerEquipment/RackPDUs/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
def rack_pdu(pdu_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    if not row:
        return not_found_response(f"RackPDU {pdu_id}")
    resource = _pdu_resource(row, db)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class PduPatch(BaseModel):
    model_config = {"extra": "allow"}
    Status: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
def patch_rack_pdu(
    pdu_id: str,
    body: PduPatch,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    if not row:
        return not_found_response(f"RackPDU {pdu_id}")
    if not check_etag(request.headers.get("If-Match"), compute_etag(_pdu_resource(row, db))):
        return precondition_failed_response()
    if body.Status:
        state = body.Status.get("State", row["status_state"])
        health = body.Status.get("Health", row["status_health"])
        db.execute(
            "UPDATE rack_pdus SET status_state=?, status_health=? WHERE id=?",
            (state, health, pdu_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    resource = _pdu_resource(row, db)
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


# --- PDU Mains ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Mains")
def pdu_mains(
    pdu_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    total = db.execute("SELECT COUNT(*) FROM pdu_mains WHERE pdu_id=?", (pdu_id,)).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{base}/Mains")
    rows = db.execute("SELECT id FROM pdu_mains WHERE pdu_id=? ORDER BY id LIMIT ? OFFSET ?", (pdu_id, limit, offset)).fetchall()
    result = {
        "@odata.id": f"{base}/Mains",
        "@odata.type": "#CircuitCollection.CircuitCollection",
        "Name": "Mains Circuit Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{base}/Mains/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Mains/{circuit_id}")
def pdu_main(pdu_id: str, circuit_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_mains WHERE pdu_id=? AND id=?", (pdu_id, circuit_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Main circuit {circuit_id}")
    return _circuit_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}", "Mains")


# --- PDU Branches ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Branches")
def pdu_branches(
    pdu_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    total = db.execute("SELECT COUNT(*) FROM pdu_branches WHERE pdu_id=?", (pdu_id,)).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{base}/Branches")
    rows = db.execute("SELECT id FROM pdu_branches WHERE pdu_id=? ORDER BY id LIMIT ? OFFSET ?", (pdu_id, limit, offset)).fetchall()
    result = {
        "@odata.id": f"{base}/Branches",
        "@odata.type": "#CircuitCollection.CircuitCollection",
        "Name": "Branch Circuit Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{base}/Branches/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Branches/{circuit_id}")
def pdu_branch(pdu_id: str, circuit_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_branches WHERE pdu_id=? AND id=?", (pdu_id, circuit_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Branch circuit {circuit_id}")
    return _circuit_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}", "Branches")


# --- PDU Outlets ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets")
def pdu_outlets(
    pdu_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    total = db.execute("SELECT COUNT(*) FROM pdu_outlets WHERE pdu_id=?", (pdu_id,)).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{base}/Outlets")
    rows = db.execute("SELECT id FROM pdu_outlets WHERE pdu_id=? ORDER BY id LIMIT ? OFFSET ?", (pdu_id, limit, offset)).fetchall()
    result = {
        "@odata.id": f"{base}/Outlets",
        "@odata.type": "#OutletCollection.OutletCollection",
        "Name": "Outlet Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{base}/Outlets/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}")
def pdu_outlet(pdu_id: str, outlet_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    resource = _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class OutletPatch(BaseModel):
    PowerState: Optional[str] = None
    Status: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}")
def patch_pdu_outlet(
    pdu_id: str,
    outlet_id: str,
    body: OutletPatch,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    if not check_etag(
        request.headers.get("If-Match"),
        compute_etag(_outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")),
    ):
        return precondition_failed_response()
    if body.PowerState is not None:
        if body.PowerState not in ("On", "Off"):
            return bad_request_response("PowerState must be 'On' or 'Off'")
        voltage = row["voltage_volts"] if body.PowerState == "On" else 0.0
        current = row["current_amps"] if body.PowerState == "On" else 0.0
        power = row["power_watts"] if body.PowerState == "On" else 0.0
        if body.PowerState == "On" and row["power_state"] == "Off":
            voltage = 100.0
        db.execute(
            "UPDATE pdu_outlets SET power_state=?, voltage_volts=?, current_amps=?, power_watts=? WHERE pdu_id=? AND id=?",
            (body.PowerState, voltage, current, power, pdu_id, outlet_id),
        )
        _recalculate_pdu_aggregates(pdu_id, db)
        db.commit()
        background_tasks.add_task(
            dispatch_event,
            "StatusChange",
            f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}",
            f"Outlet {outlet_id} PowerState changed to {body.PowerState}",
        )
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    resource = _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class PowerControlBody(BaseModel):
    PowerState: str


@router.post("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}/Actions/Outlet.PowerControl")
def pdu_outlet_power_control(
    pdu_id: str,
    outlet_id: str,
    body: PowerControlBody,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    valid_states = ("On", "Off", "PowerCycle", "GracefulShutdown")
    if body.PowerState not in valid_states:
        return bad_request_response(f"PowerState must be one of: {', '.join(valid_states)}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    task_id = str(uuid.uuid4())[:8]
    target_uri = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}"

    if body.PowerState == "PowerCycle":
        db.execute(
            "UPDATE pdu_outlets SET power_state='Off', voltage_volts=0.0, current_amps=0.0, power_watts=0.0 WHERE pdu_id=? AND id=?",
            (pdu_id, outlet_id),
        )
        _recalculate_pdu_aggregates(pdu_id, db)
        db.execute(
            "INSERT INTO tasks (id, name, task_state, task_status, start_time, target_uri) VALUES (?,?,?,?,?,?)",
            (task_id, f"Power Cycle Outlet {outlet_id}", "Running", "OK", now, target_uri),
        )
        db.commit()
        background_tasks.add_task(_do_power_cycle_task, task_id, pdu_id, outlet_id)
        return JSONResponse(
            status_code=202,
            content={"@odata.id": f"/redfish/v1/TaskService/Tasks/{task_id}"},
            headers={"Location": f"/redfish/v1/TaskService/Tasks/{task_id}"},
        )

    if body.PowerState == "GracefulShutdown":
        db.execute(
            "INSERT INTO tasks (id, name, task_state, task_status, start_time, target_uri) VALUES (?,?,?,?,?,?)",
            (task_id, f"Graceful Shutdown Outlet {outlet_id}", "Running", "OK", now, target_uri),
        )
        db.commit()
        background_tasks.add_task(_do_graceful_shutdown_task, task_id, pdu_id, outlet_id)
        return JSONResponse(
            status_code=202,
            content={"@odata.id": f"/redfish/v1/TaskService/Tasks/{task_id}"},
            headers={"Location": f"/redfish/v1/TaskService/Tasks/{task_id}"},
        )

    new_state = "On" if body.PowerState == "On" else "Off"
    voltage = 100.0 if new_state == "On" else 0.0
    current = row["current_amps"] if new_state == "On" else 0.0
    power = row["power_watts"] if new_state == "On" else 0.0
    db.execute(
        "UPDATE pdu_outlets SET power_state=?, voltage_volts=?, current_amps=?, power_watts=? WHERE pdu_id=? AND id=?",
        (new_state, voltage, current, power, pdu_id, outlet_id),
    )
    _recalculate_pdu_aggregates(pdu_id, db)
    db.commit()
    background_tasks.add_task(
        dispatch_event,
        "StatusChange",
        target_uri,
        f"Outlet {outlet_id} PowerState changed to {new_state}",
    )
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    return _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


# --- PDU Sensors ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors")
def pdu_sensors(
    pdu_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    total = db.execute("SELECT COUNT(*) FROM pdu_sensors WHERE pdu_id=?", (pdu_id,)).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{base}/Sensors")
    rows = db.execute("SELECT id FROM pdu_sensors WHERE pdu_id=? ORDER BY id LIMIT ? OFFSET ?", (pdu_id, limit, offset)).fetchall()
    result = {
        "@odata.id": f"{base}/Sensors",
        "@odata.type": "#SensorCollection.SensorCollection",
        "Name": "PDU Sensor Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{base}/Sensors/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors/{sensor_id}")
def pdu_sensor(pdu_id: str, sensor_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_sensors WHERE pdu_id=? AND id=?", (pdu_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    resource = _sensor_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


class SensorPatch(BaseModel):
    Reading: Optional[float] = None
    Status: Optional[dict] = None
    Thresholds: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors/{sensor_id}")
def patch_pdu_sensor(
    pdu_id: str,
    sensor_id: str,
    body: SensorPatch,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM pdu_sensors WHERE pdu_id=? AND id=?", (pdu_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    if not check_etag(
        request.headers.get("If-Match"),
        compute_etag(_sensor_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")),
    ):
        return precondition_failed_response()
    if body.Reading is not None:
        exceeded, severity, msg = check_threshold(row, body.Reading)
        new_health = severity if exceeded else "OK"
        db.execute(
            "UPDATE pdu_sensors SET reading=?, status_health=? WHERE pdu_id=? AND id=?",
            (body.Reading, new_health, pdu_id, sensor_id),
        )
        db.commit()
        if exceeded:
            background_tasks.add_task(
                dispatch_event,
                "Alert",
                f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors/{sensor_id}",
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
                f"UPDATE pdu_sensors SET {set_clause} WHERE pdu_id=? AND id=?",
                (*t_updates.values(), pdu_id, sensor_id),
            )
            db.commit()
    row = db.execute(
        "SELECT * FROM pdu_sensors WHERE pdu_id=? AND id=?", (pdu_id, sensor_id)
    ).fetchone()
    resource = _sensor_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
    response.headers["ETag"] = f'"{compute_etag(resource)}"'
    return resource


# --- PDU Metrics ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Metrics")
def pdu_metrics(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    power = db.execute(
        "SELECT reading FROM pdu_sensors WHERE pdu_id=? AND reading_type='Power' LIMIT 1", (pdu_id,)
    ).fetchone()
    energy = db.execute(
        "SELECT reading FROM pdu_sensors WHERE pdu_id=? AND reading_type='EnergykWh' LIMIT 1", (pdu_id,)
    ).fetchone()
    return {
        "@odata.id": f"{base}/Metrics",
        "@odata.type": "#PowerDistributionMetrics.v1_3_0.PowerDistributionMetrics",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionMetrics.PowerDistributionMetrics",
        "Id": "Metrics",
        "Name": f"Metrics for RackPDU {pdu_id}",
        "PowerWatts": {
            "DataSourceUri": f"{base}/Sensors/Power1",
            "Reading": power["reading"] if power else None,
        },
        "EnergykWh": {
            "DataSourceUri": f"{base}/Sensors/Energy1",
            "Reading": energy["reading"] if energy else None,
        },
    }


# ---------------------------------------------------------------------------
# FloorPDUs / PowerShelves (stub)
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/PowerEquipment/FloorPDUs")
def floor_pdus():
    return {
        "@odata.id": "/redfish/v1/PowerEquipment/FloorPDUs",
        "@odata.type": "#PowerDistributionCollection.PowerDistributionCollection",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionCollection.PowerDistributionCollection",
        "Name": "Floor PDU Collection",
        "Members@odata.count": 0,
        "Members": [],
    }


@router.get("/redfish/v1/PowerEquipment/PowerShelves")
def power_shelves():
    return {
        "@odata.id": "/redfish/v1/PowerEquipment/PowerShelves",
        "@odata.type": "#PowerDistributionCollection.PowerDistributionCollection",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionCollection.PowerDistributionCollection",
        "Name": "Power Shelf Collection",
        "Members@odata.count": 0,
        "Members": [],
    }
