import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    total REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL
);
"""


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_user(conn, username, password_hash):
    cur = conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
    return cur.lastrowid


def find_user(conn, username):
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def create_order(conn, user_id, items):
    total = sum(price * qty for _, qty, price in items)
    order_id = conn.execute("INSERT INTO orders (user_id, total) VALUES (?, ?)", (user_id, total)).lastrowid
    for sku, qty, _ in items:
        conn.execute("INSERT INTO order_items (order_id, sku, quantity) VALUES (?, ?, ?)", (order_id, sku, qty))
    return order_id


def list_orders(conn, user_id):
    orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    result = []
    for order in orders:
        items = conn.execute("SELECT sku, quantity FROM order_items WHERE order_id = ? ORDER BY id",
                             (order["id"],)).fetchall()
        result.append({"id": order["id"], "total": order["total"], "items": [dict(i) for i in items]})
    return result
