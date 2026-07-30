# TEST STUB — 本地/staging 冒烟用。生产已有真 models.py（用户/review/plan 表），勿部署本文件。
# 用与 pay.py 相同的 wujing.db（WUJING_DB_PATH）建极简 users/reviews 表，够跑通 server 导入与游客链路。
import os, sqlite3, uuid, datetime

DB_PATH = os.environ.get("WUJING_DB_PATH",
                         os.path.join(os.environ.get("WUJING_BASE_DIR", "/tmp/wj"), "wujing.db"))


def _db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, created_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS reviews(
            id TEXT PRIMARY KEY, user_id TEXT, teacher_key TEXT, score REAL,
            dims TEXT, problems TEXT, highlights TEXT, cards TEXT,
            status TEXT DEFAULT 'processing', created_at TEXT)""")
        con.commit()
    finally:
        con.close()


def create_user(email, pw_hash):
    uid = str(uuid.uuid4())
    con = _db()
    try:
        con.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                    (uid, email, pw_hash, datetime.datetime.now().isoformat()))
        con.commit()
        return uid
    finally:
        con.close()


def get_user_by_email(email):
    con = _db()
    try:
        return con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    finally:
        con.close()


def get_user_by_id(uid):
    con = _db()
    try:
        return con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    finally:
        con.close()


def create_review(review_id, user_id, teacher_key):
    con = _db()
    try:
        con.execute("INSERT INTO reviews(id,user_id,teacher_key,status,created_at) "
                    "VALUES(?,?,?,'processing',?)",
                    (review_id, user_id, teacher_key, datetime.datetime.now().isoformat()))
        con.commit()
    finally:
        con.close()


def get_review(review_id):
    con = _db()
    try:
        return con.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
    finally:
        con.close()


def get_user_reviews(user_id):
    con = _db()
    try:
        return con.execute("SELECT * FROM reviews WHERE user_id=? ORDER BY created_at DESC",
                           (user_id,)).fetchall()
    finally:
        con.close()


def update_review_status(review_id, status):
    con = _db()
    try:
        con.execute("UPDATE reviews SET status=? WHERE id=?", (status, review_id))
        con.commit()
    finally:
        con.close()


def get_practice_progress(review_id):
    return []


def upsert_practice_task(review_id, day, task_index, completed):
    return True


def get_user_stats(user_id):
    return {"total_reviews": 0, "avg_score": 0}
