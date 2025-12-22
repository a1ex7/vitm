import sqlite3
import pandas as pd
import pytz
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import gradio as gr

DB_FILE = "online_statuses.db"
LOCAL_TZ = pytz.timezone("Europe/Kiev")

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
        end = start + timedelta(hours=1)

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
    df = pd.read_sql_query("SELECT id, username FROM users", conn)
    conn.close()
    return dict(zip(df.id, df.username))

USER_MAP = load_users()

def load_statuses(start_dt, end_dt):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT user_id, date, status FROM online_statuses",
        conn
    )
    conn.close()

    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["status_num"] = df["status"].map({"online": 1, "offline": 0})
    return df[(df.date >= start_dt) & (df.date <= end_dt)]

# --------------------------------------------------
# Plot
# --------------------------------------------------
def build_heatmap(start_time, end_time, step_sec):
    start_dt = LOCAL_TZ.localize(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))
    end_dt = min(
        LOCAL_TZ.localize(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")),
        now_local()
    )

    df = load_statuses(start_dt, end_dt)
    if df.empty:
        return None

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
            .drop_duplicates("date")
            .set_index("date")
        )
        label = USER_MAP.get(uid, f"User {uid}")
        timeline[label] = events.status_num.reindex(time_index, method="ffill")

    fig, ax = plt.subplots(figsize=(15, len(timeline.columns)*0.5 + 2))
    im = ax.imshow(timeline.T, aspect="auto", cmap="Greens", interpolation="nearest")

    plt.colorbar(im, ax=ax, label="Online (1) / Offline (0)")
    ax.set_yticks(range(len(timeline.columns)))
    ax.set_yticklabels(timeline.columns)

    xticks = np.arange(0, len(timeline), max(1, len(timeline)//20))
    ax.set_xticks(xticks)
    ax.set_xticklabels(
        [timeline.index[i].strftime("%H:%M") for i in xticks],
        rotation=45
    )

    ax.set_title(
        f"Online Status Heatmap\n"
        f"{start_dt.strftime('%Y-%m-%d %H:%M')} — {end_dt.strftime('%Y-%m-%d %H:%M')}"
    )
    ax.set_xlabel("Time")
    ax.set_ylabel("User")

    plt.tight_layout()
    return fig

# --------------------------------------------------
# Gradio UI
# --------------------------------------------------
with gr.Blocks(title="Telegram Online Timeline") as demo:
    gr.Markdown("## 📊 Telegram Online Timeline")

    preset = gr.Dropdown(
        label="Быстрый выбор диапазона",
        choices=[
            "Текущий час",
            "Последние 3 часа",
            "Последние 5 часов",
            "Последние 10 часов",
            "Текущий день",
            "Прошлый день",
            "Текущая неделя"
        ],
        value="Последние 3 часа"
    )

    with gr.Row():
        start_time = gr.Textbox(label="Start time")
        end_time = gr.Textbox(label="End time")

    step = gr.Slider(
        minimum=1,
        maximum=3600,
        value=60,
        step=1,
        label="Шаг (секунды)"
    )

    auto = gr.Checkbox(label="Auto-refresh", value=False)
    plot = gr.Plot()
    btn = gr.Button("🔄 Обновить")

    preset.change(
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

demo.launch()
