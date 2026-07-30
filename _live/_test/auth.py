# TEST STUB — 本地/staging 冒烟用。生产已有真 auth.py（JWT），勿部署本文件。
# 用简单 HMAC 签名的 token 模拟，够跑通「登录/游客」两条链路。
import hmac, hashlib, base64, json, time

_SECRET = b"wujing-test-secret-not-for-prod"


def hash_password(pw):
    return "sha256$" + hashlib.sha256(pw.encode()).hexdigest()


def verify_password(pw, h):
    return hash_password(pw) == h


def create_token(user_id, email=""):
    payload = {"user_id": user_id, "email": email, "ts": int(time.time())}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()[:16]
    return body + "." + sig


def decode_token(token):
    body, _, sig = token.partition(".")
    exp = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(exp, sig):
        raise ValueError("bad signature")
    return json.loads(base64.urlsafe_b64decode(body.encode()).decode())
