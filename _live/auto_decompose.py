#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 任意舞自动拆解引擎（生产版·无librosa依赖）
用户上传任意舞蹈视频 → 固定八拍分段 → vision看每段自动描述动作 → 出八拍卡+故事卡+慢放切片。
无需选参考老师、无需预制breakdown。产物写 DATA_DIR/<id>/decompose.json。
"""
import os, json, math, base64, subprocess, tempfile, traceback, urllib.request
import concurrent.futures as cf

BASE_DIR = "/www/wujing-api"
DATA_DIR = os.path.join(BASE_DIR, "data")
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
EP = os.environ.get("ARK_VISION_EP", "ep-20260729155405-5l7dj")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

SEG_LEN = 3.3          # 每段目标秒数（≈130BPM的八拍）
MIN_SEG, MAX_SEG = 5, 10  # 段数上下限（控成本）
MPVENV = os.path.join(BASE_DIR, "mpvenv", "bin", "python3")  # 独立venv(mediapipe)
POSE_SCRIPT = os.path.join(BASE_DIR, "pose_angles.py")

# 关节角度中文名（点评/展示用）
ANGLE_CN = {"right_elbow": "右肘", "left_elbow": "左肘", "right_shoulder": "右肩(抬臂)",
            "left_shoulder": "左肩(抬臂)", "right_knee": "右膝", "left_knee": "左膝",
            "right_hip": "右髋", "left_hip": "左髋", "torso_tilt": "躯干倾斜"}


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _dur(path):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _grab(src, t, out):
    _run(["ffmpeg", "-y", "-ss", f"{t}", "-i", src, "-frames:v", "1",
          "-q:v", "3", "-vf", "scale=360:-1", out])


def _clip(src, t0, t1, out, slow=None):
    dur = max(0.1, t1 - t0)
    if slow:
        mult = 1.0 / slow
        _run(["ffmpeg", "-y", "-i", src, "-ss", f"{t0}", "-t", f"{dur}",
              "-filter:v", f"setpts={mult}*PTS", "-an",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", out])
    else:
        # -ss 在 -i 前=快速seek·-c copy 不重编码(慢放/镜像是前端做的·段切片不需重编码)。45s→20s
        _run(["ffmpeg", "-y", "-ss", f"{t0}", "-i", src, "-t", f"{dur}",
              "-c", "copy", "-avoid_negative_ts", "make_zero", out])


def _b64(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def _run_pose(frame_paths):
    """MediaPipe 姿态角度(独立venv子进程)。返回 {'p1':{angles},...}。失败返回{}。"""
    if not os.path.exists(MPVENV) or not frame_paths:
        return {}
    try:
        r = subprocess.run([MPVENV, POSE_SCRIPT] + frame_paths,
                           capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        # 只信高置信度的角度(护城河:不可信的角度比没有更伤·模糊/无人过滤掉)
        return {k: v.get("angles") for k, v in data.items()
                if isinstance(v, dict) and v.get("ok") and (v.get("visibility") or 0) >= 0.55}
    except Exception:
        return {}


def _fmt_angles(a):
    """角度dict→紧凑中文串，供点评prompt引用真实测量值。"""
    if not a:
        return ""
    return "、".join(f"{ANGLE_CN.get(k, k)}{int(v)}°" for k, v in a.items() if v is not None)


def _vision_describe(frame_path, idx, t0, t1):
    """豆包 vision 看一帧自动描述动作。关思考+压图=便宜(~¥0.007)。失败抛异常由上层兜底。"""
    key = os.environ["ARK_API_KEY"]
    prompt = (
        f"这是一支舞蹈第{idx}段(约{t0:.1f}-{t1:.1f}秒)的定格画面。你是资深舞蹈老师，"
        "用中文描述这个动作帮学员跟练。只输出JSON不要解释：\n"
        '{"name":"2-3字段名如 起势/开手/旋身/亮相","action":"一句话身体和手臂动作要点",'
        '"feet":"脚下和重心一句话","intent":"这段的意境或情绪一句话","kou":"3-4字记忆口诀如 举—望—转"}'
    )
    body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 260,
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_url": _b64(frame_path)},
                {"type": "input_text", "text": prompt}]}]}
    req = urllib.request.Request(ARK_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = "".join(c.get("text", "") for o in r.get("output", []) if o.get("type") == "message"
                  for c in o.get("content", [])).strip()
    if out.startswith("```"):
        out = out.split("```")[1]
        if out.lstrip().lower().startswith("json"):
            out = out.lstrip()[4:]
    d = json.loads(out.strip())
    return {"i": idx, "t0": round(t0, 2), "t1": round(t1, 2),
            "name": d.get("name", ""), "full": (d.get("action", "") or "")[:14],
            "action": d.get("action", ""), "feet": d.get("feet", ""),
            "intent": d.get("intent", ""), "kou": d.get("kou", "")}


def _vision_coach(frame_paths, title, measured=None):
    """无参考点评：看关键帧+MediaPipe实测角度，给精准技术点评。禁空泛套话。失败抛异常上层兜底。"""
    key = os.environ["ARK_API_KEY"]
    imgs = [{"type": "input_image", "image_url": _b64(p)} for p in frame_paths[:5]]
    meas_txt = ""
    if measured:
        rows = []
        for k, a in measured:
            s = _fmt_angles(a)
            if s:
                rows.append(f"第{k}段实测：{s}")
        if rows:
            meas_txt = ("\n【MediaPipe 实测关节角度·这是客观测量值，点评必须引用这些真实数字】\n"
                        + "\n".join(rows) + "\n")
    prompt = (
        f"这几张是一位学员跳《{title}》的定格画面（按先后顺序）。你是极其挑剔的资深舞蹈老师，"
        "给精准技术点评。\n" + meas_txt +
        "【铁律】必须具体：指名部位 + 当前位置/角度(尽量引用上面实测角度) + 应该到哪里 + 怎么改。"
        "严禁空泛套话（如'身形舒展''很有美感''继续加油''加强核心力量'这类一律不许出现）。\n"
        "好点评示例：\n"
        "· '右臂现在抬到约肩平（90°），应再上送到斜上约45°，指尖领着延伸，肩别耸'\n"
        "· '旋身时重心偏在后脚，应压到主力腿正上方，头顶像有根线上提再转，才不晃'\n"
        "· '左手手腕塌了，应立腕、虎口撑圆，走弧线送出去'\n"
        "· '收势下巴略扬，应微含下颌、沉气，定住1秒别急着散'\n"
        "覆盖能看到的：手臂角度/高度、手腕手型、重心与主力腿、脊柱与含胸、头位下巴、脚下。\n"
        "只输出JSON不要解释：\n"
        '{"genre":"这支舞风格,只填 guofeng(古典/国风/民族/古风) 或 kpop(K-pop/爆款/流行/手势舞)",'
        '"comment":"一句总印象(20字内，真诚不夸)","good":["2条真正做到位的·必须点名部位和位置"],'
        '"improve":["3条改进·每条必须含 部位+当前状态+目标角度或位置+怎么做"]}'
    )
    body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 600,
            "input": [{"role": "user", "content": imgs + [{"type": "input_text", "text": prompt}]}]}
    req = urllib.request.Request(ARK_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = "".join(c.get("text", "") for o in r.get("output", []) if o.get("type") == "message"
                  for c in o.get("content", [])).strip()
    if out.startswith("```"):
        out = out.split("```")[1]
        if out.lstrip().lower().startswith("json"):
            out = out.lstrip()[4:]
    d = json.loads(out.strip())
    return {"comment": d.get("comment", ""), "good": d.get("good", []) or [],
            "improve": d.get("improve", []) or [],
            "genre": d.get("genre", "")}


def _deepseek_story(title, phrases):
    key = os.environ["DEEPSEEK_API_KEY"]
    ctx = "\n".join(f"{p['i']}.{p['name']}｜{p['action']}｜意境:{p['intent']}" for p in phrases)
    prompt = (f"你是资深舞蹈老师。下面是《{title}》按八拍自动拆的分段：\n{ctx}\n\n"
              "请生成一张故事卡帮舞者跳出感觉。只输出严格JSON不要markdown：\n"
              '{"title":"故事标题","body":"120字以内情感叙事，讲这支舞的意境和该跳出的眼神状态",'
              '"chain":"把整支舞串成一句好记的联想口诀"}')
    body = json.dumps({"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 800, "temperature": 0.7}).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=90).read())["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    return json.loads(raw.strip())


def _write(did, obj):
    with open(os.path.join(DATA_DIR, did, "decompose.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def run_decompose(did, video_path, user_id, title="我的舞", genre="guofeng"):
    """后台任务：拆解一支任意上传的舞。全程兜底，绝不留半成品。"""
    ddir = os.path.join(DATA_DIR, did)
    os.makedirs(os.path.join(ddir, "frames"), exist_ok=True)
    os.makedirs(os.path.join(ddir, "clips"), exist_ok=True)
    result = {"id": did, "user_id": user_id, "title": title, "genre": genre, "status": "processing"}
    _write(did, result)
    try:
        dur = _dur(video_path)
        if dur <= 0:
            raise RuntimeError("无法读取视频时长（文件损坏或非视频）")
        n = max(MIN_SEG, min(MAX_SEG, round(dur / SEG_LEN)))
        seg = dur / n
        bounds = [round(i * seg, 2) for i in range(n)] + [round(dur, 2)]

        STRIP = 4  # 每段胶片帧数（照established八拍卡.py设计）
        for i in range(n):
            t0, t1 = bounds[i], bounds[i + 1]
            # 中帧(pose/vision用)
            _grab(video_path, (t0 + t1) / 2, os.path.join(ddir, "frames", f"p{i+1}.jpg"))
            # 胶片条：段内均匀4帧，展示动作全过程
            for k in range(STRIP):
                t = t0 + (t1 - t0) * (k + 0.5) / STRIP
                _grab(video_path, t, os.path.join(ddir, "frames", f"p{i+1}_{k}.jpg"))

        # MediaPipe 逐帧真实关节角度（测量·非AI猜）
        pose = _run_pose([os.path.join(ddir, "frames", f"p{i+1}.jpg") for i in range(n)])

        def _desc(i):
            t0, t1 = bounds[i], bounds[i + 1]
            try:
                return _vision_describe(os.path.join(ddir, "frames", f"p{i+1}.jpg"), i + 1, t0, t1)
            except Exception as e:
                return {"i": i + 1, "t0": round(t0, 2), "t1": round(t1, 2),
                        "name": f"第{i+1}段", "full": "", "action": "(此段描述生成失败)",
                        "feet": "", "intent": "", "kou": ""}
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            phrases = sorted(ex.map(_desc, range(n)), key=lambda x: x["i"])
        # 挂真实角度到每段
        for p in phrases:
            p["angles"] = pose.get(f"p{p['i']}")

        # 每段正常切片（慢放0.5×=前端playbackRate·镜像=前端scaleX(-1)·无需重复编码）
        for i in range(n):
            t0, t1 = bounds[i], bounds[i + 1]
            _clip(video_path, t0, t1, os.path.join(ddir, "clips", f"p{i+1}.mp4"), slow=None)

        try:
            story = _deepseek_story(title, phrases)
        except Exception:
            story = {"title": title, "body": "", "chain": ""}

        # 无参考 AI 点评（看首/中/尾帧直接评价用户跳得怎样）
        try:
            # 均匀取最多5帧覆盖全程，点评更全更准
            pick = sorted(set(max(1, round(1 + i * (n - 1) / 4)) for i in range(5)))
            key_frames = [os.path.join(ddir, "frames", f"p{k}.jpg") for k in pick]
            measured = [(k, pose.get(f"p{k}")) for k in pick]
            coach = _vision_coach(key_frames, title, measured)
        except Exception:
            coach = None

        # 记忆卡 = 整支视频卡（前端支持 慢速/镜像 跟练）
        memory = {"title": "记忆卡 · 整支跟练",
                  "hint": "看整支 → 慢速逐帧看清 → 镜像版对着跟跳（左右和你一致）",
                  "video": f"api/decompose/{did}/clip/full",
                  "features": ["正常速", "慢速 0.5×", "镜像版"]}

        # vision 自动判定的风格覆盖默认（修复 genre 一律 guofeng 的坑）
        det_genre = (coach or {}).get("genre")
        if det_genre in ("guofeng", "kpop"):
            result["genre"] = det_genre

        result.update({"bpm": None, "dur": round(dur, 1), "phrases": phrases, "strip": STRIP,
                       "story": story, "memory": memory, "coach": coach, "status": "completed"})
        _write(did, result)
    except Exception:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()[-500:]
        _write(did, result)


def get_decompose(did):
    p = os.path.join(DATA_DIR, did, "decompose.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
