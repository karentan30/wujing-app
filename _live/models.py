import sqlite3
import os
import json
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wujing.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""")
        # 幂等补列（存量库可能无此字段）
        for ddl in (
            "ALTER TABLE users ADD COLUMN free_credits INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN ref_code TEXT",
            "ALTER TABLE users ADD COLUMN member_expires TEXT",
            "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
            "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass
        conn.commit()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reviews (
              id TEXT PRIMARY KEY,
              user_id INTEGER REFERENCES users(id),
              teacher_key TEXT NOT NULL,
              score INTEGER,
              dims TEXT,
              problems TEXT,
              highlights TEXT,
              status TEXT DEFAULT processing,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS practice_progress (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              review_id TEXT REFERENCES reviews(id),
              day INTEGER NOT NULL,
              task_index INTEGER NOT NULL,
              completed BOOLEAN DEFAULT 0,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

def create_user(email, password_hash):
    with get_db() as conn:
        try:
            cur = conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, password_hash))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

def get_user_by_email(email):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

def create_review(review_id, user_id, teacher_key):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reviews (id, user_id, teacher_key) VALUES (?, ?, ?)",
            (review_id, user_id, teacher_key)
        )
        return review_id

def get_review(review_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return dict(row) if row else None

def get_user_reviews(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def update_review_status(review_id, status, score=None, dims=None, problems=None, highlights=None):
    with get_db() as conn:
        if status == "completed" and score is not None:
            conn.execute(
                "UPDATE reviews SET status=?, score=?, dims=?, problems=?, highlights=? WHERE id=?",
                (status, score, json.dumps(dims) if dims else None,
                 json.dumps(problems) if problems else None,
                 json.dumps(highlights) if highlights else None, review_id)
            )
        else:
            conn.execute("UPDATE reviews SET status=? WHERE id=?", (status, review_id))

def get_practice_progress(review_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM practice_progress WHERE review_id = ? ORDER BY day, task_index",
            (review_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def upsert_practice_task(review_id, day, task_index, completed):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM practice_progress WHERE review_id=? AND day=? AND task_index=?",
            (review_id, day, task_index)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE practice_progress SET completed=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (completed, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO practice_progress (review_id, day, task_index, completed) VALUES (?, ?, ?, ?)",
                (review_id, day, task_index, completed)
            )

def get_user_stats(user_id):
    with get_db() as conn:
        total_dances = conn.execute(
            "SELECT COUNT(*) as c FROM reviews WHERE user_id=? AND status='completed'",
            (user_id,)
        ).fetchone()["c"]

        total_practices = conn.execute(
            """SELECT COUNT(*) as c FROM practice_progress pp
               JOIN reviews r ON pp.review_id = r.id
               WHERE r.user_id=? AND pp.completed=1""",
            (user_id,)
        ).fetchone()["c"]

        recent_reviews = conn.execute(
            """SELECT id, score, created_at FROM reviews
               WHERE user_id=? AND status='completed'
               ORDER BY created_at DESC LIMIT 20""",
            (user_id,)
        ).fetchall()

        improvement = []
        for r in reversed(recent_reviews):
            improvement.append({"id": r["id"], "score": r["score"], "date": r["created_at"]})

        return {
            "total_dances": total_dances,
            "total_practices": total_practices,
            "improvement": improvement
        }
