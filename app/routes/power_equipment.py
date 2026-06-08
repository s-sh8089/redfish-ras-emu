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
def rack_pdus(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id FROM rack_pdus ORDER BY id").fetchall()
    return {
        "@odata.id": "/redfish/v1/PowerEquipment/RackPDUs",
        "@odata.type": "#PowerDistributionCollection.PowerDistributionCollection",
        "@odata.context": "/redfish/v1/$metadata#PowerDistributionCollection.PowerDistributionCollection",
        "Name": "Rack PDU Collection",
        "Members@odata.count": len(rows),
        "Members": [
            {"@odata.id": f"/redfish/v1/PowerEquipment/RackPDUs/{r['id']}"} for r in rows
        ],
    }


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
def rack_pdu(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    if not row:
        return not_found_response(f"RackPDU {pdu_id}")
    return _pdu_resource(row, db)


class PduPatch(BaseModel):
    model_config = {"extra": "allow"}
    Status: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")
def patch_rack_pdu(pdu_id: str, body: PduPatch, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    if not row:
        return not_found_response(f"RackPDU {pdu_id}")
    if body.Status:
        state = body.Status.get("State", row["status_state"])
        health = body.Status.get("Health", row["status_health"])
        db.execute(
            "UPDATE rack_pdus SET status_state=?, status_health=? WHERE id=?",
            (state, health, pdu_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone()
    return _pdu_resource(row, db)


# --- PDU Mains ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Mains")
def pdu_mains(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    rows = db.execute("SELECT id FROM pdu_mains WHERE pdu_id=? ORDER BY id", (pdu_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    return {
        "@odata.id": f"{base}/Mains",
        "@odata.type": "#CircuitCollection.CircuitCollection",
        "Name": "Mains Circuit Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Mains/{r['id']}"} for r in rows],
    }


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
def pdu_branches(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    rows = db.execute("SELECT id FROM pdu_branches WHERE pdu_id=? ORDER BY id", (pdu_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    return {
        "@odata.id": f"{base}/Branches",
        "@odata.type": "#CircuitCollection.CircuitCollection",
        "Name": "Branch Circuit Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Branches/{r['id']}"} for r in rows],
    }


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
def pdu_outlets(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    rows = db.execute("SELECT id FROM pdu_outlets WHERE pdu_id=? ORDER BY id", (pdu_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    return {
        "@odata.id": f"{base}/Outlets",
        "@odata.type": "#OutletCollection.OutletCollection",
        "Name": "Outlet Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Outlets/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}")
def pdu_outlet(pdu_id: str, outlet_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
    return _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


class OutletPatch(BaseModel):
    PowerState: Optional[str] = None
    Status: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}")
def patch_pdu_outlet(
    pdu_id: str,
    outlet_id: str,
    body: OutletPatch,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Outlet {outlet_id}")
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
    return _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


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

    if body.PowerState in ("Off", "GracefulShutdown"):
        new_state = "Off"
        voltage, current, power = 0.0, 0.0, 0.0
    elif body.PowerState == "PowerCycle":
        new_state = "On"
        voltage = 100.0
        current = row["current_amps"]
        power = row["power_watts"]
    else:
        new_state = "On"
        voltage = 100.0
        current = row["current_amps"]
        power = row["power_watts"]

    db.execute(
        "UPDATE pdu_outlets SET power_state=?, voltage_volts=?, current_amps=?, power_watts=? WHERE pdu_id=? AND id=?",
        (new_state, voltage, current, power, pdu_id, outlet_id),
    )
    db.commit()
    background_tasks.add_task(
        dispatch_event,
        "StatusChange",
        f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Outlets/{outlet_id}",
        f"Outlet {outlet_id} PowerState changed to {new_state} via {body.PowerState}",
    )
    row = db.execute(
        "SELECT * FROM pdu_outlets WHERE pdu_id=? AND id=?", (pdu_id, outlet_id)
    ).fetchone()
    return _outlet_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


# --- PDU Sensors ---

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors")
def pdu_sensors(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM rack_pdus WHERE id=?", (pdu_id,)).fetchone():
        return not_found_response(f"RackPDU {pdu_id}")
    rows = db.execute("SELECT id FROM pdu_sensors WHERE pdu_id=? ORDER BY id", (pdu_id,)).fetchall()
    base = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}"
    return {
        "@odata.id": f"{base}/Sensors",
        "@odata.type": "#SensorCollection.SensorCollection",
        "Name": "PDU Sensor Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Sensors/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors/{sensor_id}")
def pdu_sensor(pdu_id: str, sensor_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM pdu_sensors WHERE pdu_id=? AND id=?", (pdu_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    return _sensor_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


class SensorPatch(BaseModel):
    Reading: Optional[float] = None
    Status: Optional[dict] = None
    Thresholds: Optional[dict] = None


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/Sensors/{sensor_id}")
def patch_pdu_sensor(
    pdu_id: str,
    sensor_id: str,
    body: SensorPatch,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM pdu_sensors WHERE pdu_id=? AND id=?", (pdu_id, sensor_id)
    ).fetchone()
    if not row:
        return not_found_response(f"Sensor {sensor_id}")
    if body.Reading is not None:
        exceeded, severity, msg = check_threshold(row, body.Reading)
        db.execute(
            "UPDATE pdu_sensors SET reading=? WHERE pdu_id=? AND id=?",
            (body.Reading, pdu_id, sensor_id),
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
    return _sensor_resource(row, f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}")


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
# FloorPDUs / PowerShelves (stub — no floor PDUs or power shelves in this emu)
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
