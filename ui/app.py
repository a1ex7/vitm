import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
import gradio as gr
from collector.config import DB_FILE, LOCAL_TZ

# --------------------------------------------------
# Utils
# --------------------------------------------------
def round_down_5min(dt: datetime):
    return dt - timedelta(
        minutes=dt.minute % 5,
        seconds=dt.second,
        microseconds=dt.microsecond
    )

def round_up_5min(dt: datetime):
    if dt.minute % 5 == 0 and dt.second == 0:
        return dt.replace(second=0, microsecond=0)
    return round_down_5min(dt + timedelta(minutes=5))

def now_local():
    return datetime.now(LOCAL_TZ)

# --------------------------------------------------
# Fast ranges
# --------------------------------------------------
def calc_range(preset: str):
    now = now_local()

    if preset == "Текущий час":
        start = now.replace(minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Рабочий день":
        start = now.replace(hour=7, minute=0, second=0)
        end = now.replace(hour=19, minute=0, second=0)

    elif preset == "Последний 1 час":
        start = now - timedelta(hours=1)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Последние 3 часа":
        start = now - timedelta(hours=3)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Последние 5 часов":
        start = now - timedelta(hours=5)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Последние 10 часов":
        start = now - timedelta(hours=10)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Текущий день":
        start = now.replace(hour=0, minute=0, second=0)
        end = now.replace(hour=23, minute=55, second=0)

    elif preset == "Прошлый день":
        yesterday = now.date() - timedelta(days=1)
        start = LOCAL_TZ.localize(datetime.combine(yesterday, datetime.min.time()))
        end = start.replace(hour=23, minute=55)

    elif preset == "Текущая неделя":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=6, hours=23, minutes=55)

    else:
        return gr.update(), gr.update()

    start = round_down_5min(start)
    end = round_up_5min(end)

    return (
        start.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
    )

# --------------------------------------------------
# Data
# --------------------------------------------------
def load_users():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT id, username FROM users WHERE active = 1", conn)
    conn.close()
    return dict(zip(df.id, df.username))

USER_MAP = load_users()

def load_statuses(start_dt, end_dt, active_user_ids):
    conn = sqlite3.connect(DB_FILE)

    ids_tuple = tuple(active_user_ids)

    df = pd.read_sql_query(
        f"SELECT user_id, date, status FROM online_statuses WHERE user_id IN {ids_tuple}",
        conn
    )
    conn.close()

    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["status_num"] = df["status"].map({"online": 1, "offline": 0})
    return df[(df.date >= start_dt) & (df.date <= end_dt)]

def load_sessions(start_dt, end_dt, active_user_ids):
    conn = sqlite3.connect(DB_FILE)

    ids_tuple = tuple(active_user_ids)

    df = pd.read_sql_query(
        f"""
        SELECT user_id, started_at, ended_at, duration
        FROM online_sessions
        WHERE user_id IN {ids_tuple}
        """,
        conn
    )

    conn.close()

    if df.empty:
        return df

    # даты → datetime UTC → LOCAL_TZ
    df["started_at"] = pd.to_datetime(df["started_at"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["ended_at"] = pd.to_datetime(df["ended_at"], utc=True).dt.tz_convert(LOCAL_TZ)

    # оставляем только сессии, пересекающие период
    df = df[
        (df["ended_at"] >= start_dt) &
        (df["started_at"] <= end_dt)
    ]

    return df


# --------------------------------------------------
# Plot
# --------------------------------------------------
def build_heatmap(start_time, end_time, step_sec):
    start_dt = LOCAL_TZ.localize(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))
    end_dt = min(
        LOCAL_TZ.localize(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")),
        now_local()
    )

    df = load_statuses(start_dt, end_dt, USER_MAP.keys())
    if df.empty:
        return None

    df_sessions = load_sessions(start_dt, end_dt, USER_MAP.keys())

    time_index = pd.date_range(
        start=start_dt,
        end=end_dt,
        freq=f"{int(step_sec)}s",
        tz=LOCAL_TZ
    )

    timeline = pd.DataFrame(index=time_index)

    for uid in df.user_id.unique():
        events = (
            df[df.user_id == uid]
            .sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .set_index("date")
        )
        label = USER_MAP.get(uid, f"User {uid}")
        timeline[label] = events.status_num.reindex(time_index, method="ffill")

    fig, ax = plt.subplots(figsize=(15, len(timeline.columns)*0.5 + 2))
    im = ax.imshow(timeline.T, aspect="auto", cmap="Greens", interpolation="nearest")

    # === OVERLAY ONLINE SESSIONS ===
    user_ypos = {user: i for i, user in enumerate(timeline.columns)}

    for _, row in df_sessions.iterrows():
        user_label = USER_MAP.get(row["user_id"])
        if user_label not in user_ypos:
            continue

        y = user_ypos[user_label]

        # обрезаем сессию по выбранному периоду
        s = max(row["started_at"], start_dt)
        e = min(row["ended_at"], end_dt)

        if e <= s:
            continue

        # перевод времени в координаты heatmap
        x_start = np.searchsorted(timeline.index, s)
        x_end = np.searchsorted(timeline.index, e)

        rect = Rectangle(
            (x_start, y - 0.2),  # x, y
            x_end - x_start,  # width
            0.4,  # height
            facecolor="lime",
            alpha=0.35,
            edgecolor=None
        )

        ax.add_patch(rect)

    # Uptime for Users
    user_labels = []

    for user_label in timeline.columns:
        user_id = {v: k for k, v in USER_MAP.items()}.get(user_label)

        if df_sessions.empty or user_id not in df_sessions["user_id"].values:
            label_text = f"{user_label}"
            user_labels.append(label_text)
            continue

        user_sess = df_sessions[df_sessions["user_id"] == user_id]

        # корректируем сессии по границам периода
        total_online_seconds = 0
        for _, r in user_sess.iterrows():
            s = max(r["started_at"], start_dt)
            e = min(r["ended_at"], end_dt)
            delta = (e - s).total_seconds()
            if delta > 0:
                total_online_seconds += delta

        hours = int(total_online_seconds // 3600)
        minutes = int((total_online_seconds % 3600) // 60)

        label_text = f"{user_label}\n{hours}ч {minutes}мин"
        user_labels.append(label_text)

    # Используем подписи на оси Y
    plt.yticks(
        ticks=np.arange(len(timeline.columns)),
        labels=user_labels
    )

    # plt.colorbar(im, ax=ax, label="Online (1) / Offline (0)")
    # ax.set_yticks(range(len(timeline.columns)))
    # ax.set_yticklabels(timeline.columns)

    xticks = np.arange(0, len(timeline), max(1, len(timeline)//20))
    ax.set_xticks(xticks)
    ax.set_xticklabels(
        [timeline.index[i].strftime("%H:%M") for i in xticks],
        rotation=45
    )

    ax.set_title(
        f"Online Status Heatmap\n"
        f"{start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%Y-%m-%d %H:%M')}"
    )
    # ax.set_xlabel("Time")
    # ax.set_ylabel("User")

    plt.tight_layout()
    plt.close(fig)

    return fig

# --------------------------------------------------
# Gradio UI
# --------------------------------------------------
with gr.Blocks(title="Telegram Online Timeline") as demo:
    gr.Markdown("## 📊 Telegram Online Timeline")



    with gr.Row():
        with gr.Column():
            preset = gr.Dropdown(
                label="Быстрый выбор диапазона",
                choices=[
                    "Текущий час",
                    "Рабочий день",
                    "Последний 1 час",
                    "Последние 3 часа",
                    "Последние 5 часов",
                    "Последние 10 часов",
                    "Текущий день",
                    "Прошлый день",
                    "Текущая неделя"
                ],
                value="Последние 3 часа"
            )

        with gr.Column():
            with gr.Row():
                start_time = gr.Textbox(label="Start time")
                end_time = gr.Textbox(label="End time")

    with gr.Row():
        with gr.Column():
            step = gr.Slider(
                minimum=1,
                maximum=60,
                value=5,
                step=1,
                label="Шаг (секунды)"
            )
            auto = gr.Checkbox(label="Auto-refresh", value=False)

    plot = gr.Plot()
    btn = gr.Button("Обновить")

    preset.change(
        fn=calc_range,
        inputs=preset,
        outputs=[start_time, end_time]
    )

    demo.load(
        fn=calc_range,
        inputs=preset,
        outputs=[start_time, end_time]
    )

    btn.click(
        fn=build_heatmap,
        inputs=[start_time, end_time, step],
        outputs=plot
    )

    timer = gr.Timer(5)
    timer.tick(
        fn=lambda s, e, st, a: build_heatmap(s, e, st) if a else gr.update(),
        inputs=[start_time, end_time, step, auto],
        outputs=plot
    )

demo.launch(
    server_name="0.0.0.0",
    server_port=7860,
    share=False
)
