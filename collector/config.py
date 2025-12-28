import pytz
import os
from dotenv import load_dotenv
from datetime import timezone

load_dotenv()

def required(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is not set")
    return value

API_ID = int(required("API_ID"))
API_HASH = required("API_HASH")

CHECK_INTERVAL = 5  # секунд
DB_FILE = "shared/vitm.db"

LOCAL_TZ = pytz.timezone("Europe/Kiev")
UTC = timezone.utc
