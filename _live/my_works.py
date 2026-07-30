#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 个人库 + 跟练进步曲线（登录后拆过的舞进「我的练习库」）

方案依据：docs/埋点与个人库落地-0730.md §方案②。

现状链路已有 user_id 贯穿（/api/decompose 游客可传，登录则绑 user_id → run_decompose
写进 decompose.json）。所以「入库」不需要新流程，只补三处：
  ① 列表接口   GET  /api/my-works             —— 喂 my-works-demo.html
  ② 游客→登录  POST /api/claim-dance          —— 游客拆的舞归属到自己名下
  ③ 分数历史   POST /api/practice/{did}/score  —— 进步曲线的唯一真数据源

两张表（IF NOT EXISTS，跟现有 pay.get_db() 同库 wujing.db）：
  - my_works        冗余索引（数据源仍是 decompose.json，避免列表页 N 次读文件）
  - practice_scores ★进步曲线的唯一真数据源（每次跟练一条达标度）

诚实边界：
  - 达标度分数由「舞镜AI」算（跟练时逐帧关节角度 vs 拆解标准角度比对）；MVP 阶段可由
    前端传入自评/复用拆解达标度，先把 attempt_no 序列（回来练的次数=真信号）跑起来。
    不编造分数：没练过 curve=[]，前端据此显示「单次·再练一次解锁曲线」。
  - 全程不暴露 MediaPipe 等底层实现，对外统一称「舞镜AI」。

挂载与钩子（由主控在 server.py 统一收口，本文件不碰 server.py）：
  - server.py 顶部：from my_works import router as my_works_router, init_library_tables
  - init_orders_table() 之后：init_library_tables()
  - app.include_router(pay_router) 附近：app.include_router(my_works_router)
  - run_decompose 完成、user_id 非空时调 upsert_my_work(user_id, result)（见文末说明）
"""
import os
import json

from fastapi import APIRouter, Depends, HTTPException

# 与 server.py / pay.py 保持同一路径 / 同一库 / 同一鉴权
from pay import get_db as _get_db
from auto_decompose import get_decompose

BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DATA_DIR = os.path.join(BASE_DIR, "data")

# get_current_user 定义在 server.py（依赖 models.get_user_by_id）。为不 import server（循环），
# 这里自带一份等价实现：解 JWT → 查用户。与 server.get_current_user 行为一致。
from fastapi import Header
from auth import decode_token
from models import get_user_by_id


def get_current_user(authorization: str = Header(None)):
    """登录鉴权（与 server.get_current_user 等价）。个人库是登录后能力。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization format")
    try:
        payload = decode_token(token)
        user = get_user_by_id(payload["user_id"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


router = APIRouter(tags=["my-works"])


# ══════════════════════════════════════════════════════════════
# 建表（幂等 · IF NOT EXISTS · 跟着 init_orders_table 一起初始化）
# ══════════════════════════════════════════════════════════════
def init_library_tables():
    """个人库两张表。幂等建表，绝不破坏已有数据。"""
    con = _get_db()
    try:
        # ① 我的库索引（冗余索引；数据源仍是 decompose.json，避免列表页 N 次读文件）
        con.execute("""CREATE TABLE IF NOT EXISTS my_works(
            dance_id   TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            title      TEXT,
            genre      TEXT,
            cover      TEXT,
            duration_s REAL,
            n_phrases  INTEGER,
            is_paid    INTEGER DEFAULT 0,
            is_public  INTEGER DEFAULT 0,          -- 发到广场（plaza 用 my_works.is_public）
            created_at TEXT DEFAULT (datetime('now')),
            expire_at  TEXT                          -- 免费作品 7 天清理；付费=NULL(永久)
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_myworks_user ON my_works(user_id, created_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_myworks_public ON my_works(is_public, created_at DESC)")

        # ② 跟练分数历史（★进步曲线的唯一真数据源）
        con.execute("""CREATE TABLE IF NOT EXISTS practice_scores(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dance_id    TEXT NOT NULL,
            user_id     INTEGER NOT NULL,
            attempt_no  INTEGER NOT NULL,           -- 该舞第几次跟练（attempt_no>=2 即 aha）
            score       REAL NOT NULL,              -- 本次达标度 0-100（舞镜AI 或自评）
            angles_json TEXT,                        -- 本次逐段角度快照（可选·逐关节纠错）
            mode        TEXT,                        -- normal/slow/mirror
            created_at  TEXT DEFAULT (datetime('now'))
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_scores_dance ON practice_scores(dance_id, user_id, attempt_no)")

        # 存量 my_works 表可能缺 is_public → 幂等补列（不破坏已有数据）
        try:
            con.execute("ALTER TABLE my_works ADD COLUMN is_public INTEGER DEFAULT 0")
        except Exception:
            pass
        con.commit()
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════
# helper：拆解完成 / claim 时把 decompose.json 冗余进索引表
# ══════════════════════════════════════════════════════════════
def _dance_is_paid(dance_id):
    """该 dance 是否已存在一条 paid 订单（复用 pay.py orders 表；与 server._dance_is_paid 等价）。
    自带一份避免 import server 造成循环依赖。"""
    try:
        con = _get_db()
        try:
            row = con.execute(
                "SELECT 1 FROM orders WHERE dance_id=? AND status='paid' LIMIT 1",
                (str(dance_id),)).fetchone()
            return bool(row)
        finally:
            con.close()
    except Exception:
        return False


def upsert_my_work(user_id, d):
    """把一支拆解产物冗余进 my_works 索引表。

    调用点：run_decompose 完成且 user_id 非空时（登录用户一拆完就自动进库）；
            claim_dance 回填时。游客（user_id 为 None/'guest'）不入库 —— 等 claim 后再入。

    is_paid=1 → 永久保存（expire_at=NULL）；免费 → 7 天后清理（expire_at=now+7d）。
    幂等：INSERT OR REPLACE by dance_id 主键；重复拆同一支只留最新。
    """
    # 游客 / 匿名占位不入库（生产 user_id 为 INTEGER；此处不强转，兼容任何真实用户 id 类型）
    if not user_id or str(user_id) in ("guest", "None", ""):
        return
    uid = user_id
    did = d.get("id")
    if not did:
        return
    is_paid = 1 if _dance_is_paid(did) else 0
    title = d.get("title")
    genre = d.get("genre")
    dur = d.get("dur")
    n_phrases = len(d.get("phrases", []) or [])
    cover = f"/api/decompose/{did}/frame/p1"
    con = _get_db()
    try:
        # 保留 is_public（若此前已发广场，重拆不该把它抹掉）
        prev = con.execute("SELECT is_public FROM my_works WHERE dance_id=?", (did,)).fetchone()
        is_public = int(prev["is_public"]) if prev and prev["is_public"] is not None else 0
        if is_paid:
            con.execute(
                "INSERT OR REPLACE INTO my_works"
                "(dance_id,user_id,title,genre,cover,duration_s,n_phrases,is_paid,is_public,expire_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (did, uid, title, genre, cover, dur, n_phrases, 1, is_public))
        else:
            con.execute(
                "INSERT OR REPLACE INTO my_works"
                "(dance_id,user_id,title,genre,cover,duration_s,n_phrases,is_paid,is_public,expire_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,datetime('now','+7 days'))",
                (did, uid, title, genre, cover, dur, n_phrases, 0, is_public))
        con.commit()
    finally:
        con.close()


def _curve_for(con, dance_id, user_id):
    """取该舞历次跟练分数（按 attempt_no 升序）= 进步曲线。"""
    scores = con.execute(
        "SELECT score FROM practice_scores WHERE dance_id=? AND user_id=? "
        "ORDER BY attempt_no ASC", (dance_id, user_id)).fetchall()
    return [round(float(s["score"]), 1) for s in scores]


# ══════════════════════════════════════════════════════════════
# 接口 ① 我的作品列表 —— 喂 my-works-demo.html
# ══════════════════════════════════════════════════════════════
@router.get("/api/my-works")
def my_works(user: dict = Depends(get_current_user)):
    """登录用户的个人库。每支带进步曲线 curve[]（历次跟练分数·按 attempt_no 升序）。
    curve 为真数据：没练过就是 []（前端据此显示「单次·再练一次解锁曲线」）。"""
    out = []
    con = _get_db()
    try:
        rows = con.execute(
            "SELECT * FROM my_works WHERE user_id=? ORDER BY created_at DESC",
            (user["id"],)).fetchall()
        for r in rows:
            curve = _curve_for(con, r["dance_id"], user["id"])
            out.append({
                "dance_id": r["dance_id"],
                "title": r["title"],
                "genre": r["genre"],
                "cover": r["cover"] or f"/api/decompose/{r['dance_id']}/frame/p1",
                "duration_s": r["duration_s"],
                "n_phrases": r["n_phrases"],
                "is_paid": bool(r["is_paid"]),
                "is_public": bool(r["is_public"]) if r["is_public"] is not None else False,
                "created_at": r["created_at"],
                "expire_at": r["expire_at"],
                "curve": curve,                                   # [] = 还没练过
                "best_score": max(curve) if curve else None,
                "first_score": curve[0] if curve else None,
                "practice_count": len(curve),
            })
        saved = sum(1 for r in rows if r["is_paid"])
    finally:
        con.close()
    return {"works": out, "count": len(out), "saved": saved}


# ══════════════════════════════════════════════════════════════
# 接口 ② 游客拆的舞 → 注册后归属自己（个人库能攒东西的前提）
# ══════════════════════════════════════════════════════════════
@router.post("/api/claim-dance")
def claim_dance(data: dict, user: dict = Depends(get_current_user)):
    """游客拆的舞（user_id=None/'guest'），注册/登录后一键归属到自己名下。
    否则登录用户攒不到东西 = 个人库空。"""
    did = (data or {}).get("dance_id")
    if not did:
        raise HTTPException(status_code=400, detail="缺少 dance_id")
    d = get_decompose(did)
    if not d:
        raise HTTPException(status_code=404, detail="dance not found")
    owner = d.get("user_id")
    # 匿名（None/''/'guest'）或已属于本人才可 claim；属于他人 → 拒
    if owner not in (None, "", "guest", user["id"]) and str(owner) != str(user["id"]):
        raise HTTPException(status_code=403, detail="已归属其他用户")
    # 回写 decompose.json 的 user_id + 建 my_works 索引
    d["user_id"] = user["id"]
    try:
        with open(os.path.join(DATA_DIR, did, "decompose.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回写归属失败: {e}")
    upsert_my_work(user["id"], d)
    return {"status": "ok", "dance_id": did}


# ══════════════════════════════════════════════════════════════
# 接口 ③ 提交一次跟练分数 —— 进步曲线写入 + aha 埋点
# ══════════════════════════════════════════════════════════════
@router.post("/api/practice/{did}/score")
def submit_score(did: str, data: dict, user: dict = Depends(get_current_user)):
    """记一次跟练达标度 → 写 practice_scores（进步曲线数据源）→ 服务端补 aha 埋点。

    分数来源（诚实）：由「舞镜AI」逐帧关节角度比对得出，或 MVP 阶段前端传自评/复用拆解达标度。
    第 2 次及以上练同一支（attempt_no>=2）即 practice_repeat；本次高于历史最高即 score_improved。
    这两个是全套最重要的 aha 事件，服务端在此补打确保不漏。
    """
    data = data or {}
    try:
        score = float(data.get("score", 0))
    except Exception:
        raise HTTPException(status_code=400, detail="score 必须是数字")
    score = max(0.0, min(100.0, score))
    mode = data.get("mode", "normal")

    con = _get_db()
    try:
        row = con.execute(
            "SELECT COALESCE(MAX(attempt_no),0) n, COALESCE(MAX(score),0) best "
            "FROM practice_scores WHERE dance_id=? AND user_id=?",
            (did, user["id"])).fetchone()
        attempt_no = int(row["n"]) + 1
        prev_best = float(row["best"])
        con.execute(
            "INSERT INTO practice_scores(dance_id,user_id,attempt_no,score,angles_json,mode) "
            "VALUES(?,?,?,?,?,?)",
            (did, user["id"], attempt_no, score,
             json.dumps(data.get("angles")) if data.get("angles") is not None else None,
             mode))
        con.commit()
    finally:
        con.close()

    improved = bool(score > prev_best and attempt_no >= 2)

    # 服务端埋点：练完 + 第二次练(aha) + 分数提升(价值兑现)。埋点异常不影响返回。
    try:
        from analytics import track
        track(user["id"], "practice_complete",
              {"dance_id": did, "attempt_no": attempt_no, "score": score, "mode": mode})
        if attempt_no >= 2:
            track(user["id"], "practice_repeat", {"dance_id": did, "attempt_no": attempt_no})
        if improved:
            track(user["id"], "score_improved",
                  {"dance_id": did, "prev_best": prev_best, "new_score": score,
                   "delta": round(score - prev_best, 1)})
    except Exception:
        pass

    return {"attempt_no": attempt_no, "score": score, "prev_best": prev_best,
            "improved": improved}


# ══════════════════════════════════════════════════════════════
# 接口 ④（附赠·plaza 依赖）从个人库设一支为公开 / 取消公开
#   plaza 用 my_works.is_public，不新建 plaza_posts 表（MVP 更省）。
# ══════════════════════════════════════════════════════════════
@router.post("/api/my-works/{did}/publish")
def set_public(did: str, data: dict, user: dict = Depends(get_current_user)):
    """把我的一支舞设为公开（发到广场）/取消。body: {public: true|false}。"""
    public = 1 if (data or {}).get("public", True) else 0
    con = _get_db()
    try:
        r = con.execute("SELECT user_id FROM my_works WHERE dance_id=?", (did,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="作品不在你的库中")
        if str(r["user_id"]) != str(user["id"]):
            raise HTTPException(status_code=403, detail="Access denied")
        con.execute("UPDATE my_works SET is_public=? WHERE dance_id=?", (public, did))
        con.commit()
    finally:
        con.close()
    return {"status": "ok", "dance_id": did, "is_public": bool(public)}


@router.get("/api/plaza")
def plaza(tab: str = "recommend", genre: str = None, limit: int = 30):
    """作品广场：公开作品 feed（is_public=1）。真实数据 —— 无作品就返回空列表，
    绝不编造互动数。每支带真实达标度（best_score，来自 practice_scores）。
    genre 传 'recommend'/None = 全部；否则按舞种过滤。"""
    limit = max(1, min(60, int(limit)))
    con = _get_db()
    try:
        if genre and genre not in ("recommend", "all", ""):
            rows = con.execute(
                "SELECT * FROM my_works WHERE is_public=1 AND genre=? "
                "ORDER BY created_at DESC LIMIT ?", (genre, limit)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM my_works WHERE is_public=1 "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            curve = _curve_for(con, r["dance_id"], r["user_id"])
            out.append({
                "dance_id": r["dance_id"],
                "title": r["title"],
                "genre": r["genre"],
                "cover": r["cover"] or f"/api/decompose/{r['dance_id']}/frame/p1",
                "duration_s": r["duration_s"],
                "n_phrases": r["n_phrases"],
                "best_score": max(curve) if curve else None,   # 真达标度·没练过=None
            })
    finally:
        con.close()
    return {"posts": out, "count": len(out)}
