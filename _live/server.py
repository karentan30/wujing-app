import env_loader
import os
import uuid
import json
import threading
from datetime import datetime
from pathlib import Path
import urllib.request, base64
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Header
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from models import init_db, create_user, get_user_by_email, get_user_by_id, create_review, get_review, get_user_reviews, update_review_status, get_practice_progress, upsert_practice_task, get_user_stats
from auth import hash_password, verify_password, create_token, decode_token
# 支付统一走 pay.py（微信 NATIVE / 支付宝当面付 / Stripe Checkout，含幂等+验签+履约）。
# 旧 payment.py 的支付桩已废弃：不再 import；订单表/DB 连接改用 pay.py 提供的实现。
# check_analysis_access（旧「每月免费+付费」额度门）在新产品逻辑下作废——
# 产品拍板：上传免费无需登录，要拆解才付 9.9（付费门在 /api/decompose + pay.py 履约）。
from pay import router as pay_router, init_orders_table, get_db as _pay_get_db
from auto_decompose import run_decompose, get_decompose
from review_compare import router as solo_router
from group_review import router as group_router, init_group_tables, set_decompose_runner, set_optional_user_resolver
from my_works import router as my_works_router, init_library_tables, upsert_my_work
from analytics import track as analytics_track
app = FastAPI(title="WuJing Dance API", version="1.0.0")
# ── 拆解完成钩子：入库 + 埋点 ──
def _run_decompose_with_hooks(did, video_path, user_id, title, genre):
    try:
        run_decompose(did, video_path, user_id, title, genre)
        result = get_decompose(did)
        if result and result.get("status") == "completed":
            if user_id:
                upsert_my_work(user_id, result)
            analytics_track(str(user_id or "guest"), "decompose_success",
                          {"dance_id": did, "title": title, "genre": genre})
    except Exception:
        analytics_track(str(user_id or "guest"), "decompose_failed",
                      {"dance_id": did, "title": title})
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://karentan30.github.io","https://wj-clean.vercel.app","https://wj-clean-a83qqjigf-fabulousslim.vercel.app","https://wujing-mfgqx7z03-fabulousslim.vercel.app","https://wujing.vercel.app","https://wujing.mylumee.cn", "https://wujing.mylumee.app", "https://api-wujing.mylumee.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# BASE_DIR 支持 env 覆盖（生产默认 /www/wujing-api；staging/本地测试可指向副本，不碰生产库/数据）
BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
# Serve static/clips 目录——只在存在时挂载（本地/staging 缺目录不致启动崩溃）
def _mount_if_exists(url, directory, name, html=False):
    if os.path.isdir(directory):
        app.mount(url, StaticFiles(directory=directory, html=html), name=name)
_mount_if_exists("/demo", os.path.join(BASE_DIR, "static", "demo"), "demo", html=True)
_mount_if_exists("/static", os.path.join(BASE_DIR, "static"), "static")
_mount_if_exists("/clips", os.path.join(BASE_DIR, "clips"), "clips")
_mount_if_exists("/clips2", os.path.join(BASE_DIR, "clips2"), "clips2")
_mount_if_exists("/clips3", os.path.join(BASE_DIR, "clips3"), "clips3")
_mount_if_exists("/clips4", os.path.join(BASE_DIR, "clips4"), "clips4")
# Initialize database on startup
init_db()
init_orders_table()
init_group_tables()
init_library_tables()
# ---------- Auth Middleware ----------
def get_current_user(authorization: str = Header(None)):
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
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

def get_optional_user(authorization: str = Header(None)):
    """可选登录：有合法 token 返回 user，否则返回 None（不抛 401）。
    用于「上传免费无需登录」的游客链路——登录用户绑到其账号，游客走匿名 dance。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = decode_token(token)
        return get_user_by_id(payload["user_id"])
    except Exception:
        return None

# ── 注入群舞/班级依赖（在函数定义之后、路由之前）──
set_decompose_runner(run_decompose, get_decompose)
set_optional_user_resolver(get_optional_user)

# ---------- Phase 1: User System ----------
@app.post("/api/register")
def register(email: str = Form(...), password: str = Form(...)):
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    pw_hash = hash_password(password)
    user_id = create_user(email, pw_hash)
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")
    token = create_token(user_id, email)
    return {"token": token, "user_id": user_id, "email": email}
@app.post("/api/login")
def login(email: str = Form(...), password: str = Form(...)):
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"], user["email"])
    return {"token": token, "user_id": user["id"], "email": user["email"]}
@app.post("/api/register_json")
def register_json(data: dict):
    email = data.get("email", "")
    password = data.get("password", "")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    pw_hash = hash_password(password)
    user_id = create_user(email, pw_hash)
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")
    token = create_token(user_id, email)
    return {"token": token, "user_id": user_id, "email": email}
@app.post("/api/login_json")
def login_json(data: dict):
    email = data.get("email", "")
    password = data.get("password", "")
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"], user["email"])
    return {"token": token, "user_id": user["id"], "email": user["email"]}
@app.get("/api/me")
def get_me(user: dict = Depends(get_current_user)):
    stats = get_user_stats(user["id"])
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "created_at": user["created_at"]
        },
        "stats": stats
    }
# ---------- Phase 2: Upload + Analysis ----------
from analyze import run_analysis
TEACHER_KEYS = ["yue", "yueyuan", "chengmo"]

TEACHER_BASE = "/www/wujing"
# reference.mp4 smaller than this is a broken/placeholder video (real clips are 0.5-3MB)
MIN_REF_BYTES = 50 * 1024

def _classify_genre(title, sub):
    """Genre classifier -> theme key for the result page.
    Title is authoritative; the ingested `sub` is unreliable (operators tagged
    almost everything '爆款舞'), so guofeng title keywords win first."""
    t = (str(title) + " " + str(sub)).lower()
    gf_kw = ["古典", "国风", "古风", "戏曲", "民族", "水袖", "刀马", "敦煌", "青绿",
             "洛神", "惊鸿", "孔雀", "汉唐", "傣族", "飞天", "古风舞", "唐宫"]
    if any(k in t for k in gf_kw):
        return "guofeng"
    kpop_kw = ["k-pop", "kpop", "女团", "男团", "科目三", "blackpink", "babymonster",
               "illit", "wonyoung", "张元英", "网红", "手势", "比心", "卡点"]
    if any(k in t for k in kpop_kw):
        return "kpop"
    return "guofeng"

def _teacher_list():
    """Scan the dance library and return valid teachers with metadata.
    Excludes entries whose reference.mp4 is a tiny placeholder."""
    out = []
    try:
        for d in sorted(os.listdir(TEACHER_BASE)):
            pp = os.path.join(TEACHER_BASE, d)
            ref = os.path.join(pp, "reference.mp4")
            bd = os.path.join(pp, "breakdown.json")
            if not (os.path.isdir(pp) and os.path.exists(ref) and os.path.exists(bd)):
                continue
            try:
                if os.path.getsize(ref) < MIN_REF_BYTES:
                    continue  # broken/placeholder video
            except OSError:
                continue
            title, sub = d, ""
            try:
                with open(bd, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                title = meta.get("title") or d
                sub = meta.get("sub") or ""
            except Exception:
                pass
            out.append({
                "key": d,
                "title": title,
                "sub": sub,
                "genre": _classify_genre(title, sub),
            })
    except Exception:
        pass
    return out

def _valid_teacher_keys():
    ks = [t["key"] for t in _teacher_list()]
    return ks or ["yue", "yueyuan", "chengmo"]

@app.post("/api/upload")
async def upload_video(
    video: UploadFile = File(...),
    teacher_key: str = Form(...),
    user: dict = Depends(get_optional_user)   # 上传免费·无需登录（游客可传）
):
    if teacher_key not in _valid_teacher_keys():
        raise HTTPException(
            status_code=400,
            detail=f"Invalid teacher_key. Must be one of: {', '.join(TEACHER_KEYS)}"
        )
    review_id = str(uuid.uuid4())
    review_dir = os.path.join(DATA_DIR, review_id)
    os.makedirs(review_dir, exist_ok=True)
    # Save uploaded video（大小兜底：防 OOM / 任意大文件）
    video_path = os.path.join(review_dir, "input.mp4")
    content = await video.read()
    if len(content) > 500 * 1024 * 1024:
        import shutil as _sh
        _sh.rmtree(review_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail="视频过大，请压到 500MB 以内")
    with open(video_path, "wb") as f:
        f.write(content)
    # Create review record in DB（游客 user_id=None，登录用户绑账号）
    create_review(review_id, (user["id"] if user else None), teacher_key)
    # 上传免费、无需登录：不再有每月额度门（旧 check_analysis_access 已作废）。
    # 此流程是老「对镜评分」，与「付费拆解出卡」是两条链路，此处保持免费即时分析。
    # Run analysis in background
    thread = threading.Thread(
        target=run_analysis,
        args=(review_id, video_path, teacher_key),
        daemon=True
    )
    thread.start()
    return {
        "review_id": review_id,
        "status": "processing",
        "message": "Upload successful. Analysis started in background."
    }
@app.get("/api/review/{review_id}")
def get_review_endpoint(review_id: str, user: dict = Depends(get_current_user)):
    review = get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    # Build response
    result = {
        "id": review["id"],
        "teacher_key": review["teacher_key"],
        "score": review["score"],
        "dims": json.loads(review["dims"]) if review["dims"] else None,
        "problems": json.loads(review["problems"]) if review["problems"] else [],
        "highlights": json.loads(review["highlights"]) if review["highlights"] else [],
        "cards": json.loads(review["cards"]) if ("cards" in review.keys() and review["cards"]) else None,
        "status": review["status"],
        "created_at": review["created_at"]
    }
    return result
@app.get("/api/review/{review_id}/slowmo/{problem_id}")
def get_slowmo(review_id: str, problem_id: int, user: dict = Depends(get_current_user)):
    review = get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    slowmo_path = os.path.join(DATA_DIR, review_id, "slowmo", f"problem_{problem_id}.mp4")
    if not os.path.exists(slowmo_path):
        raise HTTPException(status_code=404, detail="Slow-mo video not found")
    return FileResponse(slowmo_path, media_type="video/mp4")
@app.get("/api/reviews")
def list_reviews(user: dict = Depends(get_current_user)):
    reviews = get_user_reviews(user["id"])
    result = []
    for r in reviews:
        result.append({
            "id": r["id"],
            "teacher_key": r["teacher_key"],
            "score": r["score"],
            "status": r["status"],
            "created_at": r["created_at"]
        })
    return {"reviews": result}
# ---------- Phase 3: Practice Progress ----------
@app.get("/api/plan/{review_id}")
def get_practice_plan(review_id: str, user: dict = Depends(get_current_user)):
    review = get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    problems = json.loads(review["problems"]) if review["problems"] else []
    progress = get_practice_progress(review_id)
    progress_map = {}
    for p in progress:
        progress_map[(p["day"], p["task_index"])] = p["completed"]
    # Generate practice plan from problems
    days = []
    num_problems = len(problems)
    if num_problems == 0:
        days = [{"day": 1, "tasks": [{"index": 0, "task": "Practice full dance routine", "completed": False}]}]
    else:
        for day_num in range(1, min(8, num_problems * 2 + 1)):
            tasks = []
            for idx, prob in enumerate(problems):
                if idx < day_num:
                    tasks.append({
                        "index": idx,
                        "task": prob.get("problem", f"Fix issue #{idx+1}"),
                        "detail": prob.get("fix", ""),
                        "completed": progress_map.get((day_num, idx), False)
                    })
            if tasks:
                days.append({"day": day_num, "tasks": tasks})
    return {
        "review_id": review_id,
        "total_problems": num_problems,
        "plan": days
    }
@app.put("/api/plan/{review_id}/task")
def update_task(review_id: str, data: dict, user: dict = Depends(get_current_user)):
    review = get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    day = data.get("day")
    task_index = data.get("task_index")
    completed = data.get("completed", True)
    if day is None or task_index is None:
        raise HTTPException(status_code=400, detail="day and task_index are required")
    upsert_practice_task(review_id, day, task_index, completed)
    return {"status": "ok", "day": day, "task_index": task_index, "completed": completed}
@app.get("/api/stats")
def get_global_stats(user: dict = Depends(get_current_user)):
    stats = get_user_stats(user["id"])
    return stats
@app.post("/api/generate-bg")
def generate_bg(data: dict, user: dict = Depends(get_current_user)):
    prompt = data.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    # ⚠️生图=最大烧钱坑：仍要求登录（get_current_user）防匿名无限调用烧豆包余额。
    # 旧 check_analysis_access 额度门已随 payment.py 作废；此处以「必须登录」作为最低门槛，
    # 更严格的每日配额留待后续（TODO：加登录用户每日生图上限）。
    key = os.environ.get("ARK_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="ARK_API_KEY not configured")
    try:
        bg_dir = os.path.join(os.path.dirname(__file__), "static", "bg")
        os.makedirs(bg_dir, exist_ok=True)
        body = json.dumps({"model": "doubao-seedream-5-0-260128", "prompt": prompt, "n": 1, "size": "720x1280", "response_format": "b64_json"}).encode()
        req = urllib.request.Request("https://ark.cn-beijing.volces.com/api/v3/images/generations", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        img_b64 = resp["data"][0]["b64_json"]
        img_id = str(uuid.uuid4())
        img_path = os.path.join(bg_dir, f"{img_id}.png")
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(img_b64))
        return {"url": f"/static/bg/{img_id}.png"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
@app.get("/api/teachers")
def list_teachers():
    """Public: real dances available as reference for student uploads (broken placeholders excluded)."""
    return {"teachers": _teacher_list()}

# ---------- 任意舞自动拆解（免选老师·上传即出八拍卡/故事卡/记忆卡） ----------
def _dance_is_paid(dance_id):
    """该 dance 是否已存在一条 paid 订单（付费门判定，复用 pay.py orders 表）。"""
    try:
        with _pay_get_db() as _c:
            row = _c.execute(
                "SELECT 1 FROM orders WHERE dance_id=? AND status='paid' LIMIT 1",
                (dance_id,)).fetchone()
            return bool(row)
    except Exception:
        return False


@app.post("/api/decompose")
async def decompose_video(
    video: UploadFile = File(...),
    title: str = Form("我的舞"),
    genre: str = Form("guofeng"),
    user: dict = Depends(get_optional_user),   # 上传免费·无需登录（游客可传）
):
    """上传免费（游客可传）：存源视频 + 建 dance 记录，但**不自动拆解**。
    用户点「拆开这支舞」→ /api/pay/*/create 付 9.9 → 支付回调履约触发 run_decompose。
    这里只落地 dance_id + 源视频，返回 awaiting_payment，前端据此展示付费按钮。"""
    # 上传校验：类型 + 大小（防 OOM / 任意文件）。放行 video/* 和 octet-stream(浏览器/curl常用)，只拒明确非视频
    _ct = (video.content_type or "").lower()
    if _ct and not (_ct.startswith("video/") or _ct == "application/octet-stream"):
        raise HTTPException(status_code=400, detail="请上传视频文件（MP4 / MOV）")
    did = str(uuid.uuid4())
    ddir = os.path.join(DATA_DIR, did)
    os.makedirs(ddir, exist_ok=True)
    video_path = os.path.join(ddir, "input.mp4")
    content = await video.read()
    if len(content) > 500 * 1024 * 1024:
        import shutil as _sh
        _sh.rmtree(ddir, ignore_errors=True)
        raise HTTPException(status_code=413, detail="视频过大，请压到 500MB 以内")
    with open(video_path, "wb") as f:
        f.write(content)

    # 落一份「待付费」占位卡（前端可立即 GET /api/decompose/{did} 拿到 awaiting_payment 态）
    uid = (user["id"] if user else None)
    try:
        _write_awaiting = os.path.join(ddir, "decompose.json")
        with open(_write_awaiting, "w", encoding="utf-8") as f:
            json.dump({"id": did, "user_id": uid, "title": title, "genre": genre,
                       "status": "awaiting_payment",
                       "message": "上传成功。点「拆开这支舞」付 9.9 生成完整拆解卡。"},
                      f, ensure_ascii=False)
    except Exception:
        pass

    # 免费模式(WJ_FREE_MODE=1·支付商户号未就位时先免费拉新)：上传即拆·不收费。
    # 商户号到位后设 WJ_FREE_MODE=0，自动恢复「要拆付 9.9」。
    if os.environ.get("WJ_FREE_MODE") == "1":
        uid2 = (user["id"] if user else None)
        threading.Thread(target=_run_decompose_with_hooks,
                         args=(did, video_path, uid2, title, genre), daemon=True).start()
        return {"decompose_id": did, "dance_id": did, "status": "processing",
                "message": "上传成功，正在为你拆解…"}

    return {"decompose_id": did, "dance_id": did, "status": "awaiting_payment",
            "price_cny": float(os.environ.get("WJ_DANCE_PRICE_CNY", "9.9")),
            "message": "上传成功。点「拆开这支舞」付 9.9 生成完整拆解卡。"}


@app.post("/api/decompose/{did}/run")
async def decompose_run_if_paid(did: str, user: dict = Depends(get_optional_user)):
    """兜底触发：已付费但拆解未生成时手动重跑（幂等）。未付费拒。
    正常路径由支付回调 pay.py._apply_paid_dance_unlock 自动触发，这里仅作重试入口。"""
    ddir = os.path.join(DATA_DIR, did)
    video_path = os.path.join(ddir, "input.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="源视频不存在，请重新上传")
    if os.environ.get("WJ_FREE_MODE") != "1" and not _dance_is_paid(did):
        raise HTTPException(status_code=402, detail="尚未付费，请先付 9.9 解锁拆解")
    # 已完成则不重复跑（幂等）
    d = get_decompose(did)
    if d and d.get("status") == "completed":
        return {"decompose_id": did, "status": "completed", "message": "已生成，无需重复。"}
    title = (d or {}).get("title", "我的舞")
    genre = (d or {}).get("genre", "guofeng")
    uid = (d or {}).get("user_id") or (user["id"] if user else None)
    t = threading.Thread(target=_run_decompose_with_hooks,
                         args=(did, video_path, uid, title, genre), daemon=True)
    t.start()
    return {"decompose_id": did, "status": "processing", "message": "已付费，拆解已开始。"}

@app.get("/api/decompose/{did}")
def get_decompose_endpoint(did: str, user: dict = Depends(get_optional_user)):
    """游客可读（上传免费、无需登录）：拿拆解卡 / awaiting_payment 态。
    若该 dance 绑定了某登录用户，则仅该用户可读；匿名 dance（user_id=None）任何人可读。"""
    d = get_decompose(did)
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    owner = d.get("user_id")
    # None / 'guest' 视为匿名，任何人可读；绑定了真实登录用户的才校验归属
    if owner not in (None, "", "guest"):
        if not user or owner != user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    return d

@app.get("/api/decompose/{did}/clip/{name}")
def get_decompose_clip(did: str, name: str):
    """服务拆解切片：name='full'→整片·'pN'→第N段。慢放/镜像前端处理。"""
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    if safe == "full":
        path = os.path.join(DATA_DIR, did, "input.mp4")
    else:
        path = os.path.join(DATA_DIR, did, "clips", f"{safe}.mp4")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(path, media_type="video/mp4")

@app.get("/api/decompose/{did}/frame/{name}")
def get_decompose_frame(did: str, name: str):
    """服务某段定格帧图 pN.jpg / pN_k.jpg（胶片条帧）。"""
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    path = os.path.join(DATA_DIR, did, "frames", f"{safe}.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path, media_type="image/jpeg")
@app.get("/")
@app.get("/design-upgrade.html")
def serve_app():
    _app_html = os.path.join(BASE_DIR, "static", "design-upgrade.html")
    if not os.path.exists(_app_html):
        return JSONResponse({"service": "wujing-api", "note": "app html not deployed here"})
    return FileResponse(_app_html)
# ---------- Payment routes ----------
app.include_router(pay_router)
# ---------- Solo / Group / My Works routes ----------
app.include_router(solo_router)
app.include_router(group_router)
app.include_router(my_works_router)
# ---------- Health Check ----------
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "wujing-api", "version": "1.0.0"}
# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3006)
