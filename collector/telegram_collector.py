import asyncio
import signal
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import UserStatusOnline, UserStatusOffline

from config import API_ID, API_HASH, CHECK_INTERVAL, DB_FILE, LOCAL_TZ, UTC
from db import connect, init_db

stop_event = asyncio.Event()
active_sessions = {}

conn = connect(DB_FILE)
init_db(conn)
cur = conn.cursor()


def shutdown():
    print("⛔ Stopping collector...")
    stop_event.set()


def get_users():
    cur.execute("SELECT username FROM users WHERE active = 1")
    return [r[0] for r in cur.fetchall()]


def get_user_id(username):
    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("INSERT INTO users(username) VALUES (?)", (username,))
    conn.commit()
    return cur.lastrowid


def save_status(username, status, ts):
    user_id = get_user_id(username)

    cur.execute("""
        INSERT OR IGNORE INTO online_statuses(user_id, date, status)
        VALUES (?, ?, ?)
    """, (
        user_id,
        ts.replace(microsecond=0).astimezone(UTC).isoformat(),
        status
    ))
    conn.commit()


def save_session(username, status, ts):
    user_id = get_user_id(username)

    if status == "online":
        active_sessions.setdefault(username, ts)
        return

    if status == "offline" and username in active_sessions:
        start = active_sessions.pop(username)
        duration = int((ts - start).total_seconds())

        if duration > 0:
            cur.execute("""
                INSERT OR IGNORE INTO online_sessions
                (user_id, started_at, ended_at, duration)
                VALUES (?, ?, ?, ?)
            """, (
                user_id,
                start.astimezone(UTC).isoformat(),
                ts.astimezone(UTC).isoformat(),
                duration
            ))
            conn.commit()


async def check_user(client, username):
    while not stop_event.is_set():
        entity = await client.get_entity(username)
        now = datetime.now(UTC)

        if isinstance(entity.status, UserStatusOnline):
            status = "online"
            ts = now
            print(
                f"[{now}] {username} — "
                f"Online"
            )
        else:
            status = "offline"
            ts = getattr(entity.status, "was_online", now)
            print(
                f"[{now}] {username} — "
                f"Offline "
                f"(last seen: {ts.strftime('%Y-%m-%d %H:%M:%S')})"
            )

        save_status(username, status, ts)
        save_session(username, status, ts)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def main():
    async with TelegramClient("collector", API_ID, API_HASH) as client:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, shutdown)

        users = get_users()

        if not users:
            print("⚠️ No active users to monitor")
            await stop_event.wait()
            return

        tasks = [
            asyncio.create_task(check_user(client, user))
            for user in users
        ]

        await stop_event.wait()
        for t in tasks:
            t.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    conn.close()
    print("✅ Collector stopped")


if __name__ == "__main__":
    asyncio.run(main())
