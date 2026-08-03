import env_loader
import os
import uuid
import json
import threading
from datetime import datetime
from pathlib import Path
import urllib.request, base64, subprocess
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from models import init_db, create_user, get_user_by_email, get_user_by_id, get_user_by_openid, create_wx_user, create_review, get_review, get_user_reviews, update_review_status, get_practice_progress, upsert_practice_task, get_user_stats
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
from hub_router import router as hub_router
app = FastAPI(title="WuJing Dance API", version="1.0.0")

# ── 免费模式限频：防无上限刷拆解烧 ARK/DeepSeek（WJ_FREE_MODE=1 时生效） ──
import time as _time
_FREE_LIMIT = {"per_hour": 3, "per_day": 10}          # 每设备每小时3次/每天10次免费拆解
_free_hits = {}                                       # {identity: {"h": [ts], "d": [ts]}}
_bg_daily = {}                                        # {"bg:{uid}:{date}": count} 生图每日配额
_FREE_LOCK = threading.Lock()

def _free_quota_ok(identity):
    """免费模式配额判定：超限返回 False。登录用户按 device 一起计（同设备）。"""
    if os.environ.get("WJ_FREE_MODE") != "1":
        return True
    if not identity or identity == "guest":
        return True  # 无身份的极端兜底不卡（正常前端都带 device）
    now = _time.time()
    with _FREE_LOCK:
        rec = _free_hits.setdefault(identity, {"h": [], "d": []})
        rec["h"] = [t for t in rec["h"] if now - t < 3600]
        rec["d"] = [t for t in rec["d"] if now - t < 86400]
        if len(rec["h"]) >= _FREE_LIMIT["per_hour"] or len(rec["d"]) >= _FREE_LIMIT["per_day"]:
            return False
        rec["h"].append(now); rec["d"].append(now)
        return True
# ── 拆解完成钩子：入库 + 埋点 ──
def _run_decompose_with_hooks(did, video_path, user_id, title, genre,
                              song="", lyric_first="", lyric_last=""):
    try:
        run_decompose(did, video_path, user_id, title, genre,
                      song=song, lyric_first=lyric_first, lyric_last=lyric_last)
        # 生成三张PNG卡片（八拍卡/镜面卡/记忆卡）
        try:
            gen_script = os.path.join(BASE_DIR, "cards", "gen_cards.py")
            if os.path.exists(gen_script):
                ddir = os.path.join(DATA_DIR, did)
                r = subprocess.run(["python3", gen_script, did, video_path, ddir],
                                   timeout=300, capture_output=True, text=True)
                print(f"[cards] {r.stdout.strip()}")
                if r.returncode != 0:
                    print(f"[cards] stderr: {r.stderr[-500:]}")
        except Exception as _ce:
            print(f"[cards] gen failed: {_ce}")
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

def _check_video_magic(data: bytes) -> bool:
    """Verify uploaded file has a valid video magic byte signature."""
    if len(data) < 12:
        return False
    if data[:4] == b'RIFF':  # AVI
        return True
    if data[4:8] == b'ftyp':  # MP4/MOV/M4V
        return True
    if data[:3] == b'\x00\x00\x00' and data[4:8] in (b'ftyp', b'moov'):
        return True
    return False

@app.get("/ping")
def ping():
    return {"pong": True}

@app.get("/health")
def health():
    return {"ok": True, "service": "wujing-api"}

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

# ── 微信网页授权登录（OAuth2.0 snsapi_userinfo）──────────────────────────────
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")
_WX_OAUTH_BASE = "https://open.weixin.qq.com/connect/oauth2/authorize"
_WX_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
_WX_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"

@app.get("/api/wx/login")
def wx_login_redirect(redirect_uri: str = ""):
    import urllib.parse as _up
    if not WECHAT_APP_ID:
        raise HTTPException(status_code=503, detail="WeChat AppID not configured")
    callback = f"https://wujing.mylumee.app/api/wx/callback?redirect={_up.quote(redirect_uri or '/')}"
    url = (f"{_WX_OAUTH_BASE}?appid={WECHAT_APP_ID}"
           f"&redirect_uri={_up.quote(callback)}"
           f"&response_type=code&scope=snsapi_userinfo&state=wujing#wechat_redirect")
    return RedirectResponse(url)

@app.get("/api/wx/callback")
async def wx_callback(code: str = "", state: str = "", redirect: str = "/"):
    import urllib.parse as _up, urllib.request as _ur
    if not WECHAT_APP_SECRET:
        return RedirectResponse(f"{redirect}#wx_error=secret_not_configured")
    try:
        # 1. code → access_token + openid
        r = _ur.urlopen(
            f"{_WX_TOKEN_URL}?appid={WECHAT_APP_ID}&secret={WECHAT_APP_SECRET}"
            f"&code={code}&grant_type=authorization_code", timeout=10)
        data = json.loads(r.read())
        openid = data.get("openid", "")
        access_token = data.get("access_token", "")
        if not openid:
            return RedirectResponse(f"{redirect}#wx_error=no_openid")
        # 2. openid → userinfo
        r2 = _ur.urlopen(
            f"{_WX_USERINFO_URL}?access_token={access_token}&openid={openid}&lang=zh_CN", timeout=10)
        user_info = json.loads(r2.read())
        nickname = user_info.get("nickname", "")
        avatar = user_info.get("headimgurl", "")
        # 3. 查或建用户
        user = get_user_by_openid(openid)
        if user:
            uid, email = user["id"], user["email"]
        else:
            uid = create_wx_user(openid, nickname)
            email = f"wx_{openid}@wujing.wx"
        token = create_token(uid, email)
        # 4. 把 token 带回前端（URL hash）
        payload = base64.b64encode(json.dumps(
            {"token": token, "openid": openid, "nickname": nickname, "avatar": avatar}
        ).encode()).decode()
        return RedirectResponse(f"{redirect}#wx_token={payload}")
    except Exception as e:
        print(f"[wx_callback] error: {e}")
        return RedirectResponse(f"{redirect}#wx_error=callback_failed")

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
    if not _check_video_magic(content):
        import shutil as _sh
        _sh.rmtree(review_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="请上传有效的视频文件（MP4 / MOV / AVI）")
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
    # ⚠️生图=最大烧钱坑：登录（get_current_user）+ 每日配额双闸，防无限调用烧豆包余额。
    _BG_LIMIT_PER_DAY = 20
    _now_day = _time.strftime("%Y%m%d")
    uid = str(user["id"])
    key = f"bg:{uid}:{_now_day}"
    with _FREE_LOCK:
        cnt = _bg_daily.get(key, 0)
        if cnt >= _BG_LIMIT_PER_DAY:
            raise HTTPException(status_code=429, detail=f"今日生图已达上限（{_BG_LIMIT_PER_DAY}次），明天再试")
        _bg_daily[key] = cnt + 1
    # 过期清理（避免 dict 无限增长）
    if len(_bg_daily) > 2000:
        _bg_daily.clear()
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
def _safe_did(did):
    """路径防穿越：dance_id 允许字母/数字/连字符/下划线，拒绝 ../ 等路径穿越。"""
    import re as _re
    if not did or not _re.match(r'^[a-zA-Z0-9_-]+$', did) or ".." in did or "/" in did:
        raise HTTPException(status_code=400, detail="无效的 dance_id")
    return did
def _identity_for(user, x_device_id=None):
    """付费身份：登录用户→user_id；游客→guest:<device_id>（每设备独立，一次付款只解锁该设备）。
    无 device 时回退全局 'guest'（旧游客，但下单会带 device 所以正常路径不会走到）。"""
    if user and user.get("id"):
        return str(user["id"])
    dev = (x_device_id or "").strip()
    if dev:
        dev = "".join(ch for ch in dev if ch.isalnum() or ch in "-_")[:64]
        if dev:
            return f"guest:{dev}"
    return "guest"


def _dance_is_paid(dance_id, identity):
    """该 dance 是否已存在一条**该身份**的 paid 订单（付费门判定，复用 pay.py orders 表）。
    按 (user_id, dance_id) 联合判定，防止一次付款被全网复用。"""
    try:
        with _pay_get_db() as _c:
            row = _c.execute(
                "SELECT 1 FROM orders WHERE dance_id=? AND user_id=? AND status='paid' LIMIT 1",
                (dance_id, identity)).fetchone()
            return bool(row)
    except Exception:
        return False


@app.post("/api/decompose")
async def decompose_video(
    video: UploadFile = File(...),
    title: str = Form("我的舞"),
    genre: str = Form("guofeng"),
    song: str = Form(""),
    lyric_first: str = Form(""),
    lyric_last: str = Form(""),
    user: dict = Depends(get_optional_user),   # 上传免费·无需登录（游客可传）
    x_device_id: str = Header(None),
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
    if not _check_video_magic(content):
        import shutil as _sh
        _sh.rmtree(ddir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="请上传有效的视频文件（MP4 / MOV / AVI）")
    with open(video_path, "wb") as f:
        f.write(content)

    # 落一份「待付费」占位卡（前端可立即 GET /api/decompose/{did} 拿到 awaiting_payment 态）
    uid = (user["id"] if user else None)
    try:
        _write_awaiting = os.path.join(ddir, "decompose.json")
        with open(_write_awaiting, "w", encoding="utf-8") as f:
            json.dump({"id": did, "user_id": uid, "title": title, "genre": genre,
                       "song": song, "lyric_first": lyric_first, "lyric_last": lyric_last,
                       "status": "awaiting_payment",
                       "message": "上传成功。点「拆开这支舞」付 9.9 生成完整拆解卡。"},
                      f, ensure_ascii=False)
    except Exception:
        pass

    # 免费模式(WJ_FREE_MODE=1·支付商户号未就位时先免费拉新)：上传即拆·不收费。
    # 商户号到位后设 WJ_FREE_MODE=0，自动恢复「要拆付 9.9」。
    if os.environ.get("WJ_FREE_MODE") == "1":
        ident = _identity_for(user, x_device_id)
        if not _free_quota_ok(ident):
            raise HTTPException(status_code=429,
                                detail="免费拆解已达上限（每小时3次/每天10次），请稍后再试或登录解锁更多")
        uid2 = (user["id"] if user else None)
        threading.Thread(target=_run_decompose_with_hooks,
                         args=(did, video_path, uid2, title, genre, song, lyric_first, lyric_last),
                         daemon=True).start()
        return {"decompose_id": did, "dance_id": did, "status": "processing",
                "message": "上传成功，正在为你拆解…"}

    return {"decompose_id": did, "dance_id": did, "status": "awaiting_payment",
            "price_cny": float(os.environ.get("WJ_DANCE_PRICE_CNY", "9.9")),
            "message": "上传成功。点「拆开这支舞」付 9.9 生成完整拆解卡。"}


@app.post("/api/decompose/{did}/run")
async def decompose_run_if_paid(did: str, user: dict = Depends(get_optional_user),
                                x_device_id: str = Header(None)):
    """兜底触发：已付费但拆解未生成时手动重跑（幂等）。未付费拒。
    正常路径由支付回调 pay.py._apply_paid_dance_unlock 自动触发，这里仅作重试入口。"""
    _safe_did(did)
    ddir = os.path.join(DATA_DIR, did)
    video_path = os.path.join(ddir, "input.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="源视频不存在，请重新上传")
    identity = _identity_for(user, x_device_id)
    if os.environ.get("WJ_FREE_MODE") != "1" and not _dance_is_paid(did, identity):
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
    _safe_did(did)
    """游客可读（上传免费、无需登录）：拿拆解卡 / awaiting_payment 态。
    若该 dance 绑定了某登录用户，则仅该用户可读；匿名 dance（user_id=None）任何人可读。"""
    d = get_decompose(did)
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    # 已发广场(is_public=1)的作品 = 公开分享物，任何人可只读查看（广场UGC的核心）
    if _decompose_is_public(did):
        return d
    owner = d.get("user_id")
    # None / 'guest' 视为匿名，任何人可读；绑定了真实登录用户的才校验归属
    if owner not in (None, "", "guest"):
        if not user or owner != user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")
    return d


def _decompose_is_public(did):
    try:
        with _pay_get_db() as _c:
            row = _c.execute(
                "SELECT is_public FROM my_works WHERE dance_id=? AND is_public=1 LIMIT 1",
                (did,)).fetchone()
            return bool(row)
    except Exception:
        return False

@app.get("/api/decompose/{did}/clip/{name}")
def get_decompose_clip(did: str, name: str):
    _safe_did(did)
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
    _safe_did(did)
    """服务某段定格帧图 pN.jpg / pN_k.jpg（胶片条帧）。"""
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    path = os.path.join(DATA_DIR, did, "frames", f"{safe}.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path, media_type="image/jpeg")

@app.get("/api/decompose/{did}/card/{name}")
def get_decompose_card(did: str, name: str):
    _safe_did(did)
    name_clean = name.replace("..", "").replace("/", "").replace("\\", "")
    path = os.path.join(DATA_DIR, did, name_clean)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Card not found")
    from urllib.parse import quote
    safe_filename = quote(name_clean, safe="")
    return FileResponse(path, media_type="image/png",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"})

@app.get("/")
@app.get("/design-upgrade.html")
def serve_app():
    _app_html = os.path.join(BASE_DIR, "static", "design-upgrade.html")
    if not os.path.exists(_app_html):
        return JSONResponse({"service": "wujing-api", "note": "app html not deployed here"})
    return FileResponse(_app_html)

@app.get("/class_teacher.html")
def serve_class_teacher():
    _p = os.path.join(BASE_DIR, "static", "class_teacher.html")
    return FileResponse(_p) if os.path.exists(_p) else JSONResponse({"error": "not found"}, 404)

@app.get("/class_join.html")
def serve_class_join():
    _p = os.path.join(BASE_DIR, "static", "class_join.html")
    return FileResponse(_p) if os.path.exists(_p) else JSONResponse({"error": "not found"}, 404)

@app.get("/teacher-partner")
@app.get("/teacher-partner.html")
def serve_teacher_partner():
    _p = os.path.join(BASE_DIR, "static", "teacher-partner.html")
    return FileResponse(_p) if os.path.exists(_p) else JSONResponse({"error": "not found"}, 404)

@app.get("/j/{code}")
def join_page(code: str):
    """班级码短链 → 重写到学员加入页。group_review 建班返回的 join_url 即 /j/{code}。"""
    return RedirectResponse(f"/class_join.html?code={code}")
# ---------- Payment routes ----------
app.include_router(pay_router)

# Stripe webhook 别名：Stripe Dashboard 注册的是 /stripe/webhook，实际处理在 /api/pay/stripe/webhook
from pay import stripe_webhook as _pay_stripe_webhook
app.post("/stripe/webhook")(_pay_stripe_webhook)
app.include_router(hub_router)
# ---------- Solo / Group / My Works routes ----------
app.include_router(solo_router)
app.include_router(group_router)
app.include_router(my_works_router)
# ---------- Teacher Signup ----------
@app.post("/api/teacher/signup")
async def teacher_signup(request: Request):
    import datetime
    try:
        data = await request.json()
        contact = str(data.get("contact", ""))[:100]
        line = f"{datetime.datetime.now().isoformat()} | {contact}\n"
        with open(os.path.join(BASE_DIR, "teacher_signups.txt"), "a") as f:
            f.write(line)
    except Exception:
        pass
    return {"ok": True}

# ---------- Health Check ----------
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "wujing-api", "version": "1.0.0"}
# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3006)
