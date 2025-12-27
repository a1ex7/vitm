import sqlite3

def connect(db_file):
    conn = sqlite3.connect(db_file)
    return conn

def init_db(conn):
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS online_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        status TEXT,
        UNIQUE(user_id, date, status)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS online_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        started_at TEXT,
        ended_at TEXT,
        duration INTEGER,
        UNIQUE(user_id, started_at)
    )
    """)

    conn.commit()
