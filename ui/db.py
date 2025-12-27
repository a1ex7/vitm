import sqlite3

DB_FILE = "online_statuses_temp.db"

def read_df(query):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df
