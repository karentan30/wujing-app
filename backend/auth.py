import jwt
import hashlib
import os
from datetime import datetime, timedelta

JWT_SECRET = os.environ.get("JWT_SECRET", "wujing-jwt-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt + ":" + h

def verify_password(password: str, hash_str: str) -> bool:
    parts = hash_str.split(":", 1)
    if len(parts) != 2:
        return False
    salt, h = parts
    return h == hashlib.sha256((salt + password).encode()).hexdigest()

def create_token(user_id: int, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
