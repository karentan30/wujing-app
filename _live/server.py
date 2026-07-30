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
from payment import router as pay_router, init_orders_table, check_analysis_access, get_db as _pay_get_db
from auto_decompose import run_decompose, get_decompose
app = FastAPI(title="WuJing Dance API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://karentan30.github.io","https://wj-clean.vercel.app","https://wj-clean-a83qqjigf-fabulousslim.vercel.app","https://wujing-mfgqx7z03-fabulousslim.vercel.app","https://wujing.vercel.app","https://wujing.mylumee.cn", "https://wujing.mylumee.app", "https://api-wujing.mylumee.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Serve demo static files
app.mount("/demo", StaticFiles(directory="/www/wujing-api/static/demo", html=True), name="demo")
app.mount("/static", StaticFiles(directory="/www/wujing-api/static"), name="static")
app.mount("/clips", StaticFiles(directory="/www/wujing-api/clips"), name="clips")
app.mount("/clips2", StaticFiles(directory="/www/wujing-api/clips2"), name="clips2")
app.mount("/clips3", StaticFiles(directory="/www/wujing-api/clips3"), name="clips3")
app.mount("/clips4", StaticFiles(directory="/www/wujing-api/clips4"), name="clips4")
BASE_DIR = "/www/wujing-api"
DATA_DIR = os.path.join(BASE_DIR, "data")
# Initialize database on startup
init_db()
init_orders_table()
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
    user: dict = Depends(get_current_user)
):
    if teacher_key not in _valid_teacher_keys():
        raise HTTPException(
            status_code=400,
            detail=f"Invalid teacher_key. Must be one of: {', '.join(TEACHER_KEYS)}"
        )
    review_id = str(uuid.uuid4())
    review_dir = os.path.join(DATA_DIR, review_id)
    os.makedirs(review_dir, exist_ok=True)
    # Save uploaded video
    video_path = os.path.join(review_dir, "input.mp4")
    content = await video.read()
    with open(video_path, "wb") as f:
        f.write(content)
    # Create review record in DB
    create_review(review_id, user["id"], teacher_key)
    # ---- 付费门骨架：每月1次免费，超出需付费(single/¥9.9 或 monthly/¥39) ----
    try:
        _access = check_analysis_access(user["id"])
    except Exception:
        _access = {"allowed": True, "type": "free", "reason": "access-check-skip"}
    if not _access.get("allowed", True):
        raise HTTPException(status_code=402, detail=_access.get("reason", "需要付费"))
    # 单次付费：标记消耗一次（钩子留好）
    if _access.get("type") == "single":
        try:
            with _pay_get_db() as _c:
                _c.execute(
                    "UPDATE orders SET consumed_at=CURRENT_TIMESTAMP WHERE id=("
                    "SELECT id FROM orders WHERE user_id=? AND product='single' AND status='paid'"
                    " AND (consumed_at IS NULL OR consumed_at='') ORDER BY paid_at LIMIT 1)",
                    (user["id"],)
                )
        except Exception:
            pass
    # 免费额度：记一条 free 占位行，作为每月免费计数依据
    if _access.get("type") == "free":
        try:
            import datetime as _dt, uuid as _uuid
            with _pay_get_db() as _c:
                _c.execute(
                    "INSERT INTO orders(out_trade_no,user_id,product,amount,currency,channel,status,created_at)"
                    " VALUES(?,?,'free','0.00','cny','free','paid',?)",
                    ("WJF" + _dt.datetime.now().strftime("%Y%m%d%H%M%S") + _uuid.uuid4().hex[:6],
                     user["id"], _dt.datetime.now().isoformat())
                )
        except Exception:
            pass
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
    # ⚠️额度门：生图=最大烧钱坑·防登录用户无限调用烧豆包余额
    try:
        _acc = check_analysis_access(user["id"])
    except Exception:
        _acc = {"allowed": True}
    if not _acc.get("allowed", True):
        raise HTTPException(status_code=402, detail=_acc.get("reason", "生图需要付费额度"))
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
@app.post("/api/decompose")
async def decompose_video(
    video: UploadFile = File(...),
    title: str = Form("我的舞"),
    genre: str = Form("guofeng"),
    user: dict = Depends(get_current_user),
):
    # 免费额度门（复用付费门骨架，防刷烧钱）
    try:
        _access = check_analysis_access(user["id"])
    except Exception:
        _access = {"allowed": True, "type": "free"}
    if not _access.get("allowed", True):
        raise HTTPException(status_code=402, detail=_access.get("reason", "需要付费"))

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

    # 记一条 free 占位（每月免费计数）
    if _access.get("type") == "free":
        try:
            import datetime as _dt
            with _pay_get_db() as _c:
                _c.execute(
                    "INSERT INTO orders(out_trade_no,user_id,product,amount,currency,channel,status,created_at)"
                    " VALUES(?,?,'free','0.00','cny','free','paid',?)",
                    ("WJD" + _dt.datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6],
                     user["id"], _dt.datetime.now().isoformat()))
        except Exception:
            pass

    t = threading.Thread(target=run_decompose,
                         args=(did, video_path, user["id"], title, genre), daemon=True)
    t.start()
    return {"decompose_id": did, "status": "processing", "message": "上传成功，自动拆解已开始。"}

@app.get("/api/decompose/{did}")
def get_decompose_endpoint(did: str, user: dict = Depends(get_current_user)):
    d = get_decompose(did)
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    if d.get("user_id") not in (None, user["id"]):
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
    return FileResponse("/www/wujing-api/static/design-upgrade.html")
# ---------- Payment routes ----------
app.include_router(pay_router)
# ---------- Health Check ----------
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "wujing-api", "version": "1.0.0"}
# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3006)
