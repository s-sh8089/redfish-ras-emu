import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.database import get_db
from app.helpers import bad_request_response, no_content_response, not_found_response

router = APIRouter()

_SESSION_TTL_HOURS = 24


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _session_resource(row) -> dict:
    return {
        "@odata.id": f"/redfish/v1/SessionService/Sessions/{row['id']}",
        "@odata.type": "#Session.v1_6_0.Session",
        "@odata.context": "/redfish/v1/$metadata#Session.Session",
        "Id": row["id"],
        "Name": f"Session {row['id']}",
        "UserName": row["username"],
        "CreatedTime": row["created_at"],
    }


@router.get("/redfish/v1/SessionService")
def session_service():
    return {
        "@odata.id": "/redfish/v1/SessionService",
        "@odata.type": "#SessionService.v1_1_8.SessionService",
        "@odata.context": "/redfish/v1/$metadata#SessionService.SessionService",
        "Id": "SessionService",
        "Name": "Session Service",
        "Status": {"State": "Enabled", "Health": "OK"},
        "ServiceEnabled": True,
        "SessionTimeout": _SESSION_TTL_HOURS * 3600,
        "Sessions": {"@odata.id": "/redfish/v1/SessionService/Sessions"},
    }


class LoginBody(BaseModel):
    UserName: str
    Password: str


@router.post("/redfish/v1/SessionService/Sessions")
def create_session(body: LoginBody, db: sqlite3.Connection = Depends(get_db)):
    account = db.execute(
        "SELECT * FROM accounts WHERE username=?", (body.UserName,)
    ).fetchone()
    if not account or account["password_hash"] != _hash_password(body.Password):
        return bad_request_response("Invalid credentials")

    session_id = str(uuid.uuid4())[:8]
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + timedelta(hours=_SESSION_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    db.execute(
        "INSERT INTO sessions (id, username, token, created_at, expires_at) VALUES (?,?,?,?,?)",
        (session_id, body.UserName, token, created_at, expires_at),
    )
    db.commit()

    row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return JSONResponse(
        status_code=201,
        content=_session_resource(row),
        headers={
            "Location": f"/redfish/v1/SessionService/Sessions/{session_id}",
            "X-Auth-Token": token,
        },
    )


@router.get("/redfish/v1/SessionService/Sessions")
def sessions(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        "SELECT id FROM sessions WHERE datetime(expires_at) > datetime('now') ORDER BY created_at DESC"
    ).fetchall()
    return {
        "@odata.id": "/redfish/v1/SessionService/Sessions",
        "@odata.type": "#SessionCollection.SessionCollection",
        "@odata.context": "/redfish/v1/$metadata#SessionCollection.SessionCollection",
        "Name": "Session Collection",
        "Members@odata.count": len(rows),
        "Members": [{"@odata.id": f"/redfish/v1/SessionService/Sessions/{r['id']}"} for r in rows],
    }


@router.get("/redfish/v1/SessionService/Sessions/{session_id}")
def get_session(session_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT * FROM sessions WHERE id=? AND datetime(expires_at) > datetime('now')",
        (session_id,),
    ).fetchone()
    if not row:
        return not_found_response(f"Session {session_id}")
    return _session_resource(row)


@router.delete("/redfish/v1/SessionService/Sessions/{session_id}")
def delete_session(session_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return not_found_response(f"Session {session_id}")
    db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    db.commit()
    return no_content_response()
