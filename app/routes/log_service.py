import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db
from app.helpers import no_content_response, not_found_response

router = APIRouter()


def _log_service_resource(owner_base: str) -> dict:
    base = f"{owner_base}/LogServices/Log"
    return {
        "@odata.id": base,
        "@odata.type": "#LogService.v1_4_0.LogService",
        "@odata.context": "/redfish/v1/$metadata#LogService.LogService",
        "Id": "Log",
        "Name": "Log Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "Entries": {"@odata.id": f"{base}/Entries"},
        "Actions": {
            "#LogService.ClearLog": {
                "target": f"{base}/Actions/LogService.ClearLog"
            }
        },
    }


def _log_entry_resource(row, owner_base: str) -> dict:
    eid = row["id"]
    resource = {
        "@odata.id": f"{owner_base}/LogServices/Log/Entries/{eid}",
        "@odata.type": "#LogEntry.v1_15_0.LogEntry",
        "@odata.context": "/redfish/v1/$metadata#LogEntry.LogEntry",
        "Id": eid,
        "Name": f"Log Entry {eid}",
        "EntryType": row["entry_type"],
        "Severity": row["severity"],
        "Created": row["created"],
        "Message": row["message"],
    }
    if row["origin_of_condition"]:
        resource["OriginOfCondition"] = {"@odata.id": row["origin_of_condition"]}
    return resource


# ---------------------------------------------------------------------------
# Manager LogService
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/Managers/{manager_id}/LogServices")
def manager_log_services(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM managers WHERE id=?", (manager_id,)).fetchone():
        return not_found_response(f"Manager {manager_id}")
    base = f"/redfish/v1/Managers/{manager_id}"
    return {
        "@odata.id": f"{base}/LogServices",
        "@odata.type": "#LogServiceCollection.LogServiceCollection",
        "@odata.context": "/redfish/v1/$metadata#LogServiceCollection.LogServiceCollection",
        "Name": "Log Service Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": f"{base}/LogServices/Log"}],
    }


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log")
def manager_log_service(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM managers WHERE id=?", (manager_id,)).fetchone():
        return not_found_response(f"Manager {manager_id}")
    return _log_service_resource(f"/redfish/v1/Managers/{manager_id}")


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log/Entries")
def manager_log_entries(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM managers WHERE id=?", (manager_id,)).fetchone():
        return not_found_response(f"Manager {manager_id}")
    rows = db.execute(
        "SELECT id FROM log_entries WHERE owner_type='manager' AND owner_id=? ORDER BY created DESC",
        (manager_id,),
    ).fetchall()
    base = f"/redfish/v1/Managers/{manager_id}/LogServices/Log"
    return {
        "@odata.id": f"{base}/Entries",
        "@odata.type": "#LogEntryCollection.LogEntryCollection",
        "@odata.context": "/redfish/v1/$metadata#LogEntryCollection.LogEntryCollection",
        "Name": "Log Entry Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Entries/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log/Entries/{entry_id}")
def manager_log_entry(manager_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM log_entries WHERE owner_type='manager' AND owner_id=? AND id=?",
        (manager_id, entry_id),
    ).fetchone()
    if not row:
        return not_found_response(f"Log entry {entry_id}")
    return _log_entry_resource(row, f"/redfish/v1/Managers/{manager_id}")


@router.post("/redfish/v1/Managers/{manager_id}/LogServices/Log/Actions/LogService.ClearLog")
def manager_clear_log(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM managers WHERE id=?", (manager_id,)).fetchone():
        return not_found_response(f"Manager {manager_id}")
    db.execute("DELETE FROM log_entries WHERE owner_type='manager' AND owner_id=?", (manager_id,))
    db.commit()
    return no_content_response()


# ---------------------------------------------------------------------------
# Chassis LogService
# ---------------------------------------------------------------------------

@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices")
def chassis_log_services(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    base = f"/redfish/v1/Chassis/{chassis_id}"
    return {
        "@odata.id": f"{base}/LogServices",
        "@odata.type": "#LogServiceCollection.LogServiceCollection",
        "@odata.context": "/redfish/v1/$metadata#LogServiceCollection.LogServiceCollection",
        "Name": "Log Service Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": f"{base}/LogServices/Log"}],
    }


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log")
def chassis_log_service(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    return _log_service_resource(f"/redfish/v1/Chassis/{chassis_id}")


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Entries")
def chassis_log_entries(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    rows = db.execute(
        "SELECT id FROM log_entries WHERE owner_type='chassis' AND owner_id=? ORDER BY created DESC",
        (chassis_id,),
    ).fetchall()
    base = f"/redfish/v1/Chassis/{chassis_id}/LogServices/Log"
    return {
        "@odata.id": f"{base}/Entries",
        "@odata.type": "#LogEntryCollection.LogEntryCollection",
        "@odata.context": "/redfish/v1/$metadata#LogEntryCollection.LogEntryCollection",
        "Name": "Log Entry Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"{base}/Entries/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Entries/{entry_id}")
def chassis_log_entry(chassis_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM log_entries WHERE owner_type='chassis' AND owner_id=? AND id=?",
        (chassis_id, entry_id),
    ).fetchone()
    if not row:
        return not_found_response(f"Log entry {entry_id}")
    return _log_entry_resource(row, f"/redfish/v1/Chassis/{chassis_id}")


@router.post("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Actions/LogService.ClearLog")
def chassis_clear_log(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM chassis WHERE id=?", (chassis_id,)).fetchone():
        return not_found_response(f"Chassis {chassis_id}")
    db.execute("DELETE FROM log_entries WHERE owner_type='chassis' AND owner_id=?", (chassis_id,))
    db.commit()
    return no_content_response()
