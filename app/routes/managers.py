import sqlite3

from fastapi import APIRouter, Depends

from app.database import get_db
from app.helpers import not_found_response

router = APIRouter()


def _manager_resource(row) -> dict:
    mid = row["id"]
    base = f"/redfish/v1/Managers/{mid}"
    return {
        "@odata.id": base,
        "@odata.type": "#Manager.v1_19_0.Manager",
        "@odata.context": "/redfish/v1/$metadata#Manager.Manager",
        "Id": mid,
        "Name": row["name"],
        "ManagerType": row["manager_type"],
        "FirmwareVersion": row["firmware_version"],
        "Status": {"State": row["status_state"], "Health": row["status_health"]},
        "NetworkProtocol": {"@odata.id": f"{base}/NetworkProtocol"},
        "EthernetInterfaces": {"@odata.id": f"{base}/EthernetInterfaces"},
        "Links": {
            "ManagedChassisCount": 1,
        },
    }


@router.get("/redfish/v1/Managers")
def managers(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id FROM managers ORDER BY id").fetchall()
    return {
        "@odata.id": "/redfish/v1/Managers",
        "@odata.type": "#ManagerCollection.ManagerCollection",
        "@odata.context": "/redfish/v1/$metadata#ManagerCollection.ManagerCollection",
        "Name": "Manager Collection",
        "Members@odata.count": len(rows),
        "Members": [
            {"@odata.id": f"/redfish/v1/Managers/{r['id']}"} for r in rows
        ],
    }


@router.get("/redfish/v1/Managers/{manager_id}")
def manager(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM managers WHERE id=?", (manager_id,)).fetchone()
    if not row:
        return not_found_response(f"Manager {manager_id}")
    return _manager_resource(row)


@router.get("/redfish/v1/Managers/{manager_id}/NetworkProtocol")
def manager_network_protocol(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM managers WHERE id=?", (manager_id,)).fetchone()
    if not row:
        return not_found_response(f"Manager {manager_id}")
    base = f"/redfish/v1/Managers/{manager_id}"
    return {
        "@odata.id": f"{base}/NetworkProtocol",
        "@odata.type": "#ManagerNetworkProtocol.v1_9_0.ManagerNetworkProtocol",
        "Id": "NetworkProtocol",
        "Name": "Manager Network Protocol",
        "Status": {"State": "Enabled", "Health": "OK"},
        "HostName": row["hostname"],
        "HTTP": {"ProtocolEnabled": True, "Port": 8009},
        "HTTPS": {"ProtocolEnabled": False, "Port": 443},
        "SNMP": {"ProtocolEnabled": True, "Port": 161},
        "SSH": {"ProtocolEnabled": True, "Port": 22},
    }


@router.get("/redfish/v1/Managers/{manager_id}/EthernetInterfaces")
def manager_ethernet_interfaces(manager_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM managers WHERE id=?", (manager_id,)).fetchone():
        return not_found_response(f"Manager {manager_id}")
    base = f"/redfish/v1/Managers/{manager_id}"
    return {
        "@odata.id": f"{base}/EthernetInterfaces",
        "@odata.type": "#EthernetInterfaceCollection.EthernetInterfaceCollection",
        "Name": "Ethernet Interface Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": f"{base}/EthernetInterfaces/eth0"}],
    }


@router.get("/redfish/v1/Managers/{manager_id}/EthernetInterfaces/{nic_id}")
def manager_ethernet_interface(
    manager_id: str, nic_id: str, db: sqlite3.Connection = Depends(get_db)
):
    row = db.execute("SELECT * FROM managers WHERE id=?", (manager_id,)).fetchone()
    if not row:
        return not_found_response(f"Manager {manager_id}")
    if nic_id != "eth0":
        return not_found_response(f"EthernetInterface {nic_id}")
    return {
        "@odata.id": f"/redfish/v1/Managers/{manager_id}/EthernetInterfaces/{nic_id}",
        "@odata.type": "#EthernetInterface.v1_9_0.EthernetInterface",
        "Id": nic_id,
        "Name": "Management Ethernet Interface",
        "InterfaceEnabled": True,
        "LinkStatus": "LinkUp",
        "SpeedMbps": 1000,
        "FullDuplex": True,
        "IPv4Addresses": [
            {
                "Address": row["ipv4_address"],
                "SubnetMask": "255.255.255.0",
                "AddressOrigin": "Static",
                "Gateway": "192.168.1.254",
            }
        ],
        "Status": {"State": "Enabled", "Health": "OK"},
    }
