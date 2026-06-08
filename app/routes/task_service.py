import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.helpers import no_content_response, not_found_response, odata_pagination

router = APIRouter()


def _task_resource(row) -> dict:
    tid = row["id"]
    resource = {
        "@odata.id": f"/redfish/v1/TaskService/Tasks/{tid}",
        "@odata.type": "#Task.v1_7_0.Task",
        "@odata.context": "/redfish/v1/$metadata#Task.Task",
        "Id": tid,
        "Name": row["name"],
        "TaskState": row["task_state"],
        "TaskStatus": row["task_status"],
        "StartTime": row["start_time"],
        "Messages": [],
    }
    if row["end_time"]:
        resource["EndTime"] = row["end_time"]
    if row["target_uri"]:
        resource["Payload"] = {"TargetUri": row["target_uri"]}
    return resource


@router.get("/redfish/v1/TaskService")
def task_service():
    return {
        "@odata.id": "/redfish/v1/TaskService",
        "@odata.type": "#TaskService.v1_2_0.TaskService",
        "@odata.context": "/redfish/v1/$metadata#TaskService.TaskService",
        "Id": "TaskService",
        "Name": "Task Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "ServiceEnabled": True,
        "Tasks": {"@odata.id": "/redfish/v1/TaskService/Tasks"},
    }


@router.get("/redfish/v1/TaskService/Tasks")
def task_list(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, "/redfish/v1/TaskService/Tasks")
    rows = db.execute(
        "SELECT id FROM tasks ORDER BY start_time DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    result = {
        "@odata.id": "/redfish/v1/TaskService/Tasks",
        "@odata.type": "#TaskCollection.TaskCollection",
        "@odata.context": "/redfish/v1/$metadata#TaskCollection.TaskCollection",
        "Name": "Task Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"/redfish/v1/TaskService/Tasks/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


@router.get("/redfish/v1/TaskService/Tasks/{task_id}")
def get_task(task_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return not_found_response(f"Task {task_id}")
    return _task_resource(row)


@router.delete("/redfish/v1/TaskService/Tasks/{task_id}")
def delete_task(task_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return not_found_response(f"Task {task_id}")
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit()
    return no_content_response()
