import sqlite3
import pandas as pd
import pytz
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

DB_FILE = "online_statuses.db"
LOCAL_TZ = pytz.timezone("Europe/Kiev")

# --- Параметры периода для анализа ---
# Можно менять на нужный диапазон, формат 'YYYY-MM-DD HH:MM:SS' (локальное время)
START_TIME = "2025-12-22 06:30:00"
END_TIME   = "2025-12-22 10:00:00"
TIME_STEP = "5s"  # или '30s'

# --- Загружаем данные ---
conn = sqlite3.connect(DB_FILE)
df_status = pd.read_sql_query("SELECT * FROM online_statuses", conn)
df_sessions = pd.read_sql_query("SELECT * FROM online_sessions", conn)
df_users = pd.read_sql_query("SELECT id, username FROM users", conn)

conn.close()

# пример
# {1: '@Viktoriia_dreams', 2: '@Prado_ua'}
user_map = dict(zip(df_users['id'], df_users['username']))

# --- Преобразуем даты в локальный часовой пояс ---
df_status['date'] = pd.to_datetime(df_status['date'], utc=True).dt.tz_convert(LOCAL_TZ)
df_status['status_num'] = df_status['status'].map({'online': 1, 'offline': 0})

df_sessions['started_at'] = pd.to_datetime(df_sessions['started_at'], utc=True).dt.tz_convert(LOCAL_TZ)
df_sessions['ended_at'] = pd.to_datetime(df_sessions['ended_at'], utc=True).dt.tz_convert(LOCAL_TZ)

# --- Фильтруем по периоду ---
start_dt = LOCAL_TZ.localize(datetime.strptime(START_TIME, "%Y-%m-%d %H:%M:%S"))
end_dt = LOCAL_TZ.localize(datetime.strptime(END_TIME, "%Y-%m-%d %H:%M:%S"))

# Ограничение конца текущим временем
end_dt = min(end_dt, datetime.now(LOCAL_TZ))

df_status = df_status[(df_status['date'] >= start_dt) & (df_status['date'] <= end_dt)]
df_sessions = df_sessions[
    (df_sessions['started_at'] <= end_dt) & (df_sessions['ended_at'] >= start_dt)
]

# --- Процент онлайн ---
print("=== Процент онлайн по пользователям ===")
for u in df_status['user_id'].unique():
    user_data = df_status[df_status['user_id'] == u]
    online_count = user_data['status_num'].sum()
    total_count = len(user_data)
    perc = online_count / total_count * 100 if total_count > 0 else 0
    print(f"User {u}: онлайн {online_count}/{total_count} ({perc:.1f}%)")

# --- Корреляция статусов ---
df_pivot = df_status.pivot_table(index='date', columns='user_id', values='status_num', fill_value=0)
print("\n=== Корреляция статусов пользователей ===")
print(df_pivot.corr())

# --- Совпадения онлайн ---
print("\n=== Совпадения во времени ===")
for ts, row in df_pivot.iterrows():
    online_users = row[row == 1].index.tolist()
    if len(online_users) > 1:
        print(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} — одновременно онлайн: {online_users}")

# --- Общий uptime ---
print("\n=== Общий uptime по пользователям ===")
for u in df_sessions['user_id'].unique():
    user_sessions = df_sessions[df_sessions['user_id'] == u]
    # корректируем сессии по периоду
    total_seconds = 0
    for _, r in user_sessions.iterrows():
        s = max(r['started_at'], start_dt)
        e = min(r['ended_at'], end_dt)
        total_seconds += (e - s).total_seconds()
    hours = total_seconds / 3600
    print(f"User {u}: {hours:.2f} часов онлайн")

# Prepare data
time_index = pd.date_range(
    start=start_dt,
    end=end_dt,
    freq=TIME_STEP,
    tz=LOCAL_TZ
)

timeline = pd.DataFrame(index=time_index)

for user_id in df_status['user_id'].unique():
    user_events = (
        df_status[df_status['user_id'] == user_id]
        .sort_values('date')
        .drop_duplicates(subset=['date'], keep='last')
        .set_index('date')
    )

    label = user_map.get(user_id, f'User {user_id}')
    timeline[label] = (
        user_events['status_num']
        .reindex(time_index, method='ffill')
    )


# --- Heatmap онлайн-статусов ---
plt.figure(figsize=(15, len(df_pivot.columns)*0.5 + 2))
time_labels = df_pivot.index.strftime('%H:%M')
plt.imshow(df_pivot.T, aspect='auto', cmap='Greens', interpolation='nearest')
plt.colorbar(label='Online status (1=online, 0=offline)')
plt.yticks(ticks=np.arange(len(df_pivot.columns)), labels=df_pivot.columns)
plt.xticks(
    ticks=np.arange(0, len(time_labels), max(1,len(time_labels)//20)),
    labels=time_labels[::max(1,len(time_labels)//20)],
    rotation=45
)
plt.title(f"Онлайн-статусы пользователей (Heatmap)\n{START_TIME} — {END_TIME}")
plt.xlabel("Time")
plt.ylabel("User ID")
plt.tight_layout()
plt.savefig("analyze/online_statuses_heatmap.png")
plt.close()

#  Heatmap timeline
plt.figure(figsize=(15, len(timeline.columns)*0.5 + 2))

plt.imshow(
    timeline.T,
    aspect='auto',
    cmap='Greens',
    interpolation='nearest'
)

plt.colorbar(label='Online (1) / Offline (0)')
plt.yticks(
    ticks=np.arange(len(timeline.columns)),
    labels=timeline.columns
)

xticks = np.arange(0, len(timeline.index), max(1, len(timeline)//20))
plt.xticks(
    ticks=xticks,
    labels=timeline.index[xticks].strftime('%H:%M'),
    rotation=45
)

plt.title(f"Online Status Heatmap (Timeline)\n{START_TIME} — {END_TIME}")
plt.xlabel("Time")
plt.ylabel("User ID")
plt.tight_layout()
plt.savefig("analyze/online_statuses_heatmap_timeline.png")
plt.close()

print("\n✅ Графики сохранены")
