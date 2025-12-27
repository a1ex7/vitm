from datetime import timezone
import pytz

API_ID = 29477438
API_HASH = "b35cd0b313143486e8ca98cbb275ee2f"

CHECK_INTERVAL = 5  # секунд
DB_FILE = "online_statuses_temp.db"

LOCAL_TZ = pytz.timezone("Europe/Kiev")
UTC = timezone.utc
