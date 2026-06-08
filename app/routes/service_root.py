from fastapi import APIRouter

router = APIRouter()


@router.get("/redfish/v1")
@router.get("/redfish/v1/")
def service_root():
    return {
        "@odata.id": "/redfish/v1/",
        "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot",
        "@odata.context": "/redfish/v1/$metadata#ServiceRoot.ServiceRoot",
        "Id": "RootService",
        "Name": "Root Service",
        "RedfishVersion": "1.17.0",
        "UUID": "00000000-0000-0000-0000-000000000001",
        "PowerEquipment": {"@odata.id": "/redfish/v1/PowerEquipment"},
        "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "EventService": {"@odata.id": "/redfish/v1/EventService"},
        "Links": {
            "Sessions": {"@odata.id": "/redfish/v1/SessionService/Sessions"}
        },
    }
