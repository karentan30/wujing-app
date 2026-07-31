#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 群舞班级点评 编排层（B端营收主力线）

产品决策（见 docs/群舞班级整合-0730.md）：不走「一段群舞自动分人」，改走
「每人各自上传独舞片段 → 逐人跑已有 auto_decompose 管线 → 汇总成班级报告」。
本文件只加「编排层」：建班 / 发码 / 学员加入 / 上传归属 / 批量评分（限流队列）/ 汇总。
核心评分能力复用 auto_decompose.run_decompose（豆包 vision + MediaPipe 实测角度 + DeepSeek）。

对外话术只说「舞镜AI」，绝不暴露 MediaPipe / 豆包 / DeepSeek。评分口径严格对齐
report.html 的 DATA[] 契约（sc/ah/sp/as_/kn/mv 六维 + radar + fb），否则前端 meter/雷达全错。

⚠️ 并发：原单人线用无上限 threading（server.py 每上传起一个 daemon Thread）。
班级 10 人同传/同评会起 10+ 子进程（每个还 fork ffmpeg + mediapipe venv）→ OOM。
本文件用「有界队列 + Semaphore 限流的工作线程池」收口所有班级评分，全局并发 ≤ MAX_CONCURRENCY。

挂载方式（主控在 server.py 收口，本文件不碰 server.py）：
    from group_review import router as group_router, init_group_tables, set_decompose_runner
    init_group_tables()
    # 复用 server 已 import 的 run_decompose，注入进来（避免本模块直接 import 造成循环/重复副作用）
    from auto_decompose import run_decompose, get_decompose
    set_decompose_runner(run_decompose, get_decompose)
    app.include_router(group_router)
所有接口前缀 /api/class 与 /api/join，与单人线不冲突。
"""
import os
import re
import json
import time
import queue
import uuid
import sqlite3
import secrets
import threading
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends
from fastapi.responses import JSONResponse

# ─────────────────────────────────────────────────────────────────────────────
# 配置 / DB（复用 pay.py 同一个 wujing.db，同 WAL 短连接模式；表全部 IF NOT EXISTS）
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("WUJING_DB_PATH", os.path.join(BASE_DIR, "wujing.db"))

# 并发上限：班级批量评分全局同时最多几人（每人 = 1×ffmpeg 抽帧 + mediapipe venv + vision 并发）。
# 默认 3，可用 env 覆盖。绝不能无上限（10 人同传 OOM 的根因）。
MAX_CONCURRENCY = int(os.environ.get("WUJING_GROUP_CONCURRENCY", "3"))
# 队列容量：待评分任务的最大积压，超出直接拒（防内存无界堆积）。
QUEUE_MAXSIZE = int(os.environ.get("WUJING_GROUP_QUEUE_MAX", "200"))
# 单人上传体积上限，沿用单人线 500MB。
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

# 班级码字符集：排除易混字符 0/O/1/I/L，6 位。
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LEN = 6


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    """短连接（与 pay.py 同款）。调用方负责 with 关闭。"""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
    except Exception:
        pass
    return con


def init_group_tables():
    """建 4 张群舞表，全部 IF NOT EXISTS（幂等，绝不 DROP，绝不碰单人线的表）。"""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = get_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS classes(
            id            TEXT PRIMARY KEY,
            teacher_uid   TEXT,                       -- 建班老师（登录用户 id）
            dance_name    TEXT NOT NULL,
            genre         TEXT DEFAULT 'guofeng',     -- 喂评分话术：guofeng / kpop
            ref_mode      TEXT DEFAULT 'ai',          -- teacher_video / library / ai
            ref_video_id  TEXT,                       -- 参考示范视频（可空）
            brand_json    TEXT,                       -- {schoolName,teacherName,motto,logoUrl}
            invite_code   TEXT UNIQUE NOT NULL,        -- 6位易读码
            max_students  INTEGER DEFAULT 60,
            deadline      TEXT,                        -- 截止时间（可空）
            status        TEXT DEFAULT 'open',         -- open / scoring / done
            created_at    TEXT
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cls_teacher ON classes(teacher_uid)")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cls_code ON classes(invite_code)")

        con.execute("""CREATE TABLE IF NOT EXISTS class_members(
            id            TEXT PRIMARY KEY,
            class_id      TEXT NOT NULL,
            student_uid   TEXT,                        -- 登录用户 id（游客为空）
            guest_token   TEXT,                        -- 游客/学员访问自己那页的 token
            nickname      TEXT,
            real_name     TEXT,                        -- 可选真实姓名（仅老师可见）
            join_at       TEXT,
            status        TEXT DEFAULT 'joined',       -- joined/uploaded/scoring/scored/failed
            decompose_id  TEXT,                        -- 挂到已有单人分析
            score_json    TEXT,                        -- 归一后的六维 + fb（喂 report.html）
            rank          INTEGER,
            error         TEXT,
            updated_at    TEXT
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mem_class ON class_members(class_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mem_token ON class_members(guest_token)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mem_decomp ON class_members(decompose_id)")

        con.execute("""CREATE TABLE IF NOT EXISTS class_reports(
            id          TEXT PRIMARY KEY,
            class_id    TEXT NOT NULL,
            version     INTEGER DEFAULT 1,            -- 支持同班多次测评的纵向对比
            report_json TEXT,                          -- 汇总缓存（report.html 契约）
            created_at  TEXT
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_rep_class ON class_reports(class_id)")

        con.execute("""CREATE TABLE IF NOT EXISTS teacher_subs(
            teacher_uid  TEXT PRIMARY KEY,
            plan         TEXT DEFAULT 'trial',        -- trial/studio/institution/chain
            seats        INTEGER DEFAULT 10,
            period_start TEXT,
            period_end   TEXT,
            status       TEXT DEFAULT 'active'        -- active/expired/canceled
        )""")
        con.commit()
    finally:
        con.close()


# ─────────────────────────────────────────────────────────────────────────────
# 评分能力注入（复用 server 已 import 的 auto_decompose，避免循环 import / 重复副作用）
# ─────────────────────────────────────────────────────────────────────────────
_run_decompose = None   # 签名: (did, video_path, user_id, title, genre)
_get_decompose = None   # 签名: (did) -> dict|None


def set_decompose_runner(run_decompose_fn, get_decompose_fn):
    """主控在挂载时注入 auto_decompose 的两个函数。测试里也用它注入 stub。"""
    global _run_decompose, _get_decompose
    _run_decompose = run_decompose_fn
    _get_decompose = get_decompose_fn


# ─────────────────────────────────────────────────────────────────────────────
# 认证：软依赖 server 的 get_optional_user（登录绑账号，游客可玩）。
# 为避免与 server 循环 import，用可注入的 hook；未注入时回退到本地宽松解析。
# ─────────────────────────────────────────────────────────────────────────────
_optional_user_fn = None


def set_optional_user_resolver(fn):
    """主控可注入 server.get_optional_user（同一套 token）。不注入则用宽松兜底。"""
    global _optional_user_fn
    _optional_user_fn = fn


def _resolve_user(authorization):
    if _optional_user_fn:
        try:
            return _optional_user_fn(authorization)
        except Exception:
            return None
    # 兜底：尝试用 auth.decode_token + models.get_user_by_id（与单人线同 token）
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        import auth as _auth
        import models as _models
        payload = _auth.decode_token(token)
        return _models.get_user_by_id(payload["user_id"])
    except Exception:
        return None


def _uid_of(user):
    if not user:
        return None
    try:
        return user["id"]
    except Exception:
        return getattr(user, "id", None)


def _require_teacher(authorization, cls):
    """校验调用者是该班级的老师（teacher_uid）。否则 403。返回 uid。"""
    user = _resolve_user(authorization)
    uid = _uid_of(user)
    if uid is None or str(cls.get("teacher_uid") or "") != str(uid):
        raise HTTPException(status_code=403, detail="只有该班老师可以操作")
    return uid


# ─────────────────────────────────────────────────────────────────────────────
# 评分归一：把 auto_decompose 产出（每段 MediaPipe 实测角度 + coach 文本）
# 归一成 report.html 六维契约。口径固定（doc 四·注意）：
#   sc 满分10% 目标≥6% | ah 满分100% 目标≥80% | sp 满分20次 目标≥12
#   as_ 满分0.5 目标≥0.35 | kn 1=直 目标≤0.92 | mv 满分0.3 目标≥0.18
# 诚实原则：能测的（臂高/屈膝/S曲线/动作量）从真实角度算；测不到的（旋转次数）
# 给保守估计并如实标记 estimated，绝不凭空编一个漂亮数字。
# ─────────────────────────────────────────────────────────────────────────────
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _collect_angles(decompose):
    """从 decompose.phrases[].angles 收集每个关节的时间序列。"""
    series = {}
    for p in (decompose.get("phrases") or []):
        a = p.get("angles") or {}
        for k, v in a.items():
            if v is None:
                continue
            series.setdefault(k, []).append(float(v))
    return series


def score_from_decompose(decompose):
    """核心归一：decompose.json → 六维分（report.html 契约）+ 是否有真实测量。
    返回 dict：{sc,ah,sp,as_,kn,mv,radar,measured,fb_raw,comment}。
    measured=True 表示有 MediaPipe 骨架真数据；False 表示纯 vision 兜底（会标注）。
    """
    series = _collect_angles(decompose)
    measured = bool(series)

    # 各关节均值（左右取平均，缺失回退到另一侧）
    def jm(*keys):
        vals = []
        for k in keys:
            m = _mean(series.get(k, []))
            if m is not None:
                vals.append(m)
        return _mean(vals)

    shoulder = jm("right_shoulder", "left_shoulder")   # 抬臂角，越大臂越高
    elbow = jm("right_elbow", "left_elbow")            # 手肘伸展，越大越展开
    knee = jm("right_knee", "left_knee")               # 膝角，180≈直
    torso = _mean(series.get("torso_tilt", []))        # 躯干倾斜度（三道弯依据）

    # ── ah 臂高 0-100%（目标≥80）：肩外展角 0..170° 线性映射到 0..100 ──
    if shoulder is not None:
        ah = _clamp(round(shoulder / 170.0 * 100.0), 0, 100)
    else:
        ah = 60  # 无骨架兜底给中位，标 estimated

    # ── kn 屈膝 1=直（目标≤0.92）：膝角 180°=1.0，越屈越小 ──
    if knee is not None:
        kn = _clamp(round(knee / 180.0, 2), 0.5, 1.0)
    else:
        kn = 0.95

    # ── as_ 臂展 0-0.5（目标≥0.35）：手肘伸直程度 → 张开度 ──
    if elbow is not None:
        as_ = _clamp(round(elbow / 180.0 * 0.5, 3), 0.0, 0.5)
    else:
        as_ = 0.28

    # ── sc S曲线 0-10%（目标≥6）：躯干倾斜（三道弯）越大越有 S；
    #    torso_tilt 通常 0..30°，映射到 0..10% ──
    if torso is not None:
        sc = _clamp(round(torso / 30.0 * 10.0, 1), 0.0, 10.0)
    else:
        sc = 1.5

    # ── mv 动作量 0-0.3（目标≥0.18）：段间关节角度变化幅度（标准差）归一 ──
    #    把每个关节序列的相邻段变化平均起来，再归一到 0..0.3。
    deltas = []
    for k, seq in series.items():
        if len(seq) >= 2:
            step = _mean([abs(seq[i + 1] - seq[i]) for i in range(len(seq) - 1)])
            if step is not None:
                deltas.append(step)
    if deltas:
        # 经验：段间平均角度变化 30° ≈ 满动作量 0.3
        mv = _clamp(round(_mean(deltas) / 30.0 * 0.3, 3), 0.0, 0.3)
    else:
        mv = 0.14

    # ── sp 旋转次数 0-20（目标≥12）：无法从静帧真测旋转，诚实用「动作量」保守估计，
    #    并标 estimated=True。绝不编一个漂亮的高分。 ──
    sp = int(_clamp(round(mv / 0.3 * 12), 0, 20))
    sp_estimated = True

    # radar 六维 0-100（report.html createRadar 用）：把各维归一到百分比
    radar = [
        round(sc / 10.0 * 100),           # S曲线
        round(ah),                        # 臂高（已是 %）
        round(sp / 20.0 * 100),           # 旋转
        round(as_ / 0.5 * 100),           # 臂展
        round(_clamp((1 - (kn - 0.8) / 0.2) * 100, 0, 100)),  # 屈膝（越直越低分）
        round(mv / 0.3 * 100),            # 动作量
    ]
    radar = [int(_clamp(x, 0, 100)) for x in radar]

    # 综合分 0-10：六维加权平均（S曲线是敦煌/古典灵魂，权重高）
    w = [0.30, 0.18, 0.12, 0.13, 0.12, 0.15]
    comp = sum(r / 100.0 * wi for r, wi in zip(radar, w)) * 10
    comp = round(_clamp(comp, 0.0, 10.0), 1)

    coach = decompose.get("coach") or {}
    return {
        "sc": {"v": sc, "pct": f"{round(sc / 10 * 100)}%"},
        "ah": {"v": ah, "pct": f"{ah}%"},
        "sp": {"v": sp, "pct": f"{round(sp / 20 * 100)}%"},
        "as_": {"v": as_, "pct": f"{round(as_ / 0.5 * 100)}%"},
        "kn": {"v": kn, "pct": f"{round(_clamp((1 - (kn - 0.8) / 0.2) * 100, 0, 100))}%"},
        "mv": {"v": mv, "pct": f"{round(mv / 0.3 * 100)}%"},
        "radar": radar,
        "score": f"{comp}",
        "measured": measured,
        "sp_estimated": sp_estimated,
        "comment": coach.get("comment", ""),
        "coach_good": coach.get("good", []) or [],
        "coach_improve": coach.get("improve", []) or [],
    }


def _build_fb(scored):
    """把 coach.improve（真实 vision 点评）整成 report.html 的 fb 三档 P0/P1/P2。
    诚实：直接用 AI 点评原文，不足则以维度短板补，不编套话。"""
    improve = list(scored.get("coach_improve") or [])
    # 若 vision 点评不足 3 条，用维度短板补足（按离目标差距排序）
    dims = [
        ("S曲线", scored["sc"]["v"], 6.0, "推胯出三道弯，对镜练身体起伏"),
        ("臂高", scored["ah"]["v"], 80.0, "手臂上提至肩线以上，肩别耸"),
        ("旋转", scored["sp"]["v"], 12.0, "加平转/踏步翻练习，落地接亮相定拍"),
        ("臂展", scored["as_"]["v"] / 0.5 * 100, 70.0, "手臂大胆展开，立腕撑圆虎口"),
        ("动作量", scored["mv"]["v"] / 0.3 * 100, 60.0, "增加纵向起伏，别只平推"),
    ]
    gaps = sorted(
        [(name, tgt - cur, tip) for name, cur, tgt, tip in dims if cur < tgt],
        key=lambda x: -x[1],
    )
    fb = []
    tags = ["P0", "P1", "P2"]
    for i in range(3):
        if i < len(improve):
            # 用真实 AI 点评作为标题+详情
            txt = str(improve[i]).strip()
            title = txt[:18]
            fb.append([tags[i], title, txt])
        elif gaps:
            name, gap, tip = gaps.pop(0)
            fb.append([tags[i], f"{name}—待加强", tip])
    if not fb:
        fb = [["P0", "整体稳定", scored.get("comment") or "动作到位，继续保持节奏与延伸。"]]
    return fb


# ─────────────────────────────────────────────────────────────────────────────
# 并发队列：全局有界工作池，Semaphore 限流。所有班级评分任务走这里，防 OOM。
# ─────────────────────────────────────────────────────────────────────────────
class ScoreQueue:
    """有界任务队列 + 固定数量工作线程 + 全局 Semaphore 限流。
    - put(job) 入队；超容量抛 queue.Full（上层转 429）。
    - 每个 job 是一个 member 的评分任务：跑 run_decompose → 归一 → 回写 status。
    - 工作线程数 == MAX_CONCURRENCY，Semaphore 再兜一层（防未来多入口共享）。
    """

    def __init__(self, max_concurrency=MAX_CONCURRENCY, maxsize=QUEUE_MAXSIZE):
        self.max_concurrency = max(1, max_concurrency)
        self._q = queue.Queue(maxsize=maxsize)
        self._sem = threading.BoundedSemaphore(self.max_concurrency)
        self._workers = []
        self._started = False
        self._lock = threading.Lock()
        # 可观测：当前在跑 / 排队中
        self._active = 0
        self._active_lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._started:
                return
            for i in range(self.max_concurrency):
                t = threading.Thread(target=self._worker, name=f"wj-score-{i}", daemon=True)
                t.start()
                self._workers.append(t)
            self._started = True

    def submit(self, fn, *args):
        """入队一个评分任务。返回 True/False（False=队列满，调用方转 429）。"""
        self.start()
        try:
            self._q.put_nowait((fn, args))
            return True
        except queue.Full:
            return False

    def stats(self):
        return {"queued": self._q.qsize(), "active": self._active,
                "max_concurrency": self.max_concurrency}

    def _worker(self):
        while True:
            fn, args = self._q.get()
            # Semaphore 限流：即便工作线程数被外部改动，也不超上限
            with self._sem:
                with self._active_lock:
                    self._active += 1
                try:
                    fn(*args)
                except Exception:
                    traceback.print_exc()
                finally:
                    with self._active_lock:
                        self._active -= 1
                    self._q.task_done()


_score_queue = ScoreQueue()


# ─────────────────────────────────────────────────────────────────────────────
# 单个 member 的评分任务（队列 worker 执行）
# ─────────────────────────────────────────────────────────────────────────────
def _score_member_task(class_id, member_id, decompose_id, video_path, title, genre):
    """跑一个学员：run_decompose（复用单人管线）→ 归一六维 → 回写 class_members。"""
    _set_member_status(member_id, "scoring")
    try:
        if _run_decompose is None or _get_decompose is None:
            raise RuntimeError("decompose runner 未注入（挂载时需 set_decompose_runner）")
        # 复用已有单人管线：豆包 vision + MediaPipe 实测角度 + DeepSeek 故事卡
        _run_decompose(decompose_id, video_path, None, title, genre)
        d = _get_decompose(decompose_id)
        if not d or d.get("status") != "completed":
            raise RuntimeError((d or {}).get("error", "评分未完成（检出失败，请重传更清晰的单人全身视频）")[:300])
        scored = score_from_decompose(d)
        fb = _build_fb(scored)
        # decompose 若检出到风格，回写覆盖班级默认（不改班级，只标记该生）
        det = (d.get("genre") or genre)
        payload = {
            "sc": scored["sc"], "ah": scored["ah"], "sp": scored["sp"],
            "as_": scored["as_"], "kn": scored["kn"], "mv": scored["mv"],
            "radar": scored["radar"], "score": scored["score"],
            "fb": fb, "measured": scored["measured"], "sp_estimated": scored["sp_estimated"],
            "genre": det, "comment": scored["comment"],
            "videoUrl": f"api/decompose/{decompose_id}/clip/full",
        }
        _save_member_score(member_id, payload)
        _set_member_status(member_id, "scored")
    except Exception as e:
        _set_member_status(member_id, "failed", error=str(e)[:400])
    # 每人评完检查：是否全班齐了 → 自动生成/刷新汇总报告
    try:
        _maybe_finalize(class_id)
    except Exception:
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────────────────────
# DB 小工具
# ─────────────────────────────────────────────────────────────────────────────
def _get_class(class_id):
    con = get_db()
    try:
        return con.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()
    finally:
        con.close()


def _get_class_by_code(code):
    con = get_db()
    try:
        return con.execute("SELECT * FROM classes WHERE invite_code=?", (code,)).fetchone()
    finally:
        con.close()


def _members(class_id):
    con = get_db()
    try:
        return con.execute(
            "SELECT * FROM class_members WHERE class_id=? ORDER BY join_at", (class_id,)
        ).fetchall()
    finally:
        con.close()


def _get_member(member_id):
    con = get_db()
    try:
        return con.execute("SELECT * FROM class_members WHERE id=?", (member_id,)).fetchone()
    finally:
        con.close()


def _get_member_by_token(class_id, token):
    con = get_db()
    try:
        return con.execute(
            "SELECT * FROM class_members WHERE class_id=? AND guest_token=?", (class_id, token)
        ).fetchone()
    finally:
        con.close()


def _set_member_status(member_id, status, error=None):
    con = get_db()
    try:
        con.execute("UPDATE class_members SET status=?, error=?, updated_at=? WHERE id=?",
                    (status, error, _now(), member_id))
        con.commit()
    finally:
        con.close()


def _save_member_score(member_id, payload):
    con = get_db()
    try:
        con.execute("UPDATE class_members SET score_json=?, updated_at=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), _now(), member_id))
        con.commit()
    finally:
        con.close()


def _gen_code():
    """生成唯一 6 位班级码（易读字符集），冲突重试。"""
    con = get_db()
    try:
        for _ in range(30):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            row = con.execute("SELECT 1 FROM classes WHERE invite_code=?", (code,)).fetchone()
            if not row:
                return code
    finally:
        con.close()
    # 极端兜底：加时间戳后缀
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


# ─────────────────────────────────────────────────────────────────────────────
# 汇总层：算排名 / 班级均值 / 统一短板 / 统一训练方案（一次 DeepSeek）
# 输出严格对齐 report.html 契约（class + students[]）。
# ─────────────────────────────────────────────────────────────────────────────
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _unified_plan_via_deepseek(dance_name, genre, common_weakness, dims_avg):
    """把班级公共短板喂 DeepSeek 出一份统一训练方案（≈¥0.002）。失败给规则兜底。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    fallback = [
        {"step": "热身", "min": 3, "desc": "肩胯开合 + 脊柱波浪，唤醒三道弯发力链"},
        {"step": "分解", "min": 8, "desc": common_weakness or "针对全班最弱维度做慢速分解练习"},
        {"step": "连贯", "min": 6, "desc": "半速跟练整支，重点保持短板维度不塌"},
        {"step": "收势", "min": 3, "desc": "定亮相 2 拍，沉气收势，眼神追手"},
    ]
    if not key:
        return fallback
    try:
        import urllib.request
        prompt = (
            f"你是资深舞蹈老师。一个《{dance_name}》（{genre}）班级的舞镜AI测评显示全班"
            f"公共短板：{common_weakness}。各维度班级均值：{json.dumps(dims_avg, ensure_ascii=False)}。"
            "请给一份 20 分钟的统一课堂训练方案，针对公共短板。只输出严格JSON数组不要markdown：\n"
            '[{"step":"步骤名","min":分钟数,"desc":"一句话怎么练(具体·不空泛)"}]'
        )
        body = json.dumps({"model": "deepseek-chat",
                           "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 700, "temperature": 0.6}).encode()
        req = urllib.request.Request(DEEPSEEK_URL, data=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        raw = json.loads(urllib.request.urlopen(req, timeout=60).read())["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
        plan = json.loads(raw.strip())
        if isinstance(plan, list) and plan:
            return plan
    except Exception:
        pass
    return fallback


def _identify_common_weakness(scored_members):
    """找全班最差的公共维度（离目标差距最大的），出一句人话短板描述。"""
    if not scored_members:
        return "", {}
    dims = {
        "sc": ("S曲线(三道弯)", 6.0, [m["sc"]["v"] for m in scored_members]),
        "ah": ("臂高", 80.0, [m["ah"]["v"] for m in scored_members]),
        "sp": ("旋转", 12.0, [m["sp"]["v"] for m in scored_members]),
        "mv": ("动作量", 0.18, [m["mv"]["v"] for m in scored_members]),
    }
    avg = {}
    worst = None
    for k, (label, tgt, vals) in dims.items():
        m = sum(vals) / len(vals)
        avg[k] = round(m, 3)
        gap_ratio = (tgt - m) / tgt if tgt else 0
        if worst is None or gap_ratio > worst[2]:
            worst = (label, m, gap_ratio, tgt)
    if worst and worst[2] > 0:
        weakness = f"{worst[0]}全班均值{round(worst[1], 2)}（目标≥{worst[3]}），是本班公共短板，建议统一强化。"
    else:
        weakness = "全班各维度均已达标，可进入表现力与情感表达进阶训练。"
    return weakness, avg


def build_report(class_id, persist=True):
    """汇总班级报告 JSON（report.html 契约）。只纳入已出分(scored)的学员，缺席不阻塞。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    members = _members(class_id)

    students = []
    scored_raw = []
    for m in members:
        if m["status"] != "scored" or not m["score_json"]:
            continue
        s = json.loads(m["score_json"])
        scored_raw.append(s)
        students.append({
            "member_id": m["id"],
            "name": m["nickname"] or "学员",
            "real_name": m["real_name"] or "",
            "score": s.get("score", "0"),
            "rank": 0,
            "sc": s["sc"], "ah": s["ah"], "sp": s["sp"],
            "as_": s["as_"], "kn": s["kn"], "mv": s["mv"],
            "radar": s["radar"],
            "videoUrl": s.get("videoUrl", ""),
            "poster": s.get("poster", ""),
            "bg": s.get("bg", {}),
            "fb": s.get("fb", []),
            "measured": s.get("measured", False),
            "sp_estimated": s.get("sp_estimated", True),
        })

    # 排名：按 S 曲线主指标降序（与 report.html DATA.sort 一致）
    students.sort(key=lambda x: x["sc"]["v"], reverse=True)
    for i, x in enumerate(students):
        x["rank"] = i + 1

    weakness, dims_avg = _identify_common_weakness(scored_raw)

    # 班级均值（喂总评/雷达）
    def avg_field(getter):
        vals = [getter(s) for s in scored_raw]
        return round(sum(vals) / len(vals), 3) if vals else 0

    class_avg = {
        "sCurve": avg_field(lambda s: s["sc"]["v"]),
        "armHeight": avg_field(lambda s: s["ah"]["v"]),
        "spins": avg_field(lambda s: s["sp"]["v"]),
        "armSpan": avg_field(lambda s: s["as_"]["v"]),
        "kneeBend": avg_field(lambda s: s["kn"]["v"]),
        "movement": avg_field(lambda s: s["mv"]["v"]),
    } if scored_raw else {}

    genre = cls["genre"]
    unified_plan = _unified_plan_via_deepseek(cls["dance_name"], genre, weakness, dims_avg) if scored_raw else []

    brand = {}
    try:
        brand = json.loads(cls["brand_json"]) if cls["brand_json"] else {}
    except Exception:
        brand = {}

    any_estimated = any(s.get("sp_estimated") for s in scored_raw)
    report = {
        "class": {
            "id": class_id,
            "danceName": cls["dance_name"],
            "genre": genre,
            "brand": {
                "schoolName": brand.get("schoolName", ""),
                "teacherName": brand.get("teacherName", ""),
                "motto": brand.get("motto", ""),
                "logoUrl": brand.get("logoUrl", ""),
            },
            "createdAt": cls["created_at"],
            "studentCount": len(students),
            "classAvg": class_avg,
            "commonWeakness": weakness,
            "unifiedPlan": unified_plan,
            # 诚实标注：AI 辅助评分供教学参考；旋转次数为估计值
            "disclaimer": "舞镜AI辅助评分，供教学参考，不替代老师专业判断。"
                          + ("（旋转次数为动作量估算值）" if any_estimated else ""),
        },
        "students": students,
    }

    if persist:
        con = get_db()
        try:
            row = con.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS v FROM class_reports WHERE class_id=?",
                (class_id,)).fetchone()
            ver = row["v"] if row else 1
            con.execute(
                "INSERT INTO class_reports(id,class_id,version,report_json,created_at) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), class_id, ver, json.dumps(report, ensure_ascii=False), _now()))
            con.commit()
        finally:
            con.close()
    return report


def _maybe_finalize(class_id):
    """每人评完调用：若所有已上传的成员都到终态(scored/failed)，把班级置 done 并落一版报告。"""
    members = _members(class_id)
    active = [m for m in members if m["status"] in ("uploaded", "scoring")]
    if active:
        return  # 还有人在跑，不结算
    scored = [m for m in members if m["status"] == "scored"]
    if not scored:
        return
    con = get_db()
    try:
        con.execute("UPDATE classes SET status='done' WHERE id=?", (class_id,))
        con.commit()
    finally:
        con.close()
    build_report(class_id, persist=True)


# ─────────────────────────────────────────────────────────────────────────────
# APIRouter
# ─────────────────────────────────────────────────────────────────────────────
router = APIRouter()


def _current_user(authorization: str = Header(None)):
    return _resolve_user(authorization)


def _class_progress(class_id):
    """进度看板数据（老师端轮询）。"""
    cls = _get_class(class_id)
    members = _members(class_id)
    counts = {"joined": 0, "uploaded": 0, "scoring": 0, "scored": 0, "failed": 0}
    mem_out = []
    for m in members:
        counts[m["status"]] = counts.get(m["status"], 0) + 1
        mo = {"member_id": m["id"], "nickname": m["nickname"] or "",
              "real_name": m["real_name"] or "", "status": m["status"],
              "rank": m["rank"], "error": m["error"]}
        if m["status"] == "scored" and m["score_json"]:
            try:
                mo["score"] = json.loads(m["score_json"]).get("score")
            except Exception:
                pass
        mem_out.append(mo)
    total = len(members)
    done = counts.get("scored", 0)
    return {"counts": counts, "total": total, "scored": done,
            "members": mem_out, "queue": _score_queue.stats()}


# ---------- 老师端 ----------
@router.post("/api/class/create")
async def class_create(
    dance_name: str = Form(...),
    genre: str = Form("guofeng"),
    ref_mode: str = Form("ai"),
    max_students: int = Form(60),
    deadline: str = Form(""),
    school_name: str = Form(""),
    teacher_name: str = Form(""),
    motto: str = Form(""),
    logo_url: str = Form(""),
    authorization: str = Header(None),
):
    """建班 → 返回 class_id + invite_code + 加入短链（前端据 code 生成二维码）。
    必须登录（老师身份需持久归属，游客建班会导致班级无人能管理/鉴权失效）。"""
    user = _resolve_user(authorization)
    teacher_uid = _uid_of(user)
    if teacher_uid is None:
        raise HTTPException(status_code=401, detail="请先登录后再创建班级")
    if not dance_name.strip():
        raise HTTPException(status_code=400, detail="请填写舞名")
    if genre not in ("guofeng", "kpop"):
        genre = "guofeng"
    max_students = int(_clamp(max_students, 1, 500))
    cid = "cls_" + uuid.uuid4().hex[:12]
    code = _gen_code()
    brand = {"schoolName": school_name.strip(), "teacherName": teacher_name.strip(),
             "motto": motto.strip(), "logoUrl": logo_url.strip()}
    con = get_db()
    try:
        con.execute("""INSERT INTO classes
            (id,teacher_uid,dance_name,genre,ref_mode,brand_json,invite_code,
             max_students,deadline,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, teacher_uid, dance_name.strip(), genre, ref_mode,
             json.dumps(brand, ensure_ascii=False), code, max_students,
             deadline.strip() or None, "open", _now()))
        con.commit()
    finally:
        con.close()
    join_url = f"/j/{code}"
    return {"class_id": cid, "invite_code": code, "join_url": join_url,
            "dance_name": dance_name.strip(), "genre": genre, "max_students": max_students}


@router.get("/api/class/{class_id}")
def class_detail(class_id: str, authorization: str = Header(None)):
    """班级详情 + 进度看板（老师端轮询）。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    brand = {}
    try:
        brand = json.loads(cls["brand_json"]) if cls["brand_json"] else {}
    except Exception:
        pass
    prog = _class_progress(class_id)
    return {"class": {"id": cls["id"], "dance_name": cls["dance_name"], "genre": cls["genre"],
                      "invite_code": cls["invite_code"], "status": cls["status"],
                      "max_students": cls["max_students"], "deadline": cls["deadline"],
                      "brand": brand, "created_at": cls["created_at"]},
            "progress": prog}


@router.post("/api/class/{class_id}/start-scoring")
def class_start_scoring(class_id: str, authorization: str = Header(None)):
    """触发批量评分：把所有 uploaded 的学员入队（限流队列）。缺席不阻塞。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    _require_teacher(authorization, cls)
    members = _members(class_id)
    pending = [m for m in members if m["status"] == "uploaded"]
    if not pending:
        raise HTTPException(status_code=400, detail="没有待评分的学员（需有人已上传）")
    con = get_db()
    try:
        con.execute("UPDATE classes SET status='scoring' WHERE id=?", (class_id,))
        con.commit()
    finally:
        con.close()
    queued, rejected = 0, 0
    for m in pending:
        did = m["decompose_id"]
        video_path = os.path.join(DATA_DIR, did, "input.mp4")
        ok = _score_queue.submit(_score_member_task, class_id, m["id"], did,
                                 video_path, cls["dance_name"], cls["genre"])
        if ok:
            queued += 1
        else:
            rejected += 1  # 队列满，保持 uploaded 态，稍后可重试
    return {"status": "scoring", "queued": queued, "rejected": rejected,
            "queue": _score_queue.stats()}


@router.post("/api/class/{class_id}/rescore-member")
def class_rescore_member(class_id: str, data: dict, authorization: str = Header(None)):
    """单人重跑（拍糊/检出差）。不重算全班积压，只把该生重新入队。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    _require_teacher(authorization, cls)
    member_id = data.get("member_id")
    m = _get_member(member_id) if member_id else None
    if not m or m["class_id"] != class_id:
        raise HTTPException(status_code=404, detail="学员不存在")
    if not m["decompose_id"]:
        raise HTTPException(status_code=400, detail="该学员尚未上传视频")
    did = m["decompose_id"]
    video_path = os.path.join(DATA_DIR, did, "input.mp4")
    _set_member_status(member_id, "uploaded")
    ok = _score_queue.submit(_score_member_task, class_id, member_id, did,
                             video_path, cls["dance_name"], cls["genre"])
    if not ok:
        raise HTTPException(status_code=429, detail="评分队列繁忙，请稍后重试")
    return {"status": "requeued", "member_id": member_id, "queue": _score_queue.stats()}


@router.get("/api/class/{class_id}/report")
def class_report(class_id: str, authorization: str = Header(None)):
    """拉汇总报告 JSON（喂 report.html 的 DATA[]）。优先用缓存，无则实时汇总。仅该班老师可看。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    _require_teacher(authorization, cls)
    con = get_db()
    try:
        row = con.execute(
            "SELECT report_json FROM class_reports WHERE class_id=? ORDER BY version DESC LIMIT 1",
            (class_id,)).fetchone()
    finally:
        con.close()
    if row and row["report_json"]:
        return json.loads(row["report_json"])
    # 无缓存（还没结算）→ 实时汇总当前已出分的
    return build_report(class_id, persist=False)


@router.patch("/api/class/{class_id}/brand")
def class_set_brand(class_id: str, data: dict, authorization: str = Header(None)):
    """存机构品牌（Logo/机构名/老师名/标语）——护城河体验。仅该班老师可改。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    _require_teacher(authorization, cls)
    brand = {"schoolName": (data.get("schoolName") or "").strip(),
             "teacherName": (data.get("teacherName") or "").strip(),
             "motto": (data.get("motto") or "").strip(),
             "logoUrl": (data.get("logoUrl") or "").strip()}
    con = get_db()
    try:
        con.execute("UPDATE classes SET brand_json=? WHERE id=?",
                    (json.dumps(brand, ensure_ascii=False), class_id))
        con.commit()
    finally:
        con.close()
    return {"status": "ok", "brand": brand}


@router.patch("/api/class/{class_id}/notes")
def class_set_notes(class_id: str, data: dict, authorization: str = Header(None)):
    """老师逐生备注：写进该生 score_json 的 teacher_note 字段（report.html 老师备注区）。仅老师可写。"""
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    _require_teacher(authorization, cls)
    member_id = data.get("member_id")
    note = (data.get("note") or "").strip()
    m = _get_member(member_id) if member_id else None
    if not m or m["class_id"] != class_id:
        raise HTTPException(status_code=404, detail="学员不存在")
    sj = json.loads(m["score_json"]) if m["score_json"] else {}
    sj["teacher_note"] = note
    _save_member_score(member_id, sj)
    return {"status": "ok"}


@router.get("/api/teacher/classes")
def teacher_classes(authorization: str = Header(None)):
    """老师历史班级列表 + 纵向对比（同 dance_name 多次测评的报告版本）。"""
    user = _resolve_user(authorization)
    uid = _uid_of(user)
    con = get_db()
    try:
        if uid:
            rows = con.execute(
                "SELECT * FROM classes WHERE teacher_uid=? ORDER BY created_at DESC", (uid,)).fetchall()
        else:
            rows = []
        out = []
        for c in rows:
            reps = con.execute(
                "SELECT version,created_at FROM class_reports WHERE class_id=? ORDER BY version",
                (c["id"],)).fetchall()
            out.append({"class_id": c["id"], "dance_name": c["dance_name"],
                        "genre": c["genre"], "status": c["status"],
                        "created_at": c["created_at"], "invite_code": c["invite_code"],
                        "report_versions": [dict(r) for r in reps]})
    finally:
        con.close()
    return {"classes": out}


# ---------- 学员端 ----------
@router.get("/api/join/{code}")
def join_lookup(code: str):
    """校验班级码 → 返回班级品牌 + 舞名（学员落地页用）。码大小写不敏感。"""
    code = (code or "").strip().upper()
    if not re.fullmatch(rf"[{CODE_ALPHABET}]{{{CODE_LEN}}}", code):
        raise HTTPException(status_code=400, detail="班级码格式不对（6位字母数字）")
    cls = _get_class_by_code(code)
    if not cls:
        # 防爆破：错误延迟 + 统一文案，不暴露是否存在
        time.sleep(0.4)
        raise HTTPException(status_code=404, detail="班级码无效或已过期")
    brand = {}
    try:
        brand = json.loads(cls["brand_json"]) if cls["brand_json"] else {}
    except Exception:
        pass
    if cls["status"] == "done":
        # 已出报告的班级不再接受加入
        raise HTTPException(status_code=410, detail="该班级测评已结束")
    return {"class_id": cls["id"], "dance_name": cls["dance_name"], "genre": cls["genre"],
            "brand": brand, "status": cls["status"]}


@router.post("/api/class/{class_id}/join")
def member_join(class_id: str, data: dict, authorization: str = Header(None)):
    """学员加入班级：填昵称 → 生成成员 + guest_token（用于看自己那页）。"""
    cls = _get_class(class_id)
    if not cls or cls["status"] == "done":
        raise HTTPException(status_code=404, detail="班级不存在或已结束")
    nickname = (data.get("nickname") or "").strip()[:20]
    real_name = (data.get("real_name") or "").strip()[:20]
    if not nickname:
        raise HTTPException(status_code=400, detail="请填昵称")
    members = _members(class_id)
    if len(members) >= cls["max_students"]:
        raise HTTPException(status_code=403, detail="班级人数已满")
    user = _resolve_user(authorization)
    uid = _uid_of(user)
    mid = "mem_" + uuid.uuid4().hex[:12]
    token = secrets.token_urlsafe(16)
    con = get_db()
    try:
        con.execute("""INSERT INTO class_members
            (id,class_id,student_uid,guest_token,nickname,real_name,join_at,status,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (mid, class_id, uid, token, nickname, real_name, _now(), "joined", _now()))
        con.commit()
    finally:
        con.close()
    return {"member_id": mid, "member_token": token, "class_id": class_id,
            "dance_name": cls["dance_name"]}


@router.post("/api/class/{class_id}/member/upload")
async def member_upload(
    class_id: str,
    member_token: str = Form(...),
    video: UploadFile = File(...),
    authorization: str = Header(None),
):
    """学员上传自己那段：存视频 + 建 decompose 目录（挂 decompose_id 到 member）。
    沿用单人线的类型 + 大小(500MB)校验。上传后置 uploaded 态，等老师开评（或全齐自动评）。
    """
    cls = _get_class(class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="班级不存在")
    m = _get_member_by_token(class_id, member_token)
    if not m:
        raise HTTPException(status_code=403, detail="成员身份无效，请重新加入班级")
    # 类型校验（放行 video/* 与 octet-stream，拒明确非视频）
    _ct = (video.content_type or "").lower()
    if _ct and not (_ct.startswith("video/") or _ct == "application/octet-stream"):
        raise HTTPException(status_code=400, detail="请上传视频文件（MP4 / MOV）")
    did = str(uuid.uuid4())
    ddir = os.path.join(DATA_DIR, did)
    os.makedirs(ddir, exist_ok=True)
    content = await video.read()
    if len(content) > MAX_UPLOAD_BYTES:
        import shutil as _sh
        _sh.rmtree(ddir, ignore_errors=True)
        raise HTTPException(status_code=413, detail="视频过大，请压到 500MB 以内")
    with open(os.path.join(ddir, "input.mp4"), "wb") as f:
        f.write(content)
    con = get_db()
    try:
        con.execute("UPDATE class_members SET decompose_id=?, status='uploaded', updated_at=? WHERE id=?",
                    (did, _now(), m["id"]))
        con.commit()
    finally:
        con.close()
    return {"status": "uploaded", "member_id": m["id"], "decompose_id": did,
            "message": "上传成功，等待老师开始评分。"}


@router.get("/api/class/{class_id}/member/{token}/result")
def member_result(class_id: str, token: str):
    """学员看自己那页 + 班级排名（脱敏：只见自己明细 + 自己名次，不见别人分数明细）。"""
    m = _get_member_by_token(class_id, token)
    if not m:
        raise HTTPException(status_code=403, detail="身份无效")
    cls = _get_class(class_id)
    brand = {}
    try:
        brand = json.loads(cls["brand_json"]) if cls and cls["brand_json"] else {}
    except Exception:
        pass
    resp = {"status": m["status"], "nickname": m["nickname"],
            "dance_name": cls["dance_name"] if cls else "",
            "brand": brand,
            "disclaimer": "舞镜AI辅助评分，供训练参考。"}
    if m["status"] == "failed":
        resp["error"] = m["error"] or "检出失败，请重传更清晰的单人全身视频"
        return resp
    if m["status"] != "scored" or not m["score_json"]:
        return resp  # 还没出分
    s = json.loads(m["score_json"])
    # 自己那一页明细
    resp["self"] = {
        "name": m["nickname"], "score": s.get("score"),
        "sc": s["sc"], "ah": s["ah"], "sp": s["sp"], "as_": s["as_"],
        "kn": s["kn"], "mv": s["mv"], "radar": s["radar"], "fb": s.get("fb", []),
        "videoUrl": s.get("videoUrl", ""), "comment": s.get("comment", ""),
        "teacher_note": s.get("teacher_note", ""),
        "measured": s.get("measured", False),
    }
    # 班级排名：只回「我是第几 / 共几人」，不泄露别人明细（脱敏红线）
    members = _members(class_id)
    scored = [x for x in members if x["status"] == "scored" and x["score_json"]]
    ranked = sorted(scored, key=lambda x: json.loads(x["score_json"])["sc"]["v"], reverse=True)
    my_rank, total = None, len(ranked)
    for i, x in enumerate(ranked):
        if x["id"] == m["id"]:
            my_rank = i + 1
            break
    resp["rank"] = {"my_rank": my_rank, "total": total}
    return resp


@router.get("/api/group/queue-stats")
def queue_stats():
    """队列可观测（运维/看板用）：当前排队与在跑数量。"""
    return _score_queue.stats()
