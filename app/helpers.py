import hashlib
import json
from typing import Optional

from fastapi.responses import JSONResponse


def not_found_response(resource: str = "Resource"):
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "Base.1.0.ResourceNotFound",
                "message": f"{resource} was not found.",
                "@Message.ExtendedInfo": [],
            }
        },
    )


def bad_request_response(message: str = "Bad request"):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "Base.1.0.GeneralError",
                "message": message,
                "@Message.ExtendedInfo": [],
            }
        },
    )


def no_content_response():
    return JSONResponse(status_code=204, content=None)


def created_response(data: dict, location: str):
    return JSONResponse(
        status_code=201,
        content=data,
        headers={"Location": location},
    )


def compute_etag(resource: dict) -> str:
    return hashlib.md5(json.dumps(resource, sort_keys=True).encode()).hexdigest()


def check_etag(if_match: Optional[str], current_etag: str) -> bool:
    if not if_match:
        return True
    return if_match in ("*", f'"{current_etag}"', current_etag)


def precondition_failed_response():
    return JSONResponse(
        status_code=412,
        content={
            "error": {
                "code": "Base.1.0.PreconditionFailed",
                "message": "The ETag supplied does not match the current ETag for the resource.",
                "@Message.ExtendedInfo": [],
            }
        },
    )


def odata_pagination(
    top: Optional[int],
    skip: Optional[int],
    total: int,
    base_url: str,
) -> tuple[int, int, Optional[str]]:
    """Return (effective_limit, effective_offset, next_link_or_None)."""
    offset = skip or 0
    limit = top if top is not None else total - offset
    next_link = None
    if top is not None and (offset + top) < total:
        next_link = f"{base_url}?$top={top}&$skip={offset + top}"
    return limit, offset, next_link
