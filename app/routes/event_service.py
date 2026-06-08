import asyncio
import json
import sqlite3
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app import config
from app.auth import unauthorized_response, validate_token
from app.database import get_db
from app.event_dispatcher import dispatch_event
from app.helpers import bad_request_response, created_response, no_content_response, not_found_response, odata_pagination
from app.sse_manager import sse_manager

router = APIRouter()

BASE = "/redfish/v1/EventService"


@router.get("/redfish/v1/EventService")
def event_service():
    return {
        "@odata.id": BASE,
        "@odata.type": "#EventService.v1_10_0.EventService",
        "@odata.context": "/redfish/v1/$metadata#EventService.EventService",
        "Id": "EventService",
        "Name": "Event Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "ServiceEnabled": True,
        "DeliveryRetryAttempts": config.EVENT_RETRY_ATTEMPTS,
        "DeliveryRetryIntervalSeconds": config.EVENT_RETRY_INTERVAL,
        "EventTypesForSubscription": [
            "StatusChange",
            "ResourceUpdated",
            "ResourceAdded",
            "ResourceRemoved",
            "Alert",
        ],
        "Subscriptions": {"@odata.id": f"{BASE}/Subscriptions"},
        "Actions": {
            "#EventService.SubmitTestEvent": {
                "target": f"{BASE}/Actions/EventService.SubmitTestEvent"
            }
        },
    }


@router.get("/redfish/v1/EventService/Subscriptions")
def subscriptions(
    db: sqlite3.Connection = Depends(get_db),
    top: Optional[int] = Query(None, alias="$top", ge=1),
    skip: Optional[int] = Query(None, alias="$skip", ge=0),
):
    total = db.execute("SELECT COUNT(*) FROM event_subscriptions").fetchone()[0]
    limit, offset, next_link = odata_pagination(top, skip, total, f"{BASE}/Subscriptions")
    rows = db.execute(
        "SELECT id FROM event_subscriptions ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    result = {
        "@odata.id": f"{BASE}/Subscriptions",
        "@odata.type": "#EventDestinationCollection.EventDestinationCollection",
        "Name": "Event Subscription Collection",
        "Members@odata.count": total,
        "Members": [{"@odata.id": f"{BASE}/Subscriptions/{r['id']}"} for r in rows],
    }
    if next_link:
        result["Members@odata.nextLink"] = next_link
    return result


class SubscriptionCreate(BaseModel):
    Destination: str
    Protocol: Optional[str] = "Redfish"
    Context: Optional[str] = None
    EventTypes: Optional[List[str]] = None
    Name: Optional[str] = None


@router.post("/redfish/v1/EventService/Subscriptions")
def create_subscription(body: SubscriptionCreate, db: sqlite3.Connection = Depends(get_db)):
    if not body.Destination:
        return bad_request_response("Destination is required")
    sub_id = str(uuid.uuid4())[:8]
    db.execute(
        """INSERT INTO event_subscriptions (id, name, destination, protocol, context, event_types)
           VALUES (?,?,?,?,?,?)""",
        (
            sub_id,
            body.Name or f"Subscription {sub_id}",
            body.Destination,
            body.Protocol,
            body.Context,
            json.dumps(body.EventTypes) if body.EventTypes else None,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM event_subscriptions WHERE id=?", (sub_id,)).fetchone()
    location = f"{BASE}/Subscriptions/{sub_id}"
    return created_response(_subscription_resource(row), location)


@router.get("/redfish/v1/EventService/Subscriptions/{sub_id}")
def subscription(sub_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM event_subscriptions WHERE id=?", (sub_id,)).fetchone()
    if not row:
        return not_found_response(f"Subscription {sub_id}")
    return _subscription_resource(row)


@router.delete("/redfish/v1/EventService/Subscriptions/{sub_id}")
def delete_subscription(sub_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT 1 FROM event_subscriptions WHERE id=?", (sub_id,)).fetchone()
    if not row:
        return not_found_response(f"Subscription {sub_id}")
    db.execute("DELETE FROM event_subscriptions WHERE id=?", (sub_id,))
    db.commit()
    return no_content_response()


class SubmitTestEventBody(BaseModel):
    EventType: Optional[str] = "Alert"
    Message: Optional[str] = "Test event submitted"
    Severity: Optional[str] = "OK"
    OriginOfCondition: Optional[str] = "/redfish/v1/EventService"


@router.post("/redfish/v1/EventService/Actions/EventService.SubmitTestEvent")
def submit_test_event(body: SubmitTestEventBody, background_tasks: BackgroundTasks):
    valid_types = ("StatusChange", "ResourceUpdated", "ResourceAdded", "ResourceRemoved", "Alert")
    if body.EventType not in valid_types:
        return bad_request_response(f"EventType must be one of: {', '.join(valid_types)}")
    background_tasks.add_task(
        dispatch_event,
        body.EventType,
        body.OriginOfCondition,
        body.Message,
        body.Severity,
    )
    return JSONResponse(status_code=200, content={"Message": "Test event submitted successfully"})


@router.get("/redfish/v1/EventService/SSE")
async def event_service_sse(request: Request, token: Optional[str] = Query(None)):
    auth_token = request.headers.get("X-Auth-Token") or token
    if not auth_token or not validate_token(auth_token):
        return unauthorized_response()

    async def generate():
        async with sse_manager.subscribe() as queue:
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _subscription_resource(row) -> dict:
    sid = row["id"]
    event_types = json.loads(row["event_types"]) if row["event_types"] else []
    return {
        "@odata.id": f"{BASE}/Subscriptions/{sid}",
        "@odata.type": "#EventDestination.v1_14_0.EventDestination",
        "@odata.context": "/redfish/v1/$metadata#EventDestination.EventDestination",
        "Id": sid,
        "Name": row["name"],
        "Destination": row["destination"],
        "Protocol": row["protocol"],
        "Context": row["context"],
        "EventTypes": event_types,
        "Status": {"State": row["status_state"]},
    }
