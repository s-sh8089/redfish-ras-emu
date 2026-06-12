import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from app.database import get_db
from app.helpers import (
    bad_request_response,
    check_etag,
    compute_etag,
    no_content_response,
    not_found_response,
    odata_pagination,
    precondition_failed_response,
)

router = APIRouter()

_OWNER_TABLE = {
    'manager': 'managers',
    'chassis': 'chassis',
    'pdu':     'rack_pdus',
    'ups':     'upss',
}

_OWNER_BASE_URL = {
    'manager': '/redfish/v1/Managers',
    'chassis': '/redfish/v1/Chassis',
    'pdu':     '/redfish/v1/PowerEquipment/RackPDUs',
    'ups':     '/redfish/v1/PowerEquipment/UPSs',
}

_VALID_OVERWRITE_POLICIES = ("WrapsWhenFull", "NeverOverWrites")


# ──── shared helpers ─────────────────────────────────────────────────────────

def _check_owner(owner_type: str, owner_id: str, db: sqlite3.Connection) -> bool:
    table = _OWNER_TABLE[owner_type]
    return db.execute(f"SELECT 1 FROM {table} WHERE id=?", (owner_id,)).fetchone() is not None


def _owner_base(owner_type: str, owner_id: str) -> str:
    return f"{_OWNER_BASE_URL[owner_type]}/{owner_id}"


def _log_service_resource(owner_type: str, owner_id: str, db: sqlite3.Connection) -> dict:
    base = f"{_owner_base(owner_type, owner_id)}/LogServices/Log"
    ls_row = db.execute(
        "SELECT max_number_of_records, overwrite_policy FROM log_services WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchone()
    max_records = ls_row["max_number_of_records"] if ls_row else 1000
    overwrite_policy = ls_row["overwrite_policy"] if ls_row else "WrapsWhenFull"
    return {
        "@odata.id": base,
        "@odata.type": "#LogService.v1_4_0.LogService",
        "@odata.context": "/redfish/v1/$metadata#LogService.LogService",
        "Id": "Log",
        "Name": "Log Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "MaxNumberOfRecords": max_records,
        "OverWritePolicy": overwrite_policy,
        "Entries": {"@odata.id": f"{base}/Entries"},
        "Actions": {
            "#LogService.ClearLog": {"target": f"{base}/Actions/LogService.ClearLog"}
        },
    }


def _log_entry_resource(row, owner_type: str, owner_id: str) -> dict:
    eid = row["id"]
    base = _owner_base(owner_type, owner_id)
    resource = {
        "@odata.id": f"{base}/LogServices/Log/Entries/{eid}",
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


def _get_log_services_collection(owner_type: str, owner_id: str, db: sqlite3.Connection):
    if not _check_owner(owner_type, owner_id, db):
        return not_found_response(f"{owner_type.capitalize()} {owner_id}")
    base = _owner_base(owner_type, owner_id)
    return {
        "@odata.id": f"{base}/LogServices",
        "@odata.type": "#LogServiceCollection.LogServiceCollection",
        "@odata.context": "/redfish/v1/$metadata#LogServiceCollection.LogServiceCollection",
        "Name": "Log Service Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": f"{base}/LogServices/Log"}],
    }


def _get_log_service(owner_type: str, owner_id: str, response: Response, db: sqlite3.Connection):
    if not _check_owner(owner_type, owner_id, db):
        return not_found_response(f"{owner_type.capitalize()} {owner_id}")
    data = _log_service_resource(owner_type, owner_id, db)
    response.headers["ETag"] = f'"{compute_etag(data)}"'
    return data


class LogServicePatch(BaseModel):
    MaxNumberOfRecords: Optional[int] = None
    OverWritePolicy: Optional[str] = None


def _patch_log_service(owner_type: str, owner_id: str, body: LogServicePatch, request: Request, db: sqlite3.Connection):
    if not _check_owner(owner_type, owner_id, db):
        return not_found_response(f"{owner_type.capitalize()} {owner_id}")

    current = _log_service_resource(owner_type, owner_id, db)
    if not check_etag(request.headers.get("If-Match"), compute_etag(current)):
        return precondition_failed_response()

    if body.OverWritePolicy is not None and body.OverWritePolicy not in _VALID_OVERWRITE_POLICIES:
        return bad_request_response(f"OverWritePolicy must be one of: {', '.join(_VALID_OVERWRITE_POLICIES)}")
    if body.MaxNumberOfRecords is not None and body.MaxNumberOfRecords < 0:
        return bad_request_response("MaxNumberOfRecords must be >= 0")

    updates = {}
    if body.MaxNumberOfRecords is not None:
        updates["max_number_of_records"] = body.MaxNumberOfRecords
    if body.OverWritePolicy is not None:
        updates["overwrite_policy"] = body.OverWritePolicy

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(
            f"UPDATE log_services SET {set_clause} WHERE owner_type=? AND owner_id=?",
            (*updates.values(), owner_type, owner_id),
        )
        db.commit()

    return _log_service_resource(owner_type, owner_id, db)


def _get_log_entries(owner_type: str, owner_id: str, top, skip, db: sqlite3.Connection):
    if not _check_owner(owner_type, owner_id, db):
        return not_found_response(f"{owner_type.capitalize()} {owner_id}")
    base = f"{_owner_base(owner_type, owner_id)}/LogServices/Log"
    total = db.execute(
        "SELECT COUNT(*) FROM log_entries WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{base}/Entries")
    rows = db.execute(
        "SELECT id FROM log_entries WHERE owner_type=? AND owner_id=? ORDER BY created DESC LIMIT ? OFFSET ?",
        (owner_type, owner_id, limit, offset),
    ).fetchall()
    result = {
        "@odata.id": f"{base}/Entries",
        "@odata.type": "#LogEntryCollection.LogEntryCollection",
        "@odata.context": "/redfish/v1/$metadata#LogEntryCollection.LogEntryCollection",
        "Name": "Log Entry Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{base}/Entries/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


def _get_log_entry(owner_type: str, owner_id: str, entry_id: str, db: sqlite3.Connection):
    row = db.execute(
        "SELECT * FROM log_entries WHERE owner_type=? AND owner_id=? AND id=?",
        (owner_type, owner_id, entry_id),
    ).fetchone()
    if not row:
        return not_found_response(f"Log entry {entry_id}")
    return _log_entry_resource(row, owner_type, owner_id)


def _delete_log_entry(owner_type: str, owner_id: str, entry_id: str, db: sqlite3.Connection):
    if not db.execute(
        "SELECT 1 FROM log_entries WHERE owner_type=? AND owner_id=? AND id=?",
        (owner_type, owner_id, entry_id),
    ).fetchone():
        return not_found_response(f"Log entry {entry_id}")
    db.execute(
        "DELETE FROM log_entries WHERE owner_type=? AND owner_id=? AND id=?",
        (owner_type, owner_id, entry_id),
    )
    db.commit()
    return no_content_response()


def _clear_log(owner_type: str, owner_id: str, db: sqlite3.Connection):
    if not _check_owner(owner_type, owner_id, db):
        return not_found_response(f"{owner_type.capitalize()} {owner_id}")
    db.execute(
        "DELETE FROM log_entries WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    )
    db.commit()
    return no_content_response()


# ──── Manager LogService ─────────────────────────────────────────────────────

@router.get("/redfish/v1/Managers/{manager_id}/LogServices")
def manager_log_services(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_services_collection('manager', manager_id, db)


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log")
def manager_log_service(manager_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_service('manager', manager_id, response, db)


@router.patch("/redfish/v1/Managers/{manager_id}/LogServices/Log")
def patch_manager_log_service(manager_id: str, body: LogServicePatch, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return _patch_log_service('manager', manager_id, body, request, db)


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log/Entries")
def manager_log_entries(
    manager_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    return _get_log_entries('manager', manager_id, top, skip, db)


@router.get("/redfish/v1/Managers/{manager_id}/LogServices/Log/Entries/{entry_id}")
def manager_log_entry(manager_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_entry('manager', manager_id, entry_id, db)


@router.delete("/redfish/v1/Managers/{manager_id}/LogServices/Log/Entries/{entry_id}")
def delete_manager_log_entry(manager_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _delete_log_entry('manager', manager_id, entry_id, db)


@router.post("/redfish/v1/Managers/{manager_id}/LogServices/Log/Actions/LogService.ClearLog")
def manager_clear_log(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _clear_log('manager', manager_id, db)


# ──── Chassis LogService ─────────────────────────────────────────────────────

@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices")
def chassis_log_services(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_services_collection('chassis', chassis_id, db)


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log")
def chassis_log_service(chassis_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_service('chassis', chassis_id, response, db)


@router.patch("/redfish/v1/Chassis/{chassis_id}/LogServices/Log")
def patch_chassis_log_service(chassis_id: str, body: LogServicePatch, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return _patch_log_service('chassis', chassis_id, body, request, db)


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Entries")
def chassis_log_entries(
    chassis_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    return _get_log_entries('chassis', chassis_id, top, skip, db)


@router.get("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Entries/{entry_id}")
def chassis_log_entry(chassis_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_entry('chassis', chassis_id, entry_id, db)


@router.delete("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Entries/{entry_id}")
def delete_chassis_log_entry(chassis_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _delete_log_entry('chassis', chassis_id, entry_id, db)


@router.post("/redfish/v1/Chassis/{chassis_id}/LogServices/Log/Actions/LogService.ClearLog")
def chassis_clear_log(chassis_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _clear_log('chassis', chassis_id, db)


# ──── PDU LogService ─────────────────────────────────────────────────────────

@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices")
def pdu_log_services(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_services_collection('pdu', pdu_id, db)


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log")
def pdu_log_service(pdu_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_service('pdu', pdu_id, response, db)


@router.patch("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log")
def patch_pdu_log_service(pdu_id: str, body: LogServicePatch, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return _patch_log_service('pdu', pdu_id, body, request, db)


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log/Entries")
def pdu_log_entries(
    pdu_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    return _get_log_entries('pdu', pdu_id, top, skip, db)


@router.get("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log/Entries/{entry_id}")
def pdu_log_entry(pdu_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_entry('pdu', pdu_id, entry_id, db)


@router.delete("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log/Entries/{entry_id}")
def delete_pdu_log_entry(pdu_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _delete_log_entry('pdu', pdu_id, entry_id, db)


@router.post("/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/LogServices/Log/Actions/LogService.ClearLog")
def pdu_clear_log(pdu_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _clear_log('pdu', pdu_id, db)


# ──── UPS LogService ─────────────────────────────────────────────────────────

@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices")
def ups_log_services(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_services_collection('ups', ups_id, db)


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log")
def ups_log_service(ups_id: str, response: Response, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_service('ups', ups_id, response, db)


@router.patch("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log")
def patch_ups_log_service(ups_id: str, body: LogServicePatch, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return _patch_log_service('ups', ups_id, body, request, db)


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log/Entries")
def ups_log_entries(
    ups_id: str,
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    return _get_log_entries('ups', ups_id, top, skip, db)


@router.get("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log/Entries/{entry_id}")
def ups_log_entry(ups_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _get_log_entry('ups', ups_id, entry_id, db)


@router.delete("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log/Entries/{entry_id}")
def delete_ups_log_entry(ups_id: str, entry_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _delete_log_entry('ups', ups_id, entry_id, db)


@router.post("/redfish/v1/PowerEquipment/UPSs/{ups_id}/LogServices/Log/Actions/LogService.ClearLog")
def ups_clear_log(ups_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _clear_log('ups', ups_id, db)
