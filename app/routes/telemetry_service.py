import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from app.database import get_db
from app.helpers import (
    bad_request_response,
    check_etag,
    compute_etag,
    created_response,
    no_content_response,
    not_found_response,
    odata_pagination,
    precondition_failed_response,
)

router = APIRouter()

BASE = "/redfish/v1/TelemetryService"


@router.get("/redfish/v1/TelemetryService")
def telemetry_service():
    return {
        "@odata.id": BASE,
        "@odata.type": "#TelemetryService.v1_3_3.TelemetryService",
        "@odata.context": "/redfish/v1/$metadata#TelemetryService.TelemetryService",
        "Id": "TelemetryService",
        "Name": "Telemetry Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "MaxReports": 100,
        "MinCollectionInterval": "PT5S",
        "SupportedCollectionFunctions": ["Average", "Maximum", "Minimum", "Summation"],
        "MetricDefinitions": {"@odata.id": f"{BASE}/MetricDefinitions"},
        "MetricReportDefinitions": {"@odata.id": f"{BASE}/MetricReportDefinitions"},
        "MetricReports": {"@odata.id": f"{BASE}/MetricReports"},
    }


# ──── MetricDefinitions ──────────────────────────────────────────────────────

@router.get("/redfish/v1/TelemetryService/MetricDefinitions")
def metric_definitions(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM metric_definitions").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{BASE}/MetricDefinitions")
    rows = db.execute(
        "SELECT id FROM metric_definitions ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    result = {
        "@odata.id": f"{BASE}/MetricDefinitions",
        "@odata.type": "#MetricDefinitionCollection.MetricDefinitionCollection",
        "Name": "Metric Definition Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{BASE}/MetricDefinitions/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/TelemetryService/MetricDefinitions/{def_id}")
def metric_definition(
    def_id: str,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM metric_definitions WHERE id=?", (def_id,)).fetchone()
    if not row:
        return not_found_response(f"MetricDefinition {def_id}")
    data = _metric_definition_resource(row)
    response.headers["ETag"] = f'"{compute_etag(data)}"'
    return data


# ──── MetricReportDefinitions ────────────────────────────────────────────────

@router.get("/redfish/v1/TelemetryService/MetricReportDefinitions")
def metric_report_definitions(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM metric_report_definitions").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{BASE}/MetricReportDefinitions")
    rows = db.execute(
        "SELECT id FROM metric_report_definitions ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    result = {
        "@odata.id": f"{BASE}/MetricReportDefinitions",
        "@odata.type": "#MetricReportDefinitionCollection.MetricReportDefinitionCollection",
        "Name": "Metric Report Definition Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{BASE}/MetricReportDefinitions/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


class _MetricItem(BaseModel):
    MetricId: str
    CollectionFunction: Optional[str] = None


class MetricReportDefinitionCreate(BaseModel):
    Name: str
    MetricReportDefinitionType: Optional[str] = "OnRequest"
    Schedule: Optional[dict] = None
    Metrics: List[_MetricItem]
    ReportActions: Optional[List[str]] = None


_VALID_DEFINITION_TYPES = ("Periodic", "OnChange", "OnRequest")


@router.post("/redfish/v1/TelemetryService/MetricReportDefinitions")
def create_metric_report_definition(
    body: MetricReportDefinitionCreate,
    db: sqlite3.Connection = Depends(get_db),
):
    if body.MetricReportDefinitionType not in _VALID_DEFINITION_TYPES:
        return bad_request_response(
            f"MetricReportDefinitionType must be one of: {', '.join(_VALID_DEFINITION_TYPES)}"
        )
    for m in body.Metrics:
        if not db.execute("SELECT 1 FROM metric_definitions WHERE id=?", (m.MetricId,)).fetchone():
            return bad_request_response(f"MetricDefinition '{m.MetricId}' not found")

    mrd_id = str(uuid.uuid4())[:8]
    schedule_interval = body.Schedule.get("RecurrenceInterval") if body.Schedule else None
    report_actions = body.ReportActions or ["LogToMetricReportsCollection"]

    db.execute(
        """INSERT INTO metric_report_definitions
           (id, name, definition_type, schedule_interval, metrics, report_actions)
           VALUES (?,?,?,?,?,?)""",
        (
            mrd_id,
            body.Name,
            body.MetricReportDefinitionType,
            schedule_interval,
            json.dumps([m.model_dump(exclude_none=True) for m in body.Metrics]),
            json.dumps(report_actions),
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM metric_report_definitions WHERE id=?", (mrd_id,)).fetchone()
    return created_response(
        _metric_report_definition_resource(row),
        f"{BASE}/MetricReportDefinitions/{mrd_id}",
    )


@router.get("/redfish/v1/TelemetryService/MetricReportDefinitions/{mrd_id}")
def metric_report_definition(
    mrd_id: str,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM metric_report_definitions WHERE id=?", (mrd_id,)).fetchone()
    if not row:
        return not_found_response(f"MetricReportDefinition {mrd_id}")
    data = _metric_report_definition_resource(row)
    response.headers["ETag"] = f'"{compute_etag(data)}"'
    return data


class MetricReportDefinitionPatch(BaseModel):
    Name: Optional[str] = None
    MetricReportDefinitionType: Optional[str] = None
    Schedule: Optional[dict] = None
    Metrics: Optional[List[_MetricItem]] = None
    ReportActions: Optional[List[str]] = None
    Status: Optional[dict] = None


@router.patch("/redfish/v1/TelemetryService/MetricReportDefinitions/{mrd_id}")
def patch_metric_report_definition(
    mrd_id: str,
    body: MetricReportDefinitionPatch,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM metric_report_definitions WHERE id=?", (mrd_id,)).fetchone()
    if not row:
        return not_found_response(f"MetricReportDefinition {mrd_id}")

    current = _metric_report_definition_resource(row)
    if not check_etag(request.headers.get("If-Match"), compute_etag(current)):
        return precondition_failed_response()

    updates = {}
    if body.Name is not None:
        updates["name"] = body.Name
    if body.MetricReportDefinitionType is not None:
        if body.MetricReportDefinitionType not in _VALID_DEFINITION_TYPES:
            return bad_request_response(
                f"MetricReportDefinitionType must be one of: {', '.join(_VALID_DEFINITION_TYPES)}"
            )
        updates["definition_type"] = body.MetricReportDefinitionType
    if body.Schedule is not None:
        updates["schedule_interval"] = body.Schedule.get("RecurrenceInterval")
    if body.Metrics is not None:
        for m in body.Metrics:
            if not db.execute("SELECT 1 FROM metric_definitions WHERE id=?", (m.MetricId,)).fetchone():
                return bad_request_response(f"MetricDefinition '{m.MetricId}' not found")
        updates["metrics"] = json.dumps([m.model_dump(exclude_none=True) for m in body.Metrics])
    if body.ReportActions is not None:
        updates["report_actions"] = json.dumps(body.ReportActions)
    if body.Status is not None:
        if "State" in body.Status:
            updates["status_state"] = body.Status["State"]
        if "Health" in body.Status:
            updates["status_health"] = body.Status["Health"]

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(
            f"UPDATE metric_report_definitions SET {set_clause} WHERE id=?",
            (*updates.values(), mrd_id),
        )
        db.commit()

    row = db.execute("SELECT * FROM metric_report_definitions WHERE id=?", (mrd_id,)).fetchone()
    return _metric_report_definition_resource(row)


@router.delete("/redfish/v1/TelemetryService/MetricReportDefinitions/{mrd_id}")
def delete_metric_report_definition(mrd_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM metric_report_definitions WHERE id=?", (mrd_id,)).fetchone():
        return not_found_response(f"MetricReportDefinition {mrd_id}")
    db.execute("DELETE FROM metric_report_definitions WHERE id=?", (mrd_id,))
    db.commit()
    return no_content_response()


# ──── MetricReports ──────────────────────────────────────────────────────────

@router.get("/redfish/v1/TelemetryService/MetricReports")
def metric_reports(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM metric_report_definitions").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{BASE}/MetricReports")
    rows = db.execute(
        "SELECT id FROM metric_report_definitions ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    result = {
        "@odata.id": f"{BASE}/MetricReports",
        "@odata.type": "#MetricReportCollection.MetricReportCollection",
        "Name": "Metric Report Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{BASE}/MetricReports/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/TelemetryService/MetricReports/{report_id}")
def metric_report(report_id: str, db: sqlite3.Connection = Depends(get_db)):
    mrd_row = db.execute(
        "SELECT * FROM metric_report_definitions WHERE id=?", (report_id,)
    ).fetchone()
    if not mrd_row:
        return not_found_response(f"MetricReport {report_id}")

    metric_values = []
    now = datetime.now(timezone.utc).isoformat()
    for metric_item in json.loads(mrd_row["metrics"]):
        def_row = db.execute(
            "SELECT * FROM metric_definitions WHERE id=?", (metric_item["MetricId"],)
        ).fetchone()
        if not def_row:
            continue
        for prop_uri in json.loads(def_row["metric_properties"]):
            reading = _resolve_metric_property(prop_uri, db)
            if reading is not None:
                metric_values.append({
                    "MetricId": metric_item["MetricId"],
                    "MetricProperty": prop_uri,
                    "MetricValue": str(reading),
                    "Timestamp": now,
                })

    return {
        "@odata.id": f"{BASE}/MetricReports/{report_id}",
        "@odata.type": "#MetricReport.v1_5_0.MetricReport",
        "@odata.context": "/redfish/v1/$metadata#MetricReport.MetricReport",
        "Id": report_id,
        "Name": f"{mrd_row['name']} Report",
        "Timestamp": now,
        "MetricReportDefinition": {"@odata.id": f"{BASE}/MetricReportDefinitions/{report_id}"},
        "MetricValues": metric_values,
    }


# ──── private helpers ────────────────────────────────────────────────────────

_PDU_SENSOR_RE = re.compile(
    r"/redfish/v1/PowerEquipment/RackPDUs/([^/]+)/Sensors/([^#/]+)"
)
_UPS_SENSOR_RE = re.compile(
    r"/redfish/v1/PowerEquipment/UPSs/([^/]+)/Sensors/([^#/]+)"
)
_CHASSIS_SENSOR_RE = re.compile(
    r"/redfish/v1/Chassis/([^/]+)/Sensors/([^#/]+)"
)


def _resolve_metric_property(uri: str, db: sqlite3.Connection) -> Optional[float]:
    base_uri = uri.split("#")[0]

    m = _PDU_SENSOR_RE.match(base_uri)
    if m:
        row = db.execute(
            "SELECT reading FROM pdu_sensors WHERE id=? AND pdu_id=?", (m.group(2), m.group(1))
        ).fetchone()
        return row["reading"] if row else None

    m = _UPS_SENSOR_RE.match(base_uri)
    if m:
        row = db.execute(
            "SELECT reading FROM ups_sensors WHERE id=? AND ups_id=?", (m.group(2), m.group(1))
        ).fetchone()
        return row["reading"] if row else None

    m = _CHASSIS_SENSOR_RE.match(base_uri)
    if m:
        row = db.execute(
            "SELECT reading FROM chassis_sensors WHERE id=? AND chassis_id=?",
            (m.group(2), m.group(1)),
        ).fetchone()
        return row["reading"] if row else None

    return None


def _metric_definition_resource(row) -> dict:
    mid = row["id"]
    props = json.loads(row["metric_properties"]) if row["metric_properties"] else []
    data = {
        "@odata.id": f"{BASE}/MetricDefinitions/{mid}",
        "@odata.type": "#MetricDefinition.v1_3_0.MetricDefinition",
        "@odata.context": "/redfish/v1/$metadata#MetricDefinition.MetricDefinition",
        "Id": mid,
        "Name": row["name"],
        "MetricType": row["metric_type"],
        "Implementation": row["implementation"],
        "MetricDataType": row["metric_data_type"],
        "Units": row["units"],
        "PhysicalContext": row["physical_context"],
        "SensorType": row["sensor_type"],
        "MetricProperties": props,
    }
    if row["min_reading_range"] is not None:
        data["MinReadingRange"] = row["min_reading_range"]
    if row["max_reading_range"] is not None:
        data["MaxReadingRange"] = row["max_reading_range"]
    return data


def _metric_report_definition_resource(row) -> dict:
    rid = row["id"]
    metrics = json.loads(row["metrics"])
    report_actions = json.loads(row["report_actions"]) if row["report_actions"] else []
    data = {
        "@odata.id": f"{BASE}/MetricReportDefinitions/{rid}",
        "@odata.type": "#MetricReportDefinition.v1_4_2.MetricReportDefinition",
        "@odata.context": "/redfish/v1/$metadata#MetricReportDefinition.MetricReportDefinition",
        "Id": rid,
        "Name": row["name"],
        "MetricReportDefinitionType": row["definition_type"],
        "Metrics": metrics,
        "ReportActions": report_actions,
        "MetricReport": {"@odata.id": f"{BASE}/MetricReports/{rid}"},
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
    }
    if row["schedule_interval"]:
        data["Schedule"] = {"RecurrenceInterval": row["schedule_interval"]}
    return data
