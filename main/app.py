import asyncio
import pandas as pd
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# === Настройки ===
api_id = 29477438      # <-- вставь свой api_id из my.telegram.org
api_hash = "b35cd0b313143486e8ca98cbb275ee2f"
USERS = ["@Viktoriia_dreams", "@Prado_ua"]  # Telegram username, @ник или user ID
CHECK_INTERVAL = 5     # секунд
TOTAL_DURATION = 2*60*60     # секунд (сколько времени мониторить)

status_history = {user: [] for user in USERS}


async def get_online_status(client, user):
    """
    Проверяет статус пользователя в Telegram.
    Возвращает True (онлайн) или False (оффлайн).
    """
    try:
        entity = await client.get_entity(user)
        status = entity.status
        return status is not None and status.__class__.__name__ == "UserStatusOnline"
    except FloodWaitError as e:
        print(f"FloodWaitError: ждём {e.seconds} секунд")
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"Ошибка при проверке {user}: {e}")
        return False


async def monitor_user(client, user):
    end_time = datetime.now().timestamp() + TOTAL_DURATION
    while datetime.now().timestamp() < end_time:
        online = await get_online_status(client, user)
        status_history[user].append((datetime.now(), online))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {user} — {'Online' if online else 'Offline'}")
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    async with TelegramClient("monitor_session", api_id, api_hash) as client:
        tasks = [monitor_user(client, user) for user in USERS]
        await asyncio.gather(*tasks)

    # === Анализ ===
    df = pd.DataFrame()
    for user, records in status_history.items():
        df[user] = pd.Series([int(s) for _, s in records])

    print("\n=== Статистика ===")
    for user in USERS:
        online_times = sum(1 for _, s in status_history[user] if s)
        total = len(status_history[user])
        print(f"{user}: онлайн {online_times}/{total} раз ({online_times / total * 100:.1f}%)")

    print("\n=== Корреляция онлайн-статусов ===")
    print(df.corr())

    print("\n=== Совпадения во времени ===")
    timestamps = [t for t, _ in status_history[USERS[0]]]
    for i, t in enumerate(timestamps):
        online_users = [u for u in USERS if status_history[u][i][1]]
        if len(online_users) > 1:
            print(f"{t.strftime('%H:%M:%S')} — одновременно онлайн: {', '.join(online_users)}")


if __name__ == "__main__":
    asyncio.run(main())
