import hashlib

from app import db


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate(conn, username, password):
    user = db.find_user(conn, username)
    if user is None:
        return None
    if user["password_hash"] != hash_password(password):
        return None
    return user
