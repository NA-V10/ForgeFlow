from app import auth, db
from app.web import App

app = App()
STATE = {"conn": None}


def get_conn():
    if STATE["conn"] is None:
        STATE["conn"] = db.connect()
    return STATE["conn"]


@app.get("/health")
def health(body, headers):
    return 200, {"status": "ok"}


@app.post("/login")
def login(body, headers):
    user = auth.authenticate(get_conn(), body.get("username", ""), body.get("password", ""))
    if user is None:
        return 401, {"error": "invalid credentials"}
    return 200, {"user": user["username"]}


@app.get("/orders")
def orders(body, headers):
    user_id = int(headers.get("X-User-Id", 0))
    return 200, {"orders": db.list_orders(get_conn(), user_id)}
