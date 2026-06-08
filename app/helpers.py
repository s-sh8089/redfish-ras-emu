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
