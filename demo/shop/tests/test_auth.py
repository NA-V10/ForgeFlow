from app import auth, db


def make_conn():
    conn = db.connect()
    db.create_user(conn, "alice", auth.hash_password("s3cret"))
    return conn


def test_authenticate_success():
    assert auth.authenticate(make_conn(), "alice", "s3cret")["username"] == "alice"


def test_authenticate_wrong_password():
    assert auth.authenticate(make_conn(), "alice", "nope") is None


def test_authenticate_unknown_user():
    assert auth.authenticate(make_conn(), "bob", "s3cret") is None
