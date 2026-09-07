"""对比·并排视频(诚实版)
────────────────────────────────────────────────────────────
产品定义(Karen 拍板 0907):对比功能 = 用户传「自己跳的」+「原舞」→ 出左右并排同步视频。
纯视觉、100% 可靠,不产出任何分数/角度差 —— 因为单帧采样+左右翻转会算出假的 160°/22 分,
给用户看就是骗人(违「不做误导的假精确数字」红线)。段级差异排序等 engine 修好(多帧轨迹+
镜像不变匹配·待办#5)再加。本模块只做能诚实交付的那一半:并排视频。

流程:POST /api/sbs (传两支) → 后台 ffmpeg 拼 → GET /api/sbs/{id} 轮询 → /video 播放 / /download 下载。
不碰 review_compare 的测量,不碰 pay(先免费跑通;付费门后续按 hub_pay 加)。
"""
import os
import json
import uuid
import shutil
import threading
import subprocess

BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DATA_DIR = os.path.join(BASE_DIR, "data")

# CJK 字体(服务器 Linux 有 Noto·本地 mac 兜底)
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
FONT = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), "")

MAX_BYTES = 500 * 1024 * 1024  # 单支 500MB 上限


def _dir(sid):
    return os.path.join(DATA_DIR, "sbs_" + sid)


def _meta_path(sid):
    return os.path.join(_dir(sid), "meta.json")


def _read(sid):
    p = _meta_path(sid)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write(sid, meta):
    d = _dir(sid)
    os.makedirs(d, exist_ok=True)
    tmp = _meta_path(sid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, _meta_path(sid))


def _side_filter(font):
    """左「你」/ 右「原舞」各缩放 540x960 居中黑边 + 角标 + 中间金色分隔线。"""
    ff = (":fontfile=" + font) if font else ""
    left = ("[0:v]scale=540:960:force_original_aspect_ratio=decrease,"
            "pad=540:960:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            "drawtext=text=你" + ff + ":x=24:y=24:fontsize=46:fontcolor=white:"
            "box=1:boxcolor=0x000000AA:boxborderw=12[l]")
    right = ("[1:v]scale=540:960:force_original_aspect_ratio=decrease,"
             "pad=540:960:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
             "drawtext=text=原舞" + ff + ":x=24:y=24:fontsize=46:fontcolor=0xF5D77A:"
             "box=1:boxcolor=0x000000AA:boxborderw=12[r]")
    join = "[l][r]hstack=inputs=2,drawbox=x=538:y=0:w=4:h=960:color=0xC8A45C:t=fill[v]"
    return left + ";" + right + ";" + join


def _run_ffmpeg(sid, mine, std):
    out = os.path.join(_dir(sid), "sidebyside.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", mine, "-i", std,
        "-filter_complex", _side_filter(FONT),
        "-map", "[v]", "-map", "1:a?", "-shortest",
        "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
        "-c:a", "aac", "-b:a", "96k", out,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10000:
            _write(sid, {"id": sid, "status": "completed",
                         "video": "api/sbs/" + sid + "/video",
                         "download": "api/sbs/" + sid + "/download"})
        else:
            err = (r.stderr or b"").decode("utf-8", "ignore")[-600:]
            _write(sid, {"id": sid, "status": "failed", "error": "视频合成失败", "_detail": err})
    except subprocess.TimeoutExpired:
        _write(sid, {"id": sid, "status": "failed", "error": "视频过长处理超时,请上传更短的片段"})
    except Exception as e:
        _write(sid, {"id": sid, "status": "failed", "error": "视频合成异常", "_detail": str(e)[:300]})


# ------------------------------------------------------------------ APIRouter
try:
    from fastapi import APIRouter, UploadFile, File, HTTPException
    from fastapi.responses import FileResponse

    router = APIRouter(prefix="/api/sbs", tags=["compare-sidebyside"])

    async def _save(up, path):
        content = await up.read()
        if len(content) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="视频过大,请压到 500MB 以内")
        if len(content) < 1000:
            raise HTTPException(status_code=400, detail="视频为空或损坏,请重新选择")
        with open(path, "wb") as f:
            f.write(content)

    @router.post("")
    async def create_sbs(
        my_video: UploadFile = File(...),
        standard_video: UploadFile = File(...),
    ):
        """传「你跳的」+「原舞」→ 建任务 → 后台拼并排视频。返回 {id,status:processing}。"""
        sid = uuid.uuid4().hex[:12]
        d = _dir(sid)
        os.makedirs(d, exist_ok=True)
        mine = os.path.join(d, "mine.mp4")
        std = os.path.join(d, "std.mp4")
        try:
            await _save(my_video, mine)
            await _save(standard_video, std)
        except HTTPException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        _write(sid, {"id": sid, "status": "processing"})
        threading.Thread(target=_run_ffmpeg, args=(sid, mine, std), daemon=True).start()
        return {"id": sid, "status": "processing",
                "message": "两支已上传,正在生成并排视频。"}

    @router.get("/{sid}")
    def get_sbs(sid: str):
        m = _read(sid)
        if not m:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"id": sid, "status": m.get("status"),
                "video": m.get("video"), "download": m.get("download"),
                "error": m.get("error")}

    @router.get("/{sid}/video")
    def video_sbs(sid: str):
        p = os.path.join(_dir(sid), "sidebyside.mp4")
        if not os.path.exists(p):
            raise HTTPException(status_code=404, detail="视频尚未生成")
        return FileResponse(p, media_type="video/mp4")

    @router.get("/{sid}/download")
    def download_sbs(sid: str):
        p = os.path.join(_dir(sid), "sidebyside.mp4")
        if not os.path.exists(p):
            raise HTTPException(status_code=404, detail="视频尚未生成")
        return FileResponse(p, media_type="video/mp4",
                            filename="舞镜对比-" + sid + ".mp4")

except ImportError:
    router = None
