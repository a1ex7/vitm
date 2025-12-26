import asyncio
import sqlite3
import pandas as pd
from datetime import datetime, timezone
import pytz
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import UserStatusOffline, UserStatusOnline
import signal

# === Настройки ===
api_id = 29477438
api_hash = "b35cd0b313143486e8ca98cbb275ee2f"
# USERS = ["@Viktoriia_dreams", "@Prado_ua"]
CHECK_INTERVAL = 5

DB_FILE = "online_statuses.db"
LOCAL_TZ = pytz.timezone("Europe/Kiev")

# === Цвета для консоли ===
GREEN = "\033[92m"
GRAY = "\033[90m"
RESET = "\033[0m"

# === Флаги и состояния ===
stop_event = asyncio.Event()
active_sessions = {}  # user -> datetime

# === Подключение к базе и создание таблиц ===
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    name TEXT,
    active INTEGER DEFAULT 1
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS online_statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    status TEXT,
    UNIQUE(user_id, date, status),
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS online_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    started_at TEXT,
    ended_at TEXT,
    duration INTEGER, -- секунды
    UNIQUE(user_id, started_at),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
""")

conn.commit()

# === Функции ===
def shutdown():
    print("\n⛔ Остановка мониторинга по нажатию Ctrl+C")
    stop_event.set()

async def get_online_status(client, user):
    """
    Возвращает (status, timestamp). status = 'online'|'offline'
    timestamp = datetime объекта статуса (last_seen для offline)
    """
    try:
        entity = await client.get_entity(user)
        status = entity.status

        now = datetime.now(timezone.utc)

        if isinstance(status, UserStatusOnline):
            return "online", now

        if isinstance(status, UserStatusOffline):
            last_seen = status.was_online
            if isinstance(last_seen, int):  # иногда возвращается unix timestamp
                last_seen = datetime.fromtimestamp(last_seen, tz=timezone.utc)
            return "offline", last_seen

        return "offline", now

    except FloodWaitError as e:
        print(f"FloodWaitError: ждём {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
        return "offline", datetime.now(timezone.utc)
    except Exception as e:
        print(f"Ошибка при проверке {user}: {e}")
        return "offline", datetime.now(timezone.utc)

def get_active_user_ids():
    conn = sqlite3.connect(DB_FILE)
    # Выбираем только тех, у кого status или флаг активен
    df_users = pd.read_sql_query(
        "SELECT username FROM users WHERE active = 1",
        conn
    )
    conn.close()
    return df_users["username"].tolist()

def save_status(user, status, ts):
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        cur.execute("INSERT INTO users(username) VALUES (?)", (user,))
        user_id = cur.lastrowid
        conn.commit()

    # Если offline — сохраняем предыдущий online по last_seen
    now = datetime.now(timezone.utc)
    if status == "offline":
        cur.execute("""
            INSERT OR IGNORE INTO online_statuses(user_id, date, status) VALUES (?, ?, ?)
        """, (user_id, ts.replace(microsecond=0).astimezone(timezone.utc).isoformat(), "online"))

    # Сохраняем текущий статус (online или offline)
    cur.execute("""
        INSERT OR IGNORE INTO online_statuses(user_id, date, status) VALUES (?, ?, ?)
    """, (user_id, now.replace(microsecond=0).astimezone(timezone.utc).isoformat(), status))
    conn.commit()

def save_uptime(user, status, ts):
    """
        Сохраняет сессии online/offline для расчёта uptime.
        """
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()

    if row:
        user_id = row[0]
    else:
        cur.execute("INSERT INTO users(username) VALUES (?)", (user,))
        user_id = cur.lastrowid
        conn.commit()

    # === ONLINE ===
    if status == "online":
        if user not in active_sessions:
            active_sessions[user] = ts
        return

    # === OFFLINE ===
    if status == "offline" and user in active_sessions:
        started_at = active_sessions.pop(user, None)

        duration = int((ts - started_at).total_seconds())
        if duration <= 0:
            return

        cur.execute("""
            INSERT OR IGNORE INTO online_sessions
            (user_id, started_at, ended_at, duration)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            started_at.replace(microsecond=0).astimezone(timezone.utc).isoformat(),
            ts.replace(microsecond=0).astimezone(timezone.utc).isoformat(),
            duration
        ))
        conn.commit()

def finalize_sessions():
    """
    Завершает все активные сессии при остановке.
    """
    now = datetime.now(timezone.utc)
    for user, started_at in list(active_sessions.items()):
        save_uptime(user, "offline", now)
        active_sessions.pop(user, None)

async def monitor_user(client, user):
    while not stop_event.is_set():
        status, ts = await get_online_status(client, user)

        save_status(user, status, ts)
        save_uptime(user, status, ts)

        last_seen_local = ts.astimezone(LOCAL_TZ)
        now_local_str = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")

        if status == "online":
            print(
                f"[{now_local_str}] {user} — "
                f"{GREEN}Online{RESET}"
            )
        else:
            print(
                f"[{now_local_str}] {user} — "
                f"{GRAY}Offline{RESET} "
                f"(last seen: {last_seen_local.strftime('%Y-%m-%d %H:%M:%S')})"
            )

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            pass

async def main():
    async with TelegramClient("monitor_session", api_id, api_hash) as client:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, shutdown)
        USERS = get_active_user_ids()
        tasks = [asyncio.create_task(monitor_user(client, user)) for user in USERS]

        await stop_event.wait() # ждём Ctrl+C

        # отменяем задачи
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    # финализируем активные сессии
    finalize_sessions()
    conn.close()
    print("✅ Мониторинг корректно остановлен")


if __name__ == "__main__":
    asyncio.run(main())
