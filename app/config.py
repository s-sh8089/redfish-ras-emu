import os

DB_PATH = os.environ.get("DB_PATH", "data/redfish.db")

EVENT_RETRY_ATTEMPTS = int(os.environ.get("EVENT_RETRY_ATTEMPTS", "3"))
EVENT_RETRY_INTERVAL = int(os.environ.get("EVENT_RETRY_INTERVAL", "60"))
