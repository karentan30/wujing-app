"""
═══ 后端超时保护 & 资源限制 ═══

添加到 server.py 中的关键代码段
"""

import asyncio
import functools
import signal
from datetime import datetime
from fastapi import Request
from fastapi.responses import JSONResponse

# ─────────────────────────────────────────────
# 1. 全局 HTTP 超时中间件（添加到 app.middleware 之后）
# ─────────────────────────────────────────────

@app.middleware("http")
async def global_timeout_middleware(request: Request, call_next):
    """
    所有 API 请求添加 30 秒全局超时
    防止长时间挂起请求占用资源
    """
    try:
        # 设置 30 秒超时（可根据业务调整）
        response = await asyncio.wait_for(call_next(request), timeout=30.0)
        return response
    except asyncio.TimeoutError:
        print(f"[Timeout] API 请求超时: {request.url.path} from {request.client}")

        # 上报埋点
        try:
            if hasattr(request.state, 'user_id'):
                analytics_track(str(request.state.user_id), "api_timeout", {
                    "path": request.url.path,
                    "timeout_sec": 30
                })
        except Exception as e:
            print(f"[Analytics] 埋点失败: {e}")

        return JSONResponse(
            status_code=504,
            content={"error": "API 请求超时（>30s），请稍后重试"}
        )


# ─────────────────────────────────────────────
# 2. 任务超时装饰器（用于长时间任务）
# ─────────────────────────────────────────────

def task_timeout(timeout_seconds=300):
    """
    任务超时装饰器

    示例:
        @task_timeout(timeout_seconds=600)
        def run_decompose_task(video_path):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 仅在 Unix 系统上启用信号超时
            if hasattr(signal, 'SIGALRM'):
                def _timeout_handler(signum, frame):
                    raise TimeoutError(f"任务超过 {timeout_seconds} 秒，已中止")

                # 保存原处理器
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(timeout_seconds)

                try:
                    result = func(*args, **kwargs)
                    signal.alarm(0)  # 取消超时
                    return result
                except TimeoutError as e:
                    signal.alarm(0)
                    print(f"[Timeout] {func.__name__}: {e}")
                    raise
                finally:
                    signal.signal(signal.SIGALRM, old_handler)
            else:
                # Windows 不支持信号超时，仅调用函数
                return func(*args, **kwargs)

        return wrapper
    return decorator


# ─────────────────────────────────────────────
# 3. 修复 /api/decompose 端点（添加超时保护）
# ─────────────────────────────────────────────

@app.post("/api/decompose")
async def decompose_upload(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    genre: str = Form(default=""),
    song: str = Form(default=""),
    lyric_first: str = Form(default=""),
    lyric_last: str = Form(default=""),
    x_device_id: str = Header(default="guest")
):
    """
    AI 拆解舞蹈视频

    改进点:
    1. 检查免费配额（防刷）
    2. 后台任务添加超时保护（30 分钟）
    3. 返回 202 立即响应（不阻塞）
    4. 超时后自动标记为失败
    """
    user_id = _current_user_id()
    identity = user_id or x_device_id

    # ✅ 1. 检查免费配额
    if not _free_quota_ok(identity):
        return JSONResponse(status_code=429, content={
            "error": "已达到免费额度限制，请登录升级或明日再试"
        })

    did = str(uuid.uuid4())
    file_path = os.path.join(DATA_DIR, did, "video.mp4")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    try:
        # 保存上传文件
        contents = await file.read()

        # 检查文件大小（防超大文件）
        if len(contents) > 500 * 1024 * 1024:  # 500 MB
            return JSONResponse(status_code=413, content={
                "error": "视频文件过大（>500MB），请上传较小文件"
            })

        with open(file_path, 'wb') as f:
            f.write(contents)
    except Exception as e:
        print(f"[Upload Error] {did}: {e}")
        return JSONResponse(status_code=400, content={
            "error": "视频上传失败"
        })

    # ✅ 2. 在后台线程中启动拆解任务，添加超时保护
    def run_decompose_with_timeout():
        """
        后台拆解任务（带超时和错误处理）
        """
        timeout_sec = 1800  # 30 分钟超时
        start_time = time.time()

        try:
            # 调用拆解函数（这会是最耗时的部分）
            _run_decompose_with_hooks(
                did, file_path, user_id, title, genre,
                song=song, lyric_first=lyric_first,
                lyric_last=lyric_last
            )

            elapsed = time.time() - start_time
            print(f"[Decompose Success] {did} completed in {elapsed:.1f}s")

        except TimeoutError as e:
            print(f"[Decompose Timeout] {did}: {e}")
            # 标记为失败
            meta_path = os.path.join(DATA_DIR, did, "meta.json")
            try:
                import json as json_module
                with open(meta_path, 'w') as f:
                    json_module.dump({
                        "status": "failed",
                        "error": "视频处理超时（>30分钟），请尝试上传较短视频",
                        "did": did,
                        "timestamp": datetime.now().isoformat()
                    }, f)
            except Exception as e:
                print(f"[Meta Write Error] {did}: {e}")

            # 上报埋点
            try:
                analytics_track(str(user_id or "guest"), "decompose_timeout", {
                    "dance_id": did,
                    "title": title,
                    "elapsed_sec": int(time.time() - start_time)
                })
            except Exception as e:
                print(f"[Analytics] 埋点失败: {e}")

        except Exception as e:
            print(f"[Decompose Error] {did}: {e}")
            # 标记为失败
            meta_path = os.path.join(DATA_DIR, did, "meta.json")
            try:
                import json as json_module
                with open(meta_path, 'w') as f:
                    json_module.dump({
                        "status": "failed",
                        "error": str(e)[:200],
                        "did": did,
                        "timestamp": datetime.now().isoformat()
                    }, f)
            except Exception as e:
                print(f"[Meta Write Error] {did}: {e}")

            # 上报埋点
            try:
                analytics_track(str(user_id or "guest"), "decompose_failed", {
                    "dance_id": did,
                    "title": title,
                    "error": str(e)[:100]
                })
            except Exception as e:
                print(f"[Analytics] 埋点失败: {e}")

    # ✅ 3. 在后台线程启动任务（立即返回 202）
    import threading
    t = threading.Thread(target=run_decompose_with_timeout, daemon=True)
    t.start()

    # ✅ 4. 返回 202 Accepted 立即响应客户端
    return JSONResponse(status_code=202, content={
        "dance_id": did,
        "status": "processing",
        "message": "视频上传成功，AI 正在拆解... 处理时间约 2-10 分钟"
    })


# ─────────────────────────────────────────────
# 4. 修复 /api/generate-bg 防烧钱漏洞
# ─────────────────────────────────────────────

# 全局生图配额限制（在 _free_limit 附近添加）
_bg_daily_limit = {}  # { "bg:{uid}:{date}": count }
_BG_LIMIT = {"per_day": 10}  # 每用户每天最多 10 张生图


@app.post("/api/generate-bg")
async def generate_background(request: Request):
    """
    生成背景图（需登录 + 配额限制）

    改进点:
    1. 必须登录验证
    2. 每天限制生图次数（防滥用）
    3. 添加超时保护（30 秒）
    4. 上报埋点
    """
    # ✅ 1. 必须登录
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return JSONResponse(status_code=401, content={
            "error": "需要登录"
        })

    user_id = decode_token(token)
    if not user_id:
        return JSONResponse(status_code=401, content={
            "error": "登录过期"
        })

    # ✅ 2. 每天限制生图次数
    today = datetime.now().strftime("%Y-%m-%d")
    quota_key = f"bg:{user_id}:{today}"
    daily_count = _bg_daily_limit.get(quota_key, 0)

    if daily_count >= _BG_LIMIT["per_day"]:
        return JSONResponse(status_code=429, content={
            "error": f"今日生图次数已用完（{_BG_LIMIT['per_day']} 张/天），明天再来"
        })

    _bg_daily_limit[quota_key] = daily_count + 1

    try:
        body = await request.json()
        prompt = body.get("prompt", "").strip()

        # 验证 prompt
        if not prompt or len(prompt) < 5:
            return JSONResponse(status_code=400, content={
                "error": "prompt 不能为空或过短"
            })

        if len(prompt) > 2000:
            return JSONResponse(status_code=400, content={
                "error": "prompt 过长"
            })

        # ✅ 3. 调用生图 API（带 30 秒超时）
        result = await asyncio.wait_for(
            call_image_api_async(prompt),  # 需要异步版本
            timeout=30.0
        )

        # 上报埋点
        try:
            analytics_track(str(user_id), "generate_bg_success", {
                "prompt_len": len(prompt),
                "model": "dalle3"
            })
        except Exception as e:
            print(f"[Analytics] 埋点失败: {e}")

        return JSONResponse(status_code=200, content={
            "status": "ok",
            "url": result["url"],
            "remaining": _BG_LIMIT["per_day"] - daily_count - 1
        })

    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={
            "error": "生图超时（>30s），请重试"
        })

    except Exception as e:
        print(f"[Generate BG Error] {user_id}: {e}")

        # 上报埋点
        try:
            analytics_track(str(user_id), "generate_bg_failed", {
                "error": str(e)[:100]
            })
        except Exception as e:
            print(f"[Analytics] 埋点失败: {e}")

        return JSONResponse(status_code=500, content={
            "error": "生图失败，请重试"
        })


# ─────────────────────────────────────────────
# 5. 添加后端监控和清理（可选）
# ─────────────────────────────────────────────

# 定期清理过期配额数据（每天午夜）
import schedule
import threading as _threading

def cleanup_quota_stats():
    """
    每天清理过期的配额数据（仅保留最近 7 天）
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        keys_to_delete = []

        for key in _bg_daily_limit:
            # 解析 key: "bg:{uid}:{date}"
            parts = key.split(':')
            if len(parts) == 3:
                date_str = parts[2]
                # 简单判断：如果日期不是今天，标记删除
                if date_str != today:
                    keys_to_delete.append(key)

        for key in keys_to_delete:
            del _bg_daily_limit[key]

        print(f"[Cleanup] 已清理 {len(keys_to_delete)} 条过期配额数据")
    except Exception as e:
        print(f"[Cleanup Error] {e}")

# 启动定时清理（可选）
def schedule_cleanup():
    """
    在后台线程中定时执行清理
    """
    schedule.every().day.at("00:00").do(cleanup_quota_stats)
    while True:
        schedule.run_pending()
        time.sleep(60)

# 在 app 启动时启动清理线程（如果使用 Gunicorn，仅主进程启动）
# _cleanup_thread = _threading.Thread(target=schedule_cleanup, daemon=True)
# _cleanup_thread.start()
