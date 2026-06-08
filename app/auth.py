import sqlite3

from fastapi.responses import JSONResponse

from app import config


def unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "Base.1.0.NoValidSession",
                "message": "There is no valid session established with the implementation.",
                "@Message.ExtendedInfo": [],
            }
        },
        headers={"WWW-Authenticate": 'Basic realm="Redfish"'},
    )


def validate_token(token: str) -> bool:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE token=? AND datetime(expires_at) > datetime('now')",
            (token,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
