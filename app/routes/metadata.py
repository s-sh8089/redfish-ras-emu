from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

_CSDL = """\
<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/ServiceRoot_v1.xml">
    <edmx:Include Namespace="ServiceRoot.v1_15_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/PowerEquipment_v1.xml">
    <edmx:Include Namespace="PowerEquipment.v1_2_1"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/PowerDistribution_v1.xml">
    <edmx:Include Namespace="PowerDistribution.v1_3_2"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Chassis_v1.xml">
    <edmx:Include Namespace="Chassis.v1_25_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Manager_v1.xml">
    <edmx:Include Namespace="Manager.v1_19_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/EventService_v1.xml">
    <edmx:Include Namespace="EventService.v1_10_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/LogService_v1.xml">
    <edmx:Include Namespace="LogService.v1_4_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/LogEntry_v1.xml">
    <edmx:Include Namespace="LogEntry.v1_15_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Sensor_v1.xml">
    <edmx:Include Namespace="Sensor.v1_9_0"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Outlet_v1.xml">
    <edmx:Include Namespace="Outlet.v1_4_2"/>
  </edmx:Reference>
  <edmx:Reference Uri="http://redfish.dmtf.org/schemas/v1/Circuit_v1.xml">
    <edmx:Include Namespace="Circuit.v1_6_0"/>
  </edmx:Reference>
  <edmx:DataServices>
    <Schema Namespace="RedfishRASEmulator" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityContainer Name="Service" Extends="ServiceRoot.v1_15_0.ServiceRoot"/>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


@router.get("/redfish/v1/$metadata")
def metadata():
    return Response(content=_CSDL, media_type="application/xml")


@router.get("/redfish/v1/odata")
def odata_service_document():
    return {
        "@odata.context": "/redfish/v1/$metadata",
        "value": [
            {"name": "Service", "kind": "Singleton", "url": "/redfish/v1/"},
            {"name": "PowerEquipment", "kind": "Singleton", "url": "/redfish/v1/PowerEquipment"},
            {"name": "Chassis", "kind": "EntitySet", "url": "/redfish/v1/Chassis"},
            {"name": "Managers", "kind": "EntitySet", "url": "/redfish/v1/Managers"},
            {"name": "EventService", "kind": "Singleton", "url": "/redfish/v1/EventService"},
        ],
    }
