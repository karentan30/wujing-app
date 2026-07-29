import os
import json
import subprocess
import cv2
import numpy as np
import traceback
import sqlite3
from cards import generate_cards, generate_coach_note

BASE_DIR = "/www/wujing-api"
DATA_DIR = os.path.join(BASE_DIR, "data")
TEACHER_DIR = "/www/wujing"
DB_PATH = os.path.join(BASE_DIR, "wujing.db")

TEACHER_KEYS = ["yue", "yueyuan", "chengmo"]

# Chinese feedback templates keyed by score range
_SEVERITY_ADJ = [
    (0.5, "severe", "大幅偏差", "需要重点攻克"),
    (0.7, "moderate", "明显偏差", "需要多加练习"),
    (0.85, "mild", "小幅偏差", "稍加注意即可"),
    (1.0, "minor", "基本到位", "保持即可"),
]

_PROBLEM_TEMPLATES = [
    ("身体角度", "你的身体角度与参考不一致。注意肩部和髋部的对齐，保持躯干稳定。",
     "对镜慢练：先摆到老师的角度，记住身体各部位的位置感，反复对比调整。"),
    ("手臂姿态", "手臂的位置和弧度与老师有差异。手腕到指尖的延伸线条需要调整。",
     "放慢速度做手臂动作，在最大延伸处停住检查——手腕、肘尖、指尖是否在一条流畅的弧线上。"),
    ("重心转移", "重心转移的时机和幅度不够准确，影响了整体姿态。",
     "专练重心转换：慢速做，感受重量从一只脚移到另一只的过程，保持上身平稳不晃。"),
    ("头部方向", "头部方向和视线与老师不一致。眼神和头位是舞蹈表达的关键。",
     "练习时先定好头的方向：转头时让视线领先半拍，想象用目光画出一条轨迹。"),
    ("脚步位置", "脚步的位置和间距与参考有差距，影响了下盘的稳定性。",
     "在地上贴标记练脚步：标出每一步的落点，反复走直到形成肌肉记忆。"),
    ("身体延伸", "身体的延伸感不够，缺少从核心到末端的贯通力量。",
     "想象有一根线从头顶往上拉，同时指尖往远延伸——从头到脚完全展开再做动作。"),
    ("节奏配合", "动作的节奏和音乐节拍配合不够精准，有提前或滞后。",
     "用节拍器或原曲打拍子：先听节拍再动，确保每个重拍对应动作的最大幅度点。"),
    ("肩部放松", "肩膀紧张上提，导致上半身僵硬，失去流动感。",
     "做动作前先沉肩：深吸气→呼气时肩膀自然下沉，保持这个放松感再做动作。"),
    ("腰部发力", "腰部的核心发力不足，影响了转身和姿态的控制。",
     "练习平板支撑增强核心力量。动作时想象用腰腹带动四肢，而不是光用手臂发力。"),
    ("手型细节", "手型和手指的细节不够讲究，缺少古典舞的韵味。",
     "对镜检查手型：兰花指/剑指/握拳是否标准，指尖的力度和方向是否到位。"),
]

_WORDS = [
    "身体姿态", "手臂角度", "重心控制", "头部引导",
    "脚步位置", "身体延伸", "节奏配合", "肩部放松",
    "腰部发力", "手型细节", "眼神表达", "呼吸节奏",
    "旋转平衡", "发力方式", "动作幅度", "收放节奏",
]


def get_teacher_video(teacher_key):
    path = os.path.join(TEACHER_DIR, teacher_key, "reference.mp4")
    if os.path.exists(path):
        return path
    clips_dir = os.path.join(TEACHER_DIR, "clips")
    if os.path.isdir(clips_dir):
        clips = sorted([f for f in os.listdir(clips_dir) if f.endswith((".mp4", ".mov"))])
        if clips:
            return os.path.join(clips_dir, clips[0])
    return None


def get_teacher_breakdown(teacher_key):
    path = os.path.join(TEACHER_DIR, teacher_key, "breakdown.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"phrases": [{"name": "full", "t0": 0, "duration": 30}]}


def extract_frame(video_path, timestamp, output_path, size=(480, -1)):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scale = f"scale={size[0]}:{size[1]}" if size[1] > 0 else f"scale={size[0]}:-1"
    cmd = [
        "ffmpeg", "-y", "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1", "-q:v", "2",
        "-vf", scale,
        output_path
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def create_slowmo(input_path, t0, duration, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_path = output_path.replace(".mp4", "_temp.mp4")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(t0), "-i", input_path,
            "-t", str(duration), "-c", "copy", temp_path
        ], capture_output=True, timeout=60)
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            return False
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_path,
            "-vf", "setpts=4*PTS", "-af", "atempo=0.25",
            output_path
        ], capture_output=True, timeout=120)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception:
        return False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def compare_frames(student_path, teacher_path):
    s = cv2.imread(student_path)
    t = cv2.imread(teacher_path)
    if s is None or t is None:
        return 0.0, None
    s = cv2.resize(s, (480, 640))
    t = cv2.resize(t, (480, 640))
    gray_s = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY)
    gray_t = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_s, gray_t)
    score = float(1.0 - (np.sum(diff) / (480.0 * 640.0 * 255.0)))
    score = max(0.0, min(1.0, score))
    diff_color = cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
    diff_color[diff > 30] = (0, 0, 255)
    diff_path = student_path.replace(".jpg", "_diff.jpg")
    cv2.imwrite(diff_path, diff_color)
    return score, diff_path


def generate_feedback(score, problem_num, phrase_name, timestamp):
    """Generate Chinese feedback from SSIM score + frame position."""
    score = max(0.0, min(1.0, score))

    # Determine severity
    severity = "moderate"
    adj = "需要改进"
    for threshold, sev, adj_sev, _ in _SEVERITY_ADJ:
        if score <= threshold:
            severity = sev
            adj = adj_sev
            break

    # Pick template based on problem index + timestamp
    tidx = (problem_num + int(timestamp or 0)) % len(_PROBLEM_TEMPLATES)
    title, detail, fix = _PROBLEM_TEMPLATES[tidx]

    # If score is very high, it's actually a good match not a problem
    if score >= 0.92:
        return {
            "problem": f"#{problem_num}: 姿态基本准确",
            "detail": f"这一拍的姿态和老师参考非常接近（匹配度{round(score * 100)}%），继续保持。",
            "fix": "注意细节微调，可以参考慢放视频对比自己的每一个关节位置。",
            "severity": "minor",
            "match_score": round(score * 100, 1)
        }

    problem_txt = f"#{problem_num}: {title}——{adj}"
    detail_txt = f"{detail} 当前帧与老师参考的匹配度约{round(score * 100)}%，{adj}。"
    fix_txt = fix

    if phrase_name and phrase_name != "full":
        detail_txt += f"（对应舞段：{phrase_name}）"

    return {
        "problem": problem_txt,
        "detail": detail_txt,
        "fix": fix_txt,
        "severity": severity,
        "match_score": round(score * 100, 1)
    }


def run_analysis(review_id, student_video_path, teacher_key):
    review_dir = os.path.join(DATA_DIR, review_id)
    os.makedirs(review_dir, exist_ok=True)
    try:
        teacher_video = get_teacher_video(teacher_key)
        breakdown = get_teacher_breakdown(teacher_key)
        phrases = breakdown.get("phrases", [{"name": "full", "t0": 0, "duration": 30}])
        if not teacher_video:
            raise FileNotFoundError(f"No teacher video found for key: {teacher_key}")
        frame_dir = os.path.join(review_dir, "frames")
        os.makedirs(frame_dir, exist_ok=True)
        frame_pairs = []
        for phrase in phrases[:10]:
            t0 = phrase.get("t0", 0)
            name = phrase.get("name", f"p_{t0}")
            s_path = os.path.join(frame_dir, f"s_{name}.jpg")
            t_path = os.path.join(frame_dir, f"t_{name}.jpg")
            s_ok = extract_frame(student_video_path, t0, s_path)
            t_ok = extract_frame(teacher_video, t0, t_path)
            if s_ok and t_ok:
                frame_pairs.append((s_path, t_path, t0, name))
        if not frame_pairs:
            raise RuntimeError("Could not extract any valid frame pairs")
        # 豆包 vision 真评分(关思考+压图), 只评关键帧, 并行提速; 失败自动回退像素对比
        import vision_score
        from concurrent.futures import ThreadPoolExecutor

        def _score_one(fp):
            s_path, t_path, t0, name = fp
            v = vision_score.score_pair(s_path, t_path, name)
            if v is not None:
                sc100, problem, good = v
                return {"s01": sc100 / 100.0, "s_path": s_path, "t_path": t_path,
                        "t0": t0, "name": name, "problem": problem, "good": good, "vision": True}
            sc01, diff_path = compare_frames(s_path, t_path)
            return {"s01": sc01, "s_path": s_path, "t_path": t_path,
                    "t0": t0, "name": name, "problem": "", "good": "", "vision": False}

        with ThreadPoolExecutor(max_workers=6) as ex:
            scored = list(ex.map(_score_one, frame_pairs[:6]))
        scored.sort(key=lambda x: x["s01"])
        problems = []
        for i, sp in enumerate(scored[:5]):
            sc = sp["s01"]
            if sp["vision"] and sp["problem"]:
                analysis = {
                    "id": i + 1,
                    "name": sp["name"],
                    "problem": sp["problem"],
                    "fix": sp["good"] or "对照老师慢练这一拍，注意上面提到的差异。",
                    "match_score": round(sc * 100, 1),
                }
            else:
                analysis = generate_feedback(sc, i + 1, sp["name"], sp["t0"])
            analysis["timestamp"] = sp["t0"]
            problems.append(analysis)
            slowmo_path = os.path.join(review_dir, "slowmo", f"problem_{i+1}.mp4")
            create_slowmo(student_video_path, max(0, sp["t0"] - 0.5), 3.0, slowmo_path)
        if scored:
            avg_score = sum(x["s01"] for x in scored) / len(scored)
            overall_score = max(1, min(100, int(avg_score * 100)))
            dims = {
                "overall": overall_score,
                "posture": max(1, min(100, overall_score + 5)),
                "timing": max(1, min(100, overall_score - 2)),
                "alignment": max(1, min(100, overall_score + 3))
            }
        else:
            overall_score = 50
            dims = {"overall": 50, "posture": 50, "timing": 50, "alignment": 50}
        scored.sort(key=lambda x: x["s01"], reverse=True)
        highlights = []
        for i, sp in enumerate(scored[:3]):
            sc, name, t0 = sp["s01"], sp["name"], sp["t0"]
            label = name if name != "full" else f"第{round(t0)}秒位置"
            emoji = "🌟" if sc >= 0.9 else "👍" if sc >= 0.8 else "💪"
            fb = sp["good"] if (sp["vision"] and sp["good"]) else f"匹配度 {round(sc * 100)}%，做得不错！"
            highlights.append({
                "name": name,
                "timestamp": t0,
                "match_score": round(sc * 100, 1),
                "feedback": f"{emoji} {label}——{fb}"
            })
        # 三张卡：八拍卡/故事卡/记忆卡 + 老师点评指导 (DeepSeek, 便宜)
        cards_data = generate_cards(breakdown, overall_score)
        cards_data["coach"] = generate_coach_note(overall_score, problems, breakdown.get("title", "这支舞"))
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE reviews SET score=?, dims=?, problems=?, highlights=?, cards=?, status='completed' WHERE id=?",
            (overall_score, json.dumps(dims, ensure_ascii=False),
             json.dumps(problems, ensure_ascii=False),
             json.dumps(highlights, ensure_ascii=False),
             json.dumps(cards_data, ensure_ascii=False), review_id)
        )
        conn.commit()
        conn.close()
        result = {
            "id": review_id,
            "teacher_key": teacher_key,
            "score": overall_score,
            "dims": dims,
            "problems": problems,
            "highlights": highlights,
            "cards": cards_data,
            "status": "completed"
        }
        with open(os.path.join(review_dir, "review.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_msg = traceback.format_exc()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE reviews SET status='failed' WHERE id=?", (review_id,))
        conn.commit()
        conn.close()
        with open(os.path.join(review_dir, "error.txt"), "w") as f:
            f.write(error_msg)
