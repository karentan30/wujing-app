#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 任意舞自动拆解引擎（生产版·无librosa依赖）
用户上传任意舞蹈视频 → 固定八拍分段 → vision看每段自动描述动作 → 出八拍卡+故事卡+慢放切片。
无需选参考老师、无需预制breakdown。产物写 DATA_DIR/<id>/decompose.json。
"""
import os, json, math, base64, subprocess, tempfile, traceback, urllib.request, signal
import concurrent.futures as cf

BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DATA_DIR = os.path.join(BASE_DIR, "data")
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
EP = os.environ.get("ARK_VISION_EP", "ep-20260729155405-5l7dj")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_CHAT_MODEL = "deepseek-chat"

SEG_LEN = 3.3          # 每段目标秒数（≈130BPM的八拍）
MIN_SEG, MAX_SEG = 5, 10  # 段数上下限（控成本）
MPVENV = os.path.join(BASE_DIR, "mpvenv", "bin", "python3")  # 独立venv(mediapipe)
POSE_SCRIPT = os.path.join(BASE_DIR, "pose_angles.py")

# 关节角度中文名（点评/展示用）
ANGLE_CN = {"right_elbow": "右肘", "left_elbow": "左肘", "right_shoulder": "右肩(抬臂)",
            "left_shoulder": "左肩(抬臂)", "right_knee": "右膝", "left_knee": "左膝",
            "right_hip": "右髋", "left_hip": "左髋", "torso_tilt": "躯干倾斜"}

# 口诀词库（身韵八元素 + 延伸 + K-pop街舞）
_KOU_CLASSICAL = set("提沉冲靠含腆拧旋仰俯摆荡甩扬收落开展拢顿绷勾遮抬转点踏")
_KOU_KPOP     = set("弹锁定波隔爆指滑摇转钉推甩踏闪抖踢跳合交探拉稳冻踩")
_KOU_VOCAB    = _KOU_CLASSICAL | _KOU_KPOP
# 非动词黑名单（形容词/副词/名词误入kou时拦截）
_KOU_BLACKLIST = set("垂缓慢快轻重柔刚美丽优雅稳定流畅平顺自然舒展")


def _kou_words(kou):
    """解析kou字符串为单字列表，兼容—/-/--分隔符。"""
    return [w.strip() for w in kou.replace("—", "-").replace("--", "-").split("-") if w.strip()]


def _kou_format_ok(kou):
    """格式检查：必须用—，不能用-或--，每词单字，无黑名单词。"""
    if not kou:
        return False
    if "-" in kou and "—" not in kou:
        return False          # 纯连字符
    if "--" in kou:
        return False          # 双连字符
    words = _kou_words(kou)
    if any(len(w) > 1 for w in words):
        return False          # 复合词
    if any(w in _KOU_BLACKLIST for w in words):
        return False          # 非动词混入
    return True


def _kou_quality(phrases):
    """检查全视频口诀质量：格式/key去重/kou词重复/词库命中率。"""
    from collections import Counter
    issues = []
    # 1. 格式问题（-/--/复合词/非动词）
    for p in phrases:
        if not _kou_format_ok(p.get("kou", "")):
            issues.append(("bad_format", p["i"], p.get("kou", "")))
    # 2. key字在整支舞重复>2次
    key_counts = Counter(p.get("key", "") for p in phrases if p.get("key"))
    for k, cnt in key_counts.items():
        if cnt > 2:
            issues.append(("dup_key", k, cnt))
    # 3. kou字在整支舞重复>3次（整体多样性）
    all_kou_words = [w for p in phrases for w in _kou_words(p.get("kou", ""))]
    kou_counts = Counter(all_kou_words)
    for w, cnt in kou_counts.items():
        if cnt > 3:
            issues.append(("dup_kou_word", w, cnt))
    # 4. 词库命中率<50%
    for p in phrases:
        words = _kou_words(p.get("kou", ""))
        if not words:
            continue
        hit = sum(1 for w in words if w in _KOU_VOCAB)
        if hit / len(words) < 0.5:
            issues.append(("low_vocab", p["i"], p.get("kou", ""), hit, len(words)))
    return issues


def _retry_phrase_for_uniqueness(frame_path, p, used_keys, ark_key):
    """key字重复时重调vision，要求换一个不同的key字。"""
    idx, t0, t1 = p["i"], p.get("t0", 0), p.get("t1", 3)
    avoid = "、".join(sorted(used_keys))
    note = (f"这段当前key字「{p.get('key','')}」在整支舞里重复太多次了。"
            f"请重新生成，key字必须换一个不在以下列表里的字：{avoid}。"
            f"kou也尽量换不同的字，增加整支舞的多样性。")
    try:
        from urllib.request import Request
        key = ark_key
        prompt = (
            f"这是一支舞蹈第{idx}段(约{t0:.1f}-{t1:.1f}秒)的定格画面。你是专业舞蹈老师，"
            "用中文描述动作帮学员跟练。只输出JSON不要解释：\n"
            '{"name":"2-3字段名","action":"一句话带方向词","feet":"脚下和重心","intent":"意境一句话",'
            '"kou":"3-5个单字动词破折号连接，词库：提/沉/冲/靠/含/腆/拧/旋/仰/落/展/开/弹/锁/定/波/甩/踏",'
            '"key":"1个汉字，必须是kou里的字，且不在避免列表里"}'
            f"\n\n{note}"
        )
        body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 320,
                "input": [{"role": "user", "content": [
                    {"type": "input_image", "image_url": _b64(frame_path)},
                    {"type": "input_text", "text": prompt}]}]}
        req = Request(ARK_URL, data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        out = "".join(c.get("text", "") for o in r.get("output", []) if o.get("type") == "message"
                      for c in o.get("content", [])).strip()
        if out.startswith("```"):
            out = out.split("```")[1]
            if out.lstrip().lower().startswith("json"):
                out = out.lstrip()[4:]
        d2 = json.loads(out.strip())
        if d2.get("kou") and d2.get("key") and d2["key"] not in used_keys:
            p.update({k: d2[k] for k in ("kou", "key", "name", "action", "feet", "intent") if d2.get(k)})
            print(f"[dup_key fix] p{idx}: key→{d2['key']} kou→{d2['kou']}")
    except Exception as e:
        print(f"[dup_key fix] p{idx} failed: {e}")


def _user_friendly_error(exc_type, exc_msg):
    """异常 → 用户友好的中文错误消息（带改进建议）"""
    exc_str = str(exc_msg).lower()
    # 音频相关
    if "audio" in exc_str or "codec" in exc_str or "wav" in exc_str:
        return "视频音频有损坏，建议重新上传清晰的原始视频"
    # 帧提取/视频格式
    if "frame" in exc_str or "demux" in exc_str or "format" in exc_str or isinstance(exc_msg, ValueError):
        return "视频格式不兼容，建议用 MP4 或 MOV 格式"
    # 姿态检测失败
    if "pose" in exc_str or "keypoint" in exc_str or "skeleton" in exc_str:
        return "未检出清晰的人物姿态，建议选择光线清晰、人物占画面 1/3 的视频"
    # Vision API 失败
    if "vision" in exc_str or "ark" in exc_str or "401" in exc_str or "quota" in exc_str:
        return "AI 视觉服务暂时不可用，请稍后重试"
    # 网络/API 超时
    if "timeout" in exc_str or "connection" in exc_str or "resolve" in exc_str:
        return "网络连接超时，请检查网络后重试"
    # 全局超时（15分钟）
    if exc_type == TimeoutError or "15分钟" in exc_str:
        return "处理时间过长（>15分钟），建议用时长 60-120 秒的清晰视频"
    # 磁盘/内存
    if "disk" in exc_str or "space" in exc_str or "memory" in exc_str:
        return "服务器资源不足，请稍后重试"
    # 通用降级
    return "处理失败，请稍后重试或联系技术支持"


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _dur(path):
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _detect_bpm(video_path):
    """检测视频 BPM。优先 aubiotrack，fallback None。"""
    import tempfile as _tf
    tmp = _tf.mktemp(suffix=".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
                       "-ar", "44100", "-ac", "1", tmp],
                      check=True, timeout=30, capture_output=True)
        r = subprocess.run(["aubiotrack", "-i", tmp, "-O", "tempo"],
                          capture_output=True, text=True, timeout=20)
        bpms = [float(x) for x in r.stdout.strip().split()
                if x.replace('.', '').replace('-', '').isdigit() and 40 < float(x) < 240]
        if bpms:
            return round(sum(bpms) / len(bpms), 1)
    except Exception:
        pass
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    return None


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
    """MediaPipe 姿态角度(独立venv子进程)。返回 {'p1':{angles},...}。失败返回{}。
    ⭐ 新增：低置信度(visibility<0.5)的角度不喂点评，防止不可信数字污染护城河。
    """
    if not os.path.exists(MPVENV) or not frame_paths:
        return {}
    try:
        r = subprocess.run([MPVENV, POSE_SCRIPT] + frame_paths,
                           capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        # 高置信度过滤：visibility >= 0.50（能检出就用，低于50%的暗场/模糊/无人都过滤掉）
        result = {}
        for k, v in data.items():
            if isinstance(v, dict) and v.get("ok"):
                vis = v.get("visibility") or 0
                if vis >= 0.50:  # ✅ 高置信
                    result[k] = v.get("angles")
                # else: 低置信不返回角度，防污染点评
        return result
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
        f"这是一支舞蹈第{idx}段(约{t0:.1f}-{t1:.1f}秒)的定格画面。你是专业舞蹈老师，"
        "用中文描述动作帮学员跟练。只输出JSON不要解释：\n"
        '{"name":"2-3字段名，如 起势/开手/旋身/亮相",'
        '"action":"一句话：身体+手臂动作要点，带方向词（如右臂前抬至肩高，身体左拧45度）",'
        '"feet":"脚下和重心一句话",'
        '"intent":"这段的意境或情绪一句话",'
        '"kou":"3-5个单字动词用破折号「—」连接，像老师在课堂喊节拍一样俏皮好记。'
        '规则：①每词必须是1个汉字，禁用举扇/侧腰/回眸等2字复合词 '
        '②词序按动作先后，每个字给下一个字留余韵（顺势感，别戛然而止） '
        '③默念时每字一拍，4字为佳 '
        '④古典舞优先从身韵八元素取字：提/沉/冲/靠/含/腆/拧/旋，其次：仰/俯/摆/甩/扬/收/落/展/拢/顿/开 '
        '⑤K-pop/街舞用：弹/锁/定/波/隔/爆/指/滑/摇/转/钉/推/甩/踏（快去慢定、膝盖要给是关键） '
        '⑥示例古典：「提—冲—仰—落」「含—拧—展—沉」；K-pop：「弹—锁—甩—定」「波—隔—爆—钉」",'
        '"key":"1个汉字，必须是kou里某个字，选最难或最容易软掉/跳错的——古典舞常是「沉」或「含」，K-pop常是「定」或「弹」"}'
    )
    body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 320,
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
    # 口诀质量 loop：格式/内容不达标 → 自动重试一次（复用_kou_format_ok统一检测）
    kou_val = d.get("kou", "")
    key_val = d.get("key", "")
    words = _kou_words(kou_val)
    fmt_ok = _kou_format_ok(kou_val)
    key_missing = key_val and "—" in kou_val and key_val not in kou_val
    if not fmt_ok or key_missing or len(kou_val) < 4:
        reasons = []
        if "-" in kou_val and "—" not in kou_val: reasons.append("用了连字符-而非破折号—")
        if "--" in kou_val: reasons.append("用了--双连字符")
        bad_words = [w for w in words if len(w) > 1]
        if bad_words: reasons.append("含复合词%s必须改成单字" % bad_words)
        blacklisted = [w for w in words if w in _KOU_BLACKLIST]
        if blacklisted: reasons.append("含非动词%s（形容词/副词不能入口诀）" % blacklisted)
        if key_missing: reasons.append("key=%s不在口诀里" % key_val)
        try:
            retry_note = "上次不合格原因：%s。请重新生成，严格遵守：1)每词单字 2)用「—」连接 3)key必须是kou中的某个字" % "、".join(reasons)
            retry_body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 320,
                          "input": [{"role": "user", "content": [
                              {"type": "input_image", "image_url": _b64(frame_path)},
                              {"type": "input_text", "text": prompt + "\n\n" + retry_note}]}]}
            req2 = urllib.request.Request(ARK_URL, data=json.dumps(retry_body).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            r2 = json.loads(urllib.request.urlopen(req2, timeout=60).read())
            out2 = "".join(c.get("text", "") for o in r2.get("output", []) if o.get("type") == "message"
                           for c in o.get("content", [])).strip()
            if out2.startswith("```"):
                out2 = out2.split("```")[1]
                if out2.lstrip().lower().startswith("json"):
                    out2 = out2.lstrip()[4:]
            d2 = json.loads(out2.strip())
            new_kou = d2.get("kou", "")
            new_key = d2.get("key", "")
            if new_kou and len(new_kou) >= 4:
                d["kou"] = new_kou
                d["key"] = new_key
                print("[kou loop] %r → kou=%r key=%r" % (kou_val, new_kou, new_key))
        except Exception as _e:
            print("[kou loop] retry fail: %s" % _e)
    return {"i": idx, "t0": round(t0, 2), "t1": round(t1, 2),
            "name": d.get("name", ""), "full": (d.get("action", "") or "")[:14],
            "action": d.get("action", ""), "feet": d.get("feet", ""),
            "intent": d.get("intent", ""), "kou": d.get("kou", ""),
            "key": d.get("key", "")}


def _vision_coach(frame_paths, title, measured=None, phrases=None):
    """无参考点评：看关键帧+MediaPipe实测角度+口诀key字，给精准技术点评。禁空泛套话。失败抛异常上层兜底。"""
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
    kou_txt = ""
    if phrases:
        kou_lines = [
            f"第{p['i']}段「{p.get('name','')}」：口诀={p.get('kou','')}，key字=【{p.get('key','')}】（最难/最易跳错）"
            for p in phrases if p.get("kou")
        ]
        if kou_lines:
            kou_txt = ("\n【本视频各段口诀和key字·点评时对照这些字找问题】\n"
                       + "\n".join(kou_lines) + "\n")
    prompt = (
        f"这几张是一位学员跳《{title}》的定格画面（按先后顺序）。你是极其挑剔的资深舞蹈老师，"
        "给精准技术点评。\n" + meas_txt + kou_txt +
        "【铁律】必须具体：指名部位 + 当前位置/角度(尽量引用上面实测角度) + 应该到哪里 + 怎么改。"
        "点评时优先检查各段key字对应的动作是否到位（key字是最容易软掉/跳错的那个）。"
        "严禁空泛套话（如'身形舒展''很有美感''继续加油''加强核心力量'这类一律不许出现）。\n"
        "好点评示例：\n"
        "· '右臂现在抬到约肩平（90°），应再上送到斜上约45°，指尖领着延伸，肩别耸'\n"
        "· '旋身时重心偏在后脚，应压到主力腿正上方，头顶像有根线上提再转，才不晃'\n"
        "· '左手手腕塌了，应立腕、虎口撑圆，走弧线送出去'\n"
        "· '收势下巴略扬，应微含下颌、沉气，定住1秒别急着散'\n"
        "覆盖能看到的：手臂角度/高度、手腕手型、重心与主力腿、脊柱与含胸、头位下巴、脚下。\n"
        "如能判断问题出现在第几拍（按画面顺序第1/2/3…段），improve 条目里注明'第N拍'，方便学员定位。\n"
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
    key = os.environ.get("DS_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    ctx = "\n".join(
        f"{p['i']}.{p['name']}｜口诀:{p.get('kou','')}｜key字:{p.get('key','')}｜意境:{p['intent']}"
        for p in phrases
    )
    prompt = (f"你是资深舞蹈老师。下面是《{title}》按八拍自动拆的分段（含每段口诀和key字）：\n{ctx}\n\n"
              "请生成一张故事卡帮舞者跳出感觉。只输出严格JSON不要markdown：\n"
              '{"title":"故事标题(8字以内)","body":"150字以内情感叙事，讲这支舞的意境和该跳出的眼神状态，不被截断",'
              '"chain":"把每段的kou口诀字串成一首押韵短歌，每段对应一句，句句押同一韵脚，朗朗上口跳舞时能默念。'
              '必须用各段已有的kou字（如「提—冲—仰—落」→ 提冲仰落），不要另造新词。'
              '示例格式：提冲仰落气贯通/含拧展沉意从容/弹锁甩定一拍停/波隔爆钉力到终。'
              '段数和口诀一一对应，押同一个韵脚"}')
    body = json.dumps({"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 1600, "temperature": 0.7}).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=90).read())["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    return json.loads(raw.strip())


def _claude_runthrough(phrases, title, genre):
    """DeepSeek 生成「过一遍剧本」——演员读完能顺下来的连贯口播文字。
    失败返回空串，不阻塞主流程。
    """
    key = os.environ.get("DS_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return ""
    is_guofeng = "guofeng" in genre or "古" in genre or "国风" in genre
    style_hint = "古典/国风舞，语言优美有意境" if is_guofeng else "K-pop/流行舞，语言简洁有节奏感"
    ctx = "\n".join(
        f"{p['i']}. {p['name']}｜口诀:{p.get('kou','')}｜key字【{p.get('key','')}】｜{p['action']}  脚下：{p['feet']}"
        for p in phrases
    )
    prompt = f"""这是《{title}》的动作拆解（{style_hint}）：

{ctx}

请写一段「过一遍剧本」，让演员读完就能顺着把整支舞跳下来。

要求：
- 一段话，不分段，不加序号
- 用「接着」「随之」「紧接着」「同时」「然后」把每个动作自然连起来
- 写出身体在空间中的方向和流动感，不只是动作名
- 每段的key字【】是这段最难/最容易跳错的动作，在对应位置用口语点出来（如"——这里「沉」要真的落下去，别浮着"）
- 古典舞用意象语言（如"如柳枝随风"），K-pop用节奏语言（如"卡在第3拍，钉住！"）
- 150-220字，不截断

只输出剧本文字，不要标题不要解释。"""

    body = json.dumps({
        "model": DEEPSEEK_CHAT_MODEL,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body, headers={
        "Authorization": f"Bearer {key}",
        "content-type": "application/json"
    })
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[runthrough] failed: {e}")
        return ""


def _write(did, obj):
    with open(os.path.join(DATA_DIR, did, "decompose.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)




def _assign_lyrics_deepseek(phrases, song, lyric_first, lyric_last):
    if not (song or lyric_first):
        return
    try:
        key = os.environ.get("DS_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
        n = len(phrases)
        prompt = (
            f"歌曲：《{song}》  首句：{lyric_first}  末句：{lyric_last}\n"
            f"请从这首歌中选 {n} 句歌词，按顺序分配给舞蹈每一段，适合作配字显示。\n"
            f"只输出JSON数组，长度精确 {n}，每项是一句歌词字符串，不要解释。"
        )
        body = json.dumps({"model": "deepseek-chat",
                           "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 400, "temperature": 0.3}).encode()
        req = urllib.request.Request(DEEPSEEK_URL, data=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        raw = json.loads(urllib.request.urlopen(req, timeout=30).read())
        text = raw["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
        lines = json.loads(text.strip())
        if isinstance(lines, list):
            for i, p in enumerate(phrases):
                if i < len(lines) and isinstance(lines[i], str):
                    p["lyric"] = lines[i]
    except Exception as e:
        print(f"[lyrics_ds] failed: {e}")


def whisper_align_lyrics(video_path, phrases, song="", lyric_first="", lyric_last=""):
    """Whisper 时间戳对齐歌词；失败返回 False"""
    import tempfile
    tmp_audio = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
                        "-ar", "16000", "-ac", "1", tmp_audio],
                       check=True, timeout=60, capture_output=True)
    except Exception as e:
        print(f"[whisper] 音频提取失败: {e}")
        return False
    try:
        import whisper as _whisper
        model = _whisper.load_model("base")
        result = model.transcribe(tmp_audio, language="zh", task="transcribe")
        segments = result.get("segments", [])
        print(f"[whisper] 识别到 {len(segments)} 段")
        if not segments:
            return False
        matched = 0
        for p in phrases:
            t0, t1 = p["t0"], p["t1"]
            best_seg, best_overlap = None, 0.0
            for seg in segments:
                overlap = min(seg["end"], t1) - max(seg["start"], t0)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_seg = seg
            if best_seg and best_overlap > 0.3:
                p["lyric"] = best_seg["text"].strip()
                matched += 1
        return matched > 0
    except Exception as e:
        print(f"[whisper] 识别失败: {e}")
        return False
    finally:
        try:
            os.remove(tmp_audio)
        except Exception:
            pass


_MEM_JOINTS = ["right_elbow", "left_elbow", "right_shoulder", "left_shoulder",
               "right_knee", "left_knee", "right_hip", "left_hip", "torso_tilt"]


def _analyze_memory(phrases, pose):
    """纯几何记忆分析:用每段中点姿态的关节角度,按'平均每关节角度差'找起手相近的段。
    绝对尺度(不受离群段影响) + complete-linkage(组内两两都相近) + 有效维守卫。
    副作用:给 phrases[i] 写 'rep'(≈八拍j) / 'rep_solo'(独立难点)。
    返回富记忆卡 dict;数据不足或聚类不可信→保守不标重复。零 AI 成本。
    ⚠️ 只看每段中点单帧的静态姿态,不含运动轨迹/朝向,故措辞只说"起手相近可对照",不断言"同一个动作"。"""
    try:
        n = len(phrases)
        if n < 2:
            return None
        MIN_VALID = 5     # 有效关节<5的段不参与判定(测不准→诚实不标)
        MEAN_DEG = 12.0   # 平均每关节角度差 < 12°
        MAX_DEG = 30.0    # 且 任一关节角度差 < 30°(防"腿一样但一条手臂差很多"被误判相近)
        segs = []
        for p in phrases:
            a = (pose or {}).get(f"p{p.get('i')}") or p.get("angles") or {}
            segs.append({j: (None if a.get(j) is None else float(a.get(j))) for j in _MEM_JOINTS})

        def valid_ct(s):
            return sum(1 for j in _MEM_JOINTS if s[j] is not None)

        def similar(a, b):
            ds = [abs(a[j] - b[j]) for j in _MEM_JOINTS if a[j] is not None and b[j] is not None]
            if len(ds) < MIN_VALID:
                return False
            return (sum(ds) / len(ds)) < MEAN_DEG and max(ds) < MAX_DEG

        # complete-linkage 分组:一段只能加入"与组内全体都相近"的组
        groups = []  # [[idx,...], ...]
        for k in range(n):
            if valid_ct(segs[k]) < MIN_VALID:
                continue
            placed = False
            for g in groups:
                if all(similar(segs[k], segs[m]) for m in g):
                    g.append(k)
                    placed = True
                    break
            if not placed:
                groups.append([k])
        rep_idx = [g for g in groups if len(g) > 1]
        # 兜底:整支被并成一组(覆盖全部有效段)→ 聚类不可信,不标重复
        valid_n = sum(1 for s in segs if valid_ct(s) >= MIN_VALID)
        if len(rep_idx) == 1 and valid_n and len(rep_idx[0]) >= valid_n:
            rep_idx = []
        in_group = set(m for g in rep_idx for m in g)

        # 逐段标记:组内非首段→≈组首;有效但不在任何组→独立难点;测不准→不标
        for k, p in enumerate(phrases):
            p["rep"] = ""
            p.pop("rep_solo", None)
            if valid_ct(segs[k]) < MIN_VALID:
                continue
            grp = next((g for g in rep_idx if k in g), None)
            if grp:
                if k != grp[0]:
                    p["rep"] = f"≈八拍{grp[0] + 1}"
            else:
                p["rep_solo"] = True

        rep_groups = [[m + 1 for m in g] for g in rep_idx]
        isolated = [k + 1 for k, p in enumerate(phrases) if p.get("rep_solo")]
        save_count = sum(len(g) - 1 for g in rep_idx)

        # 锚点:肩外展角最大=手举最高;屈膝角最小=下沉最低(措辞只说"手举/下沉",不说"身体")
        def seg_avg(i, joints):
            vals = [segs[i][j] for j in joints if segs[i][j] is not None]
            return sum(vals) / len(vals) if vals else None

        sh = [(i, seg_avg(i, ["right_shoulder", "left_shoulder"])) for i in range(n)]
        kn = [(i, seg_avg(i, ["right_knee", "left_knee"])) for i in range(n)]
        sh = [(i, v) for i, v in sh if v is not None]
        kn = [(i, v) for i, v in kn if v is not None]
        high = max(sh, key=lambda t: t[1])[0] + 1 if sh else None
        low = min(kn, key=lambda t: t[1])[0] + 1 if kn else None
        return {
            "title": "记忆卡 · 速记攻略",
            "hint": "先记骨架 → 起手相近的对照着记 → 独立难点单独练 → 用高低点记顺序",
            "n8": n,
            "rep_groups": rep_groups,      # 组内起手姿势相近,可对照记,如 [[1,3]]
            "isolated": isolated,          # 独立难点·没有相近段可借
            "anchors": {"high": high, "low": low},
            "save_count": save_count,      # 有几处起手相近可对照
            "features": ["正常速", "慢速 0.5×", "镜像版"],
        }
    except Exception as e:
        print(f"[memory] 记忆分析失败(降级): {e}")
        return None


def run_decompose(did, video_path, user_id, title="我的舞", genre="guofeng",
                  song="", lyric_first="", lyric_last=""):
    """后台任务：拆解一支任意上传的舞。全程兜底，绝不留半成品。
    ✨ 改进：中间进度反馈 + user-friendly错误消息 + 全局15分钟超时保护
    """
    # 全局超时保护：15分钟兜底。⚠️ signal 只能在主线程装，而生产所有调用方
    # (server.py/pay.py) 都在 threading.Thread 里跑 → 非主线程装 signal 会抛
    # "signal only works in main thread" 直接崩掉整支拆解。故仅主线程启用，
    # 子线程优雅跳过(不崩;各外部调用本身有 urllib/ffmpeg 超时兜底)。
    import threading as _threading
    _alarm_on = False

    def _timeout_handler(signum, frame):
        raise TimeoutError("AI 处理超时（>15分钟）")
    if _threading.current_thread() is _threading.main_thread():
        try:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(900)  # 900秒 = 15分钟
            _alarm_on = True
        except (ValueError, OSError):
            _alarm_on = False

    ddir = os.path.join(DATA_DIR, did)
    os.makedirs(os.path.join(ddir, "frames"), exist_ok=True)
    os.makedirs(os.path.join(ddir, "clips"), exist_ok=True)
    result = {"id": did, "user_id": user_id, "title": title, "genre": genre,
              "song": song, "lyric_first": lyric_first, "lyric_last": lyric_last,
              "bpm": None, "status": "processing", "progress": "准备中..."}
    _write(did, result)
    try:
        dur = _dur(video_path)
        if dur <= 0:
            raise RuntimeError("无法读取视频时长（文件损坏或非视频）")

        result["progress"] = "检测节奏..."
        _write(did, result)
        bpm = _detect_bpm(video_path)
        if bpm and 40 < bpm < 220:
            bar_dur = 60.0 / bpm * 8  # 一个八拍时长
            n = max(MIN_SEG, min(MAX_SEG, round(dur / bar_dur)))
            seg = dur / n
            print(f"[bpm] {bpm} BPM → 八拍={bar_dur:.2f}s → {n}段")
        else:
            bpm = None
            n = max(MIN_SEG, min(MAX_SEG, round(dur / SEG_LEN)))
            seg = dur / n
        result["bpm"] = bpm
        bounds = [round(i * seg, 2) for i in range(n)] + [round(dur, 2)]

        result["progress"] = f"提取帧画 (1/{n}段)..."
        _write(did, result)
        STRIP = 4  # 每段胶片帧数（照established八拍卡.py设计）
        for i in range(n):
            t0, t1 = bounds[i], bounds[i + 1]
            # 中帧(pose/vision用)
            _grab(video_path, (t0 + t1) / 2, os.path.join(ddir, "frames", f"p{i+1}.jpg"))
            # 胶片条：段内均匀4帧，展示动作全过程
            for k in range(STRIP):
                t = t0 + (t1 - t0) * (k + 0.5) / STRIP
                _grab(video_path, t, os.path.join(ddir, "frames", f"p{i+1}_{k}.jpg"))

        result["progress"] = "检测姿态..."
        _write(did, result)
        # MediaPipe 逐帧真实关节角度（测量·非AI猜）
        pose = _run_pose([os.path.join(ddir, "frames", f"p{i+1}.jpg") for i in range(n)])

        result["progress"] = f"生成动作描述 (1/{n}段)..."
        _write(did, result)
        def _desc(i):
            t0, t1 = bounds[i], bounds[i + 1]
            try:
                return _vision_describe(os.path.join(ddir, "frames", f"p{i+1}.jpg"), i + 1, t0, t1)
            except Exception as e:
                # Vision 失败降级：用分段名替代，继续流程不阻塞
                return {"i": i + 1, "t0": round(t0, 2), "t1": round(t1, 2),
                        "name": f"第{i+1}段", "full": "", "action": "",
                        "feet": "", "intent": "", "kou": "", "fallback": True}
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            phrases = sorted(ex.map(_desc, range(n)), key=lambda x: x["i"])
        # 挂真实角度到每段
        for p in phrases:
            p["angles"] = pose.get(f"p{p['i']}")

        # ── Harness：全视频口诀质量检查 ──────────────────────────────────
        result["progress"] = "口诀质量检查..."
        _write(did, result)
        q_issues = _kou_quality(phrases)
        if q_issues:
            ark_key_env = os.environ.get("ARK_API_KEY", "")
            from collections import Counter
            # 1. 格式问题：-/--/复合词/非动词 → 重试
            if ark_key_env:
                for p in phrases:
                    if not _kou_format_ok(p.get("kou", "")):
                        frame_path = os.path.join(ddir, "frames", f"p{p['i']}.jpg")
                        if os.path.exists(frame_path):
                            used_set = set(p.get("key", "") for p in phrases if p.get("key"))
                            _retry_phrase_for_uniqueness(frame_path, p, used_set, ark_key_env)
                            print(f"[harness fmt] p{p['i']} fixed: {p.get('kou','')}")
            # 2. key字重复>2次 → 换字
            key_counts = Counter(p.get("key", "") for p in phrases if p.get("key"))
            dup_keys = {k for k, cnt in key_counts.items() if cnt > 2}
            if dup_keys and ark_key_env:
                used_set = set(p.get("key", "") for p in phrases)
                for p in phrases:
                    if p.get("key") in dup_keys:
                        used_set.discard(p.get("key", ""))
                        frame_path = os.path.join(ddir, "frames", f"p{p['i']}.jpg")
                        if os.path.exists(frame_path):
                            _retry_phrase_for_uniqueness(frame_path, p, used_set, ark_key_env)
                        used_set.add(p.get("key", ""))
            # 3. kou词全视频重复>3次 → log（不自动修，代价太高）
            for issue in q_issues:
                if issue[0] == "dup_kou_word":
                    print(f"[harness] kou字「{issue[1]}」全视频出现{issue[2]}次，多样性偏低")
                elif issue[0] == "low_vocab":
                    print(f"[harness] p{issue[1]} kou={issue[2]} 词库命中{issue[3]}/{issue[4]}")
        # ─────────────────────────────────────────────────────────────────

        # 歌词对齐：whisper 优先，fallback DeepSeek
        if song or lyric_first:
            aligned = whisper_align_lyrics(video_path, phrases, song, lyric_first, lyric_last)
            if not aligned:
                _assign_lyrics_deepseek(phrases, song, lyric_first, lyric_last)

        # 串联口诀（用 key 字拼）
        keys = [p.get("key", "") for p in phrases]
        if any(keys):
            mnemo = "  ".join(k for k in keys if k) + "  ·  " + "  ".join(k for k in keys if k)
            mnemo = "  ".join(k for k in keys if k)
            result["mnemo"] = mnemo
            result["mnemo_sub"] = "  >  ".join(
                f"{p.get('key','')}({p.get('name','')})" for p in phrases if p.get("key")
            )

        # 每段正常切片（慢放0.5×=前端playbackRate·镜像=前端scaleX(-1)·无需重复编码）
        for i in range(n):
            t0, t1 = bounds[i], bounds[i + 1]
            _clip(video_path, t0, t1, os.path.join(ddir, "clips", f"p{i+1}.mp4"), slow=None)

        result["progress"] = "生成故事卡..."
        _write(did, result)
        try:
            story = _deepseek_story(title, phrases)
            # Harness：验证chain是否真的用了kou字，不合格重试一次
            chain = story.get("chain", "")
            kou_words_all = [w for p in phrases
                             for w in p.get("kou", "").replace("—", "-").split("-") if w]
            chain_hits = sum(1 for w in kou_words_all if w in chain)
            if kou_words_all and chain_hits / len(kou_words_all) < 0.4:
                print(f"[harness] chain kou命中率低({chain_hits}/{len(kou_words_all)})，重试")
                story2 = _deepseek_story(title, phrases)
                chain2 = story2.get("chain", "")
                hits2 = sum(1 for w in kou_words_all if w in chain2)
                if hits2 > chain_hits:
                    story = story2
        except Exception:
            story = {"title": title, "body": "", "chain": ""}

        result["progress"] = "生成过一遍剧本..."
        _write(did, result)
        runthrough = _claude_runthrough(phrases, title, genre)

        # 无参考 AI 点评（看首/中/尾帧直接评价用户跳得怎样）
        result["progress"] = "生成点评卡..."
        _write(did, result)
        try:
            # 均匀取最多5帧覆盖全程，点评更全更准
            pick = sorted(set(max(1, round(1 + i * (n - 1) / 4)) for i in range(5)))
            key_frames = [os.path.join(ddir, "frames", f"p{k}.jpg") for k in pick]
            measured = [(k, pose.get(f"p{k}")) for k in pick]
            coach = _vision_coach(key_frames, title, measured, phrases)
        except Exception:
            # Coach 失败降级：显示"未检出"而不是隐藏卡片
            coach = {"title": "AI 点评", "tips": "暂无检测结果", "fallback": True}

        # 记忆卡 = 速记攻略(重复组/独立难点/高低点) + 整支跟练视频
        result["progress"] = "生成记忆卡..."
        _write(did, result)
        memory = _analyze_memory(phrases, pose) or {
            "title": "记忆卡 · 整支跟练",
            "hint": "看整支 → 慢速逐帧看清 → 镜像版对着跟跳（左右和你一致）",
            "features": ["正常速", "慢速 0.5×", "镜像版"]}
        memory["video"] = f"api/decompose/{did}/clip/full"

        # vision 自动判定的风格覆盖默认（修复 genre 一律 guofeng 的坑）
        det_genre = (coach or {}).get("genre")
        if det_genre in ("guofeng", "kpop"):
            result["genre"] = det_genre

        result["progress"] = "保存卡片..."
        result.update({"bpm": result.get("bpm"), "dur": round(dur, 1), "phrases": phrases, "strip": STRIP,
                       "story": story, "runthrough": runthrough, "memory": memory, "coach": coach, "status": "completed"})
        _write(did, result)
        if _alarm_on:
            signal.alarm(0)  # 取消全局超时
    except Exception as e:
        if _alarm_on:
            signal.alarm(0)  # 取消全局超时
        result["status"] = "failed"
        exc_type, exc_val = type(e).__name__, str(e)
        user_msg = _user_friendly_error(type(e), exc_val)
        result["error"] = user_msg  # 前端显示
        result["error_log"] = f"{exc_type}: {exc_val}\n{traceback.format_exc()[-500:]}"  # 日志记录
        _write(did, result)


def get_decompose(did):
    p = os.path.join(DATA_DIR, did, "decompose.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
