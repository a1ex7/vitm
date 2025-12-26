import sqlite3
import pandas as pd
import pytz
import numpy as np
from datetime import datetime, timedelta
import gradio as gr
import plotly.graph_objects as go

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
        end = now
    elif preset == "Последние 5 часов":
        start = now - timedelta(hours=5)
        end = now
    elif preset == "Последние 10 часов":
        start = now - timedelta(hours=10)
        end = now
    elif preset == "Текущий день":
        start = now.replace(hour=0, minute=0, second=0)
        end = now
    elif preset == "Прошлый день":
        yesterday = now.date() - timedelta(days=1)
        start = LOCAL_TZ.localize(datetime.combine(yesterday, datetime.min.time()))
        end = start.replace(hour=23, minute=55)
    elif preset == "Текущая неделя":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0)
        end = now
    else:
        return gr.update(), gr.update()

    start = round_down_5min(start)
    end = round_up_5min(end)

    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

# --------------------------------------------------
# Data
# --------------------------------------------------
def load_users():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT id, username FROM users WHERE ACTIVE = 1", conn)
    conn.close()
    return dict(zip(df.id, df.username))

USER_MAP = load_users()

def load_statuses(start_dt, end_dt):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT user_id, date, status FROM online_statuses", conn)
    conn.close()
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["status_num"] = df["status"].map({"online": 1, "offline": 0})
    return df[(df.date >= start_dt) & (df.date <= end_dt)]

def load_sessions(start_dt, end_dt):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT user_id, started_at, ended_at, duration FROM online_sessions", conn)
    conn.close()
    if df.empty:
        return df
    df["started_at"] = pd.to_datetime(df["started_at"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["ended_at"] = pd.to_datetime(df["ended_at"], utc=True).dt.tz_convert(LOCAL_TZ)
    df = df[(df["ended_at"] >= start_dt) & (df["started_at"] <= end_dt)]
    return df

# --------------------------------------------------
# Plotly heatmap timeline
# --------------------------------------------------
def build_plotly_timeline(start_time, end_time, step_sec):
    start_dt = LOCAL_TZ.localize(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))
    end_dt = min(LOCAL_TZ.localize(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")), now_local())

    df = load_statuses(start_dt, end_dt)
    if df.empty:
        return go.Figure()

    df_sessions = load_sessions(start_dt, end_dt)

    time_index = pd.date_range(start=start_dt, end=end_dt, freq=f"{int(step_sec)}s", tz=LOCAL_TZ)
    timeline = pd.DataFrame(index=time_index)

    for uid in df.user_id.unique():
        events = df[df.user_id == uid].sort_values("date").drop_duplicates(subset=["date"], keep="last").set_index("date")
        label = USER_MAP.get(uid, f"User {uid}")
        timeline[label] = events.status_num.reindex(time_index, method="ffill")

    fig = go.Figure()

    # Heatmap
    fig.add_trace(go.Heatmap(
        z=timeline.T.values,
        x=timeline.index,
        y=[USER_MAP.get(uid, f"User {uid}") for uid in df.user_id.unique()],
        colorscale="Greens",
        colorbar=dict(title="Online (1)/Offline (0)"),
        hoverongaps=False
    ))

    # Overlay uptime from sessions
    for _, row in df_sessions.iterrows():
        user_label = USER_MAP.get(row.user_id)
        if user_label not in timeline.columns:
            continue
        # clip to period
        s = max(row.started_at, start_dt)
        e = min(row.ended_at, end_dt)
        if e <= s:
            continue
        fig.add_trace(go.Scatter(
            x=[s, e],
            y=[user_label, user_label],
            mode="lines",
            line=dict(color="lime", width=6),
            hoverinfo="skip",
            showlegend=False
        ))

    fig.update_layout(
        yaxis=dict(title="User"),
        xaxis=dict(title="Time"),
        title=f"Telegram Online Timeline\n{start_dt.strftime('%Y-%m-%d %H:%M:%S')} — {end_dt.strftime('%Y-%m-%d %H:%M:%S')}",
        height=400 + 40*len(timeline.columns),
        template="plotly_white"
    )

    return fig

# --------------------------------------------------
# Gradio UI
# --------------------------------------------------
with gr.Blocks(title="Telegram Online Timeline") as demo:
    gr.Markdown("## 📊 Telegram Online Status Timeline (Plotly)")

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
        maximum=60,
        value=5,
        step=1,
        label="Шаг (секунды)"
    )

    auto = gr.Checkbox(label="Auto-refresh", value=False)
    plot = gr.Plot()
    btn = gr.Button("Обновить")

    # Preset -> update times
    preset.change(fn=calc_range, inputs=preset, outputs=[start_time, end_time])
    demo.load(fn=calc_range, inputs=preset, outputs=[start_time, end_time])

    # Build plot on click
    btn.click(fn=build_plotly_timeline, inputs=[start_time, end_time, step], outputs=plot)

    # Auto-refresh timer
    timer = gr.Timer(5)
    timer.tick(
        fn=lambda s, e, st, a: build_plotly_timeline(s, e, st) if a else gr.update(),
        inputs=[start_time, end_time, step, auto],
        outputs=plot
    )

demo.launch()
