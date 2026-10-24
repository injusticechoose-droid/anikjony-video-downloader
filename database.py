import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB = "users.db"

def get_conn():
    # WAL মোড ডেটাবেস লক হওয়া প্রতিরোধ করে
    conn = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL)""")
        conn.commit()
    finally: 
        conn.close()

def add_user(username, password):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", 
                     (username, generate_password_hash(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError: 
        return False
    finally: 
        conn.close()

def check_user(username, password):
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, password FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row[1], password): 
            return row[0]
        return None
    finally: 
        conn.close()
