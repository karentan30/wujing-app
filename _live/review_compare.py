#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 独舞 AI 点评「比对层」（诚实实测版）

定位：拆解引擎的「有参考」出口。拆解把任意舞变成带真实关节角度指纹的分段；
本层拿用户跳的按同样分段用姿态引擎实测角度，跟标准逐关节做差 → 出 76 分式点评。

诚实红线（写进引擎，不是口号）：
  1. 测不到就说测不到 —— 某段检测不到骨架（暗场/遮挡/多人/半身）→ 该段不产角度、不产分，
     报告标「此段画面无法测量」，绝不用邻段/模板顶替。
  2. 数字必须可回溯 —— 每个「38°」都对应标准/我的两个实测值 + 段号 + 时间戳，
     前端问题卡展开显示「标准 X° · 你 Y°（差 Z°）」两个真数字并排。
  3. 文案引用真数字 —— 复用 _vision_coach 铁律 prompt（禁「身形舒展/很有美感/继续加油」），
     把实测差值喂进 prompt，改正建议 = 部位 + 当前 X° + 目标 Y° + 怎么改。
  4. 低置信不给高分 —— 可测段比例 < LOW_CONF_RATIO → 不出总分，出「建议重拍」，重拍按钮顶上来。

技术脱敏：对外一律「舞镜 AI 逐帧测量」，不出现 MediaPipe / SSIM / landmark。
明确弃用老 analyze.py 的 SSIM 像素差 + 随机模板文案（那会编数字），本层不接入它。

复用（不重造）：
  - 拆段 / 抽帧 / 切片：auto_decompose 的 SEG_LEN / _grab / _clip / _dur
  - 测角度：pose_angles.py（独立 mpvenv 子进程，visibility≥0.55 门槛，暗场重试）——一字不改
  - 点评文案：_vision_coach 铁律 prompt + _fmt_angles，加「标准 vs 我的差值」上下文

产物：DATA_DIR/<review_id>/review.json（前端契约见 §5.4）。

—— 挂载说明（收口在主控，本文件不碰 server.py / pay.py）——
  1) server.py 顶部加：`from review_compare import router as solo_router`
     并在 `app.include_router(pay_router)` 附近加：`app.include_router(solo_router)`。
  2) 付费回调触发：本文件的 run_solo_review 与 auto_decompose.run_decompose 同形（后台线程可直接调）。
     pay.py 现有 _run_dance_breakdown 走 run_decompose；独舞线复用同一「awaiting_payment→付费回调」模式时，
     主控在履约分支按 review.json 里 kind=="solo_review" 改调 run_solo_review(review_id) 即可（本文件已提供
     可从磁盘自恢复入参的 run_solo_review_from_disk，付费回调只需 review_id 一个参数，零耦合）。
"""
import os
import json
import traceback

# 复用拆解引擎的常量与工具（同 _live 目录，一字不改地借用）。
from auto_decompose import (
    DATA_DIR, SEG_LEN, MIN_SEG, MAX_SEG, ANGLE_CN,
    _dur, _grab, _clip, _run_pose, _fmt_angles, _vision_coach, get_decompose,
)

# ---- 可调阈值（诚实门槛，全部有据） ----
LOW_CONF_RATIO = 0.40      # 可测段比例 < 40% → 不出总分，改「建议重拍」
GOOD_MATCH_DELTA = 5.0     # 单关节偏差 ≤5° 视为「到位」（亮点判定）
STRIP = 4                  # 每段胶片帧数（与 auto_decompose 对齐）
STD_GENRE = "guofeng"

# 镜像一致性用的左右对称关节对（同一姿态该对称时，左右角度差越小越一致）。
_MIRROR_PAIRS = [
    ("left_elbow", "right_elbow"),
    ("left_shoulder", "right_shoulder"),
    ("left_knee", "right_knee"),
    ("left_hip", "right_hip"),
]

# 参与「动作延展度」的关节（绝对角度差；torso_tilt 受机位影响大，仅作参考不计入主分）。
_EXT_JOINTS = ["right_elbow", "left_elbow", "right_shoulder", "left_shoulder",
               "right_knee", "left_knee", "right_hip", "left_hip"]


# ------------------------------------------------------------------ 内部工具

def _review_dir(review_id):
    return os.path.join(DATA_DIR, review_id)


def _write(review_id, obj):
    os.makedirs(_review_dir(review_id), exist_ok=True)
    with open(os.path.join(_review_dir(review_id), "review.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def get_review(review_id):
    """读独舞点评报告 JSON（前端 GET /api/solo/review/{id} 用）。不存在返回 None。"""
    p = os.path.join(_review_dir(review_id), "review.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _clamp_score(x):
    return max(0, min(100, int(round(x))))


def _severity(delta):
    """按最大关节偏差定严重度。阈值有据：>25° 明显走形=重点改正，>12°=需注意。"""
    if delta is None:
        return "minor"
    if delta >= 25:
        return "major"
    return "minor"


def _joint_delta(std_ang, mine_ang, joints):
    """逐关节做差 → {joint:{std,mine,delta}}，只保留两边都实测到的关节。"""
    out = {}
    if not std_ang or not mine_ang:
        return out
    for j in joints:
        s, m = std_ang.get(j), mine_ang.get(j)
        if s is None or m is None:
            continue
        out[j] = {"std": round(s, 1), "mine": round(m, 1), "delta": round(abs(s - m), 1)}
    return out


def _extension_score(std_ang, mine_ang):
    """动作延展度：各关节 |标准°−我的°| 归一化。返回 (0-100 或 None, 逐关节差字典)。
    40° 差记满扣（大幅走形）；测不到关节则该关节不计入（不编）。"""
    diffs = _joint_delta(std_ang, mine_ang, _EXT_JOINTS)
    if not diffs:
        return None, {}
    avg = sum(d["delta"] for d in diffs.values()) / len(diffs)
    score = _clamp_score(100 - (avg / 40.0) * 100)
    return score, diffs


def _mirror_score(mine_ang):
    """镜像一致性：左右对称关节角度差。相对指标，比绝对角度更抗机位差异。
    返回 (0-100 或 None)。25° 记满扣。"""
    if not mine_ang:
        return None
    diffs = []
    for a, b in _MIRROR_PAIRS:
        va, vb = mine_ang.get(a), mine_ang.get(b)
        if va is None or vb is None:
            continue
        diffs.append(abs(va - vb))
    if not diffs:
        return None
    avg = sum(diffs) / len(diffs)
    return _clamp_score(100 - (avg / 25.0) * 100)


def _peak_time_of_segment(std_ang, mine_ang):
    """占位：真正的节拍峰值需逐帧幅度曲线；v1 诚实降级——无 BPM 不硬折算成「拍」。
    返回 None 表示本段不产节拍偏移（方案 §八 扣分项 1：v1 先只报秒，不假装报拍）。"""
    return None


# ------------------------------------------------------------------ 标准取角度

def _standard_segments(standard_ref):
    """取标准的分段角度。
    A/C 入口：standard_ref={"kind":"decompose_id","id":<did>} → 直接读缓存 decompose.json 的 phrases[].angles。
    B   入口：standard_ref={"kind":"video","path":<mp4>}       → 现拆标准视频，逐段测角度。
    返回 [{"i":int,"t0":float,"t1":float,"angles":dict|None}, ...]（i 从 1 起）。测不到的段 angles=None。
    """
    kind = standard_ref.get("kind")

    if kind == "decompose_id":
        d = get_decompose(standard_ref["id"])
        if not d or d.get("status") != "completed":
            raise RuntimeError("标准舞尚未拆解完成，无法作为对标（请先拆解该舞或换一个已拆好的标准）")
        segs = []
        for p in d.get("phrases", []):
            segs.append({"i": p["i"], "t0": p.get("t0", 0.0), "t1": p.get("t1", 0.0),
                         "angles": p.get("angles")})
        if not segs:
            raise RuntimeError("标准舞无分段数据")
        return segs

    if kind == "video":
        path = standard_ref["path"]
        segs = _measure_video_segments(path, tag="std")
        return segs

    raise RuntimeError(f"未知标准来源 kind={kind}")


def _bounds_for(dur, n_hint=None):
    """按 auto_decompose 同规则算固定分段边界。n_hint 给定则对齐标准段数（我的视频对齐标准）。"""
    if dur <= 0:
        raise RuntimeError("无法读取视频时长（文件损坏或非视频）")
    n = n_hint if n_hint else max(MIN_SEG, min(MAX_SEG, round(dur / SEG_LEN)))
    n = max(1, int(n))
    seg = dur / n
    bounds = [round(i * seg, 2) for i in range(n)] + [round(dur, 2)]
    return n, bounds


def _measure_video_segments(video_path, tag, n_hint=None, review_id=None, save_frames=False):
    """对一支视频按固定分段抽中帧，用姿态引擎逐段实测角度。
    返回 [{"i","t0","t1","angles"(None=测不到)}]。save_frames=True 时把帧落到 review 目录（供对比帧/慢放）。"""
    dur = _dur(video_path)
    n, bounds = _bounds_for(dur, n_hint=n_hint)

    if save_frames and review_id:
        fdir = os.path.join(_review_dir(review_id), "frames")
        os.makedirs(fdir, exist_ok=True)
    else:
        import tempfile
        fdir = tempfile.mkdtemp(prefix=f"wj_{tag}_")

    mid_paths = []
    for i in range(n):
        t0, t1 = bounds[i], bounds[i + 1]
        mp_path = os.path.join(fdir, f"{tag}{i + 1}.jpg")
        _grab(video_path, (t0 + t1) / 2, mp_path)
        mid_paths.append(mp_path)
        if save_frames and review_id:
            # 胶片条帧（前端可选展示动作全过程）
            for k in range(STRIP):
                t = t0 + (t1 - t0) * (k + 0.5) / STRIP
                _grab(video_path, t, os.path.join(fdir, f"{tag}{i + 1}_{k}.jpg"))

    # 一次批量测（姿态子进程模型只加载一次）。返回 {'mine1':{angles}} 只含 visibility≥0.55 的。
    pose = _run_pose(mid_paths)
    segs = []
    for i in range(n):
        t0, t1 = bounds[i], bounds[i + 1]
        segs.append({"i": i + 1, "t0": round(t0, 2), "t1": round(t1, 2),
                     "angles": pose.get(f"{tag}{i + 1}")})  # None = 该段测不到（不编）
    return segs, bounds, n


# ------------------------------------------------------------------ 核心比对

def compare_segments(std_segs, my_segs):
    """标准段 × 我的段逐段逐关节做差 → 每段偏差 + 维度分素材。
    返回 {
      "per_seg": [{i,t0,t1,measurable,ext_score,mirror_score,joint_diffs,worst_joint,worst_delta,beat_offset}],
      "measured_ratio": float,
    }
    诚实：任一侧该段测不到 → measurable=False，该段不产分（不用邻段/模板顶）。
    """
    std_by_i = {s["i"]: s for s in std_segs}
    per_seg = []
    measurable = 0
    total = 0
    for my in my_segs:
        i = my["i"]
        std = std_by_i.get(i)
        total += 1
        my_ang = my.get("angles")
        std_ang = std.get("angles") if std else None

        row = {"i": i, "t0": my.get("t0"), "t1": my.get("t1"),
               "measurable": False, "ext_score": None, "mirror_score": None,
               "joint_diffs": {}, "worst_joint": None, "worst_delta": None,
               "beat_offset": None}

        # 双侧都测到才算可测（这是诚实命门：缺一侧就标测不到）。
        if my_ang and std_ang:
            ext_s, diffs = _extension_score(std_ang, my_ang)
            mir_s = _mirror_score(my_ang)
            if diffs:
                worst_j = max(diffs, key=lambda k: diffs[k]["delta"])
                row.update({"measurable": True, "ext_score": ext_s, "mirror_score": mir_s,
                            "joint_diffs": diffs, "worst_joint": worst_j,
                            "worst_delta": diffs[worst_j]["delta"],
                            "beat_offset": _peak_time_of_segment(std_ang, my_ang)})
                measurable += 1
        per_seg.append(row)

    ratio = (measurable / total) if total else 0.0
    return {"per_seg": per_seg, "measured_ratio": round(ratio, 2),
            "measurable_count": measurable, "total": total}


def _dim_scores(cmp):
    """从逐段偏差聚合四维分。可测段太少的维度返回 None（不编分）。"""
    per = [s for s in cmp["per_seg"] if s["measurable"]]
    ext_vals = [s["ext_score"] for s in per if s["ext_score"] is not None]
    mir_vals = [s["mirror_score"] for s in per if s["mirror_score"] is not None]
    ext = _clamp_score(sum(ext_vals) / len(ext_vals)) if ext_vals else None
    mir = _clamp_score(sum(mir_vals) / len(mir_vals)) if mir_vals else None
    # 节拍：v1 无 BPM，不产可测分（诚实降级）。有 beat_offset 段时才给相对提示，暂标 None。
    timing = None
    return {"extension": ext, "mirror": mir, "timing": timing}


def _build_problems(cmp, coach):
    """偏差最大的 Top5 段 → problems[]（含 std/mine/delta 真值 + 可回溯段号时间）。
    文案：优先用 _vision_coach 的 improve（引用了实测角度）；否则用可回溯的实测差值兜底句（仍不空泛）。"""
    measurable = [s for s in cmp["per_seg"] if s["measurable"] and s["worst_delta"] is not None]
    measurable.sort(key=lambda s: s["worst_delta"], reverse=True)
    top = measurable[:5]

    coach_improve = list((coach or {}).get("improve", []) or [])
    problems = []
    for idx, s in enumerate(top):
        wj = s["worst_joint"]
        jd = s["joint_diffs"].get(wj, {})
        std_v, mine_v, delta = jd.get("std"), jd.get("mine"), jd.get("delta")
        cn = ANGLE_CN.get(wj, wj)
        # detail：可回溯真数字（不空泛）。fix：优先 coach 的引数字建议，缺则实测兜底句。
        detail = (f"{cn}：标准约 {int(std_v)}°，你约 {int(mine_v)}°，差 {int(delta)}°。"
                  "舞镜 AI 逐帧测量得出，可对照慢放核对。")
        fix = coach_improve[idx] if idx < len(coach_improve) else \
            (f"把{cn}从当前约 {int(mine_v)}° 调向标准 {int(std_v)}°，慢练这一段专门找这个角度，"
             "比整段重复更有效。")
        problems.append({
            "seg": s["i"], "t": s["t0"], "severity": _severity(delta),
            "title": f"{cn}偏差较大（差约 {int(delta)}°）",
            "joint": wj, "std": std_v, "mine": mine_v, "delta": delta,
            "beat_offset": s.get("beat_offset"),
            "detail": detail, "fix": fix,
            "slowmo": None, "frames": None,  # 由主控/切片阶段回填 URL（见下 run 流程）
        })
    return problems


def _build_highlights(cmp):
    """偏差最小的 Top2 可测段 → 亮点（真实：差 <5% 才叫到位）。"""
    measurable = [s for s in cmp["per_seg"] if s["measurable"] and s["worst_delta"] is not None]
    measurable.sort(key=lambda s: s["worst_delta"])
    out = []
    for s in measurable[:2]:
        if s["worst_delta"] <= GOOD_MATCH_DELTA:
            cn = ANGLE_CN.get(s["worst_joint"], s["worst_joint"])
            out.append({"seg": s["i"], "t": s["t0"],
                        "detail": f"第{s['i']}段{cn}与标准差仅约 {int(s['worst_delta'])}°，延展到位，是全段技术最好的一拍。"})
    return out


def _build_dims(dim, coach):
    """四维输出（前端契约）。情感维度诚实降级：measured=False + note，val 来自 vision 定性（非测量）。"""
    dims = []
    dims.append({"key": "timing", "name": "节拍契合度",
                 "val": dim["timing"], "measured": dim["timing"] is not None,
                 "note": None if dim["timing"] is not None else "v1 暂只报秒级偏移，未折算成拍"})
    dims.append({"key": "extension", "name": "动作延展度",
                 "val": dim["extension"], "measured": dim["extension"] is not None,
                 "note": None if dim["extension"] is not None else "本次可测画面不足，未出此维分"})
    dims.append({"key": "mirror", "name": "镜像一致性",
                 "val": dim["mirror"], "measured": dim["mirror"] is not None,
                 "note": None if dim["mirror"] is not None else "本次可测画面不足，未出此维分"})
    # 情感：姿态引擎测不了 → 诚实标「AI 观察·非测量」。给一个视觉参考区间但明确非分数。
    dims.append({"key": "emotion", "name": "情感表达力",
                 "val": None, "measured": False, "note": "AI 观察 · 非测量",
                 "observe": (coach or {}).get("comment", "") or ""})
    return dims


def _weighted_total(dim):
    """总分 = 可测维度加权平均（明确「可测维度综合」，非玄学总评）。情感不计入分。
    可测维度全缺 → None。"""
    weights = {"extension": 0.45, "mirror": 0.35, "timing": 0.20}
    num = 0.0
    den = 0.0
    for k, w in weights.items():
        v = dim.get(k)
        if v is not None:
            num += v * w
            den += w
    if den == 0:
        return None
    return _clamp_score(num / den)



def _run_vision_only_review(review_id, my_video, title, result_placeholder):
    """Vision-only fallback when reference has no angle data.
    Uses _vision_coach on user video frames — real AI feedback, no comparison score."""
    rdir = _review_dir(review_id)
    fdir = os.path.join(rdir, "frames")
    os.makedirs(fdir, exist_ok=True)
    try:
        dur = _dur(my_video)
        n = max(3, min(5, int(dur / 3)))
        frame_paths = []
        for i in range(n):
            t = dur * (i + 0.5) / n
            p = os.path.join(fdir, f"mine{i+1}.jpg")
            _grab(my_video, t, p)
            if os.path.exists(p):
                frame_paths.append(p)
        coach = None
        if frame_paths:
            try:
                coach = _vision_coach(frame_paths, title)
            except Exception:
                coach = None
        if not coach:
            result_placeholder.update({"status": "failed",
                "message": "AI 视觉分析失败，请确保视频光线充足、全身入镜后重试"})
            _write(review_id, result_placeholder)
            return
        problems = []
        for i, item in enumerate(coach.get("improve", [])[:3]):
            problems.append({"seg": i + 1,
                "severity": "severe" if i == 0 else "mild",
                "title": item.split("：")[0].strip() if "：" in item else item[:20],
                "detail": item, "fix": "", "slowmo": None, "frames": None})
        highlights = [{"seg": 0, "desc": h} for h in coach.get("good", [])[:2]]
        result_placeholder.update({"status": "completed", "score": None,
            "score_note": "纯视觉分析模式 · 无参考角度数据，不出对比分",
            "measured_ratio": 0, "vision_only": True, "dims": [],
            "problems": problems, "highlights": highlights,
            "coach_comment": coach.get("comment", "")})
        _write(review_id, result_placeholder)
    except Exception as e:
        result_placeholder.update({"status": "failed", "message": f"分析失败：{str(e)[:100]}"})
        _write(review_id, result_placeholder)

# ------------------------------------------------------------------ 顶层编排

def run_solo_review(review_id, my_video, standard_ref, title="我的舞", mode="reference", user_id=None):
    """后台任务：独舞 AI 点评主流程。全程兜底，绝不留半成品（照拆解引擎风格）。
    入参:
      review_id   本次点评 id（data/<review_id>/ 已存 my_video）
      my_video    用户自己跳的视频路径
      standard_ref  {"kind":"decompose_id","id":<did>} | {"kind":"video","path":<mp4>}
      mode        reference | self | progress（仅标注用途）
    产物: data/<review_id>/review.json（前端契约 §5.4）+ frames/ + clips/
    """
    rdir = _review_dir(review_id)
    os.makedirs(rdir, exist_ok=True)
    result = {"id": review_id, "kind": "solo_review", "user_id": user_id,
              "mode": mode, "title": title, "status": "processing"}
    _write(review_id, result)
    try:
        # 1) 标准分段角度（A/C 读缓存免测；B 现拆标准）
        std_segs = _standard_segments(standard_ref)
        n_std = len(std_segs)

        # 无角度数据时降级为纯 vision 点评（诚实：不假装能对比）
        has_std_angles = any(
            seg.get("angles") and any(v is not None for v in seg["angles"].values())
            for seg in std_segs if seg.get("angles")
        )
        if not has_std_angles:
            _run_vision_only_review(review_id, my_video, title, result)
            return

        # 2) 我的视频：对齐标准段数抽中帧，姿态引擎逐段实测（帧落盘供对比/慢放）
        my_segs, my_bounds, _n = _measure_video_segments(
            my_video, tag="mine", n_hint=n_std, review_id=review_id, save_frames=True)

        # 3) 逐段逐关节做差
        cmp = compare_segments(std_segs, my_segs)

        # 4) 低置信度门：可测段比例过低 → 不出总分，改「建议重拍」（诚实红线 4）
        if cmp["measured_ratio"] < LOW_CONF_RATIO:
            result.update({
                "status": "low_confidence",
                "measured_ratio": cmp["measured_ratio"],
                "score": None,
                "score_note": "本次拍摄多数画面测不准（全身未入镜/光线不足/多人/遮挡），未出分。",
                "advice": "建议重拍：全身入镜、光线充足、单人、竖屏，舞镜 AI 才能逐帧测准。",
                "dims": [], "problems": [], "highlights": [],
            })
            _write(review_id, result)
            return

        # 5) 维度分（全实测，缺则 None 不编）
        dim = _dim_scores(cmp)

        # 6) AI 点评文案：复用 _vision_coach 铁律 prompt，喂入实测差值（禁空泛）。失败降级不阻断。
        coach = None
        try:
            # 取偏差最大的最多 5 段中帧喂给 vision，并把「实测差值」作为 measured 上下文
            worst = sorted([s for s in cmp["per_seg"] if s["measurable"]],
                           key=lambda s: (s["worst_delta"] or 0), reverse=True)[:5]
            fdir = os.path.join(rdir, "frames")
            frame_paths = [os.path.join(fdir, f"mine{s['i']}.jpg") for s in worst
                           if os.path.exists(os.path.join(fdir, f"mine{s['i']}.jpg"))]
            measured_ctx = []
            for s in worst:
                # 把「标准 vs 我的」差值组织成 _fmt_angles 能吃的角度字典（喂真数字进 prompt）
                mine_ang = {j: d["mine"] for j, d in s["joint_diffs"].items()}
                measured_ctx.append((s["i"], mine_ang))
            if frame_paths:
                coach = _vision_coach(frame_paths, title, measured_ctx)
        except Exception:
            coach = None

        # 7) 问题 Top5 / 亮点 Top2 / 四维 / 总分（全部实测可回溯）
        problems = _build_problems(cmp, coach)
        highlights = _build_highlights(cmp)
        dims = _build_dims(dim, coach)
        total = _weighted_total(dim)

        # 8) 我的段慢放切片 + 问题卡的 slowmo/frames URL 回填（-c copy 不重编码）
        cdir = os.path.join(rdir, "clips")
        os.makedirs(cdir, exist_ok=True)
        seg_bounds = {s["i"]: (s["t0"], s["t1"]) for s in my_segs}
        for p in problems:
            seg = p["seg"]
            t0, t1 = seg_bounds.get(seg, (None, None))
            if t0 is not None:
                out_clip = os.path.join(cdir, f"mine{seg}.mp4")
                if not os.path.exists(out_clip):
                    _clip(my_video, t0, t1, out_clip, slow=None)
            p["slowmo"] = f"api/solo/review/{review_id}/clip/{seg}"
            p["frames"] = f"api/solo/review/{review_id}/frame/{seg}"

        note = "综合可测维度加权（动作延展度/镜像一致性/节拍契合度中的可测项）"
        result.update({
            "status": "completed",
            "measured_ratio": cmp["measured_ratio"],
            "measurable_count": cmp["measurable_count"], "total_segments": cmp["total"],
            "score": total,
            "score_note": note if total is not None else "可测维度不足，未出总分",
            "dims": dims, "problems": problems, "highlights": highlights,
            "genre": (coach or {}).get("genre", STD_GENRE),
        })
        _write(review_id, result)
    except Exception:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()[-500:]
        _write(review_id, result)


def run_solo_review_from_disk(review_id):
    """付费回调零耦合入口：只给 review_id，从磁盘 review.json 恢复入参并跑。
    上传阶段（主控在 /api/solo/review 里）应把 my_video 存 data/<id>/input.mp4，
    并把 standard_ref/mode/title 写进 awaiting_payment 占位 review.json。"""
    meta = get_review(review_id) or {}
    my_video = os.path.join(_review_dir(review_id), "input.mp4")
    if not os.path.exists(my_video):
        m = dict(meta); m["status"] = "failed"; m["error"] = "源视频缺失，请重新上传"
        _write(review_id, m)
        return
    std_ref = meta.get("standard_ref")
    if not std_ref:
        m = dict(meta); m["status"] = "failed"; m["error"] = "缺少标准来源 standard_ref"
        _write(review_id, m)
        return
    run_solo_review(review_id, my_video, std_ref,
                    title=meta.get("title", "我的舞"),
                    mode=meta.get("mode", "reference"),
                    user_id=meta.get("user_id"))


# ------------------------------------------------------------------ APIRouter

# 延迟导入 FastAPI，方便纯逻辑单测时不依赖 web 栈。
try:
    from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Header
    from fastapi.responses import FileResponse
    import uuid
    import threading

    router = APIRouter(prefix="/api/solo", tags=["solo-review"])

    _SOLO_PRICE_CNY = float(os.environ.get("WJ_SOLO_PRICE_CNY",
                                           os.environ.get("WJ_DANCE_PRICE_CNY", "9.9")))

    def _safe_seg(name):
        s = "".join(ch for ch in str(name) if ch.isalnum() or ch == "_")
        return s

    @router.post("/review")
    async def create_solo_review(
        mode: str = Form("reference"),                 # reference | self | progress
        standard_id: str = Form(None),                 # A/C 入口：已拆标准的 decompose_id
        standard_video: UploadFile = File(None),       # B 入口：上传标准视频
        my_video: UploadFile = File(...),              # 必填：用户自己跳的
        title: str = Form("我的舞"),
        authorization: str = Header(None),
    ):
        """建 review_id → 存源视频 + awaiting_payment 占位（复用拆解付费墙模式）。
        付费回调后由主控调 run_solo_review_from_disk(review_id) 触发比对。
        本端点不碰 server.py/pay.py：只落地占位，返回 awaiting_payment。"""
        if mode not in ("reference", "self", "progress"):
            raise HTTPException(status_code=400, detail="mode 必须是 reference/self/progress")

        review_id = str(uuid.uuid4())
        rdir = _review_dir(review_id)
        os.makedirs(rdir, exist_ok=True)

        # 存「我的」视频（诚实前置约束提示由前端上传页给：全身/光线/单人/竖屏）
        my_path = os.path.join(rdir, "input.mp4")
        content = await my_video.read()
        if len(content) > 500 * 1024 * 1024:
            import shutil as _sh
            _sh.rmtree(rdir, ignore_errors=True)
            raise HTTPException(status_code=413, detail="视频过大，请压到 500MB 以内")
        with open(my_path, "wb") as f:
            f.write(content)

        # 解析标准来源
        std_ref = None
        if mode in ("reference", "progress"):
            # A/C 入口：优先用已拆标准；C（progress）也走 decompose_id（用上一次拆好的自己）
            if standard_id:
                std_ref = {"kind": "decompose_id", "id": standard_id}
            elif standard_video is not None:
                std_ref = None  # 下面按 B 入口处理
        if std_ref is None:
            if standard_video is not None:
                std_path = os.path.join(rdir, "standard.mp4")
                sc = await standard_video.read()
                if len(sc) > 500 * 1024 * 1024:
                    import shutil as _sh
                    _sh.rmtree(rdir, ignore_errors=True)
                    raise HTTPException(status_code=413, detail="标准视频过大，请压到 500MB 以内")
                with open(std_path, "wb") as f:
                    f.write(sc)
                std_ref = {"kind": "video", "path": std_path}
            elif standard_id:
                std_ref = {"kind": "decompose_id", "id": standard_id}
            else:
                import shutil as _sh
                _sh.rmtree(rdir, ignore_errors=True)
                raise HTTPException(status_code=400,
                                    detail="需提供 standard_id（选已拆的舞）或 standard_video（上传标准）")

        placeholder = {"id": review_id, "kind": "solo_review", "mode": mode,
                       "title": title, "standard_ref": std_ref,
                       "status": "awaiting_payment",
                       "message": "上传成功。付费后舞镜 AI 逐帧测量出点评报告。",
                       "price_cny": _SOLO_PRICE_CNY}
        _write(review_id, placeholder)
        return {"review_id": review_id, "dance_id": review_id,
                "status": "awaiting_payment", "price_cny": _SOLO_PRICE_CNY,
                "message": placeholder["message"]}

    @router.post("/review/{review_id}/run")
    async def run_solo_review_endpoint(review_id: str, authorization: str = Header(None),
                                       x_device_id: str = Header(None)):
        """兜底触发：已付费但报告未生成时手动重跑（幂等）。
        付费判定：按 (身份, dance_id==review_id) 查 pay.py orders 表 paid，防免费刷昂贵计算。"""
        # 复用 pay.py 的游客设备身份（登录→user_id，游客→guest:<device>）
        try:
            from pay import _user_id_optional as _pay_uid
        except Exception:
            _pay_uid = None
        identity = _pay_uid(authorization, x_device_id) if _pay_uid else "guest"
        if os.environ.get("WJ_FREE_MODE") != "1":
            try:
                from pay import get_db as _pay_db
                with _pay_db() as _c:
                    paid = _c.execute(
                        "SELECT 1 FROM orders WHERE dance_id=? AND user_id=? AND status='paid' LIMIT 1",
                        (review_id, identity)).fetchone()
            except Exception:
                paid = None
            if not paid:
                raise HTTPException(status_code=402, detail="尚未付费，请先付 9.9 解锁点评")
        rdir = _review_dir(review_id)
        if not os.path.exists(os.path.join(rdir, "input.mp4")):
            raise HTTPException(status_code=404, detail="源视频不存在，请重新上传")
        cur = get_review(review_id)
        if cur and cur.get("status") == "completed":
            return {"review_id": review_id, "status": "completed", "message": "已生成，无需重复。"}
        threading.Thread(target=run_solo_review_from_disk, args=(review_id,), daemon=True).start()
        return {"review_id": review_id, "status": "processing", "message": "点评已开始。"}

    @router.get("/review/{review_id}")
    def get_solo_review_endpoint(review_id: str):
        """拉报告 JSON（processing|completed|low_confidence|failed|awaiting_payment）。"""
        d = get_review(review_id)
        if not d:
            raise HTTPException(status_code=404, detail="Not found")
        return d

    @router.get("/review/{review_id}/clip/{seg}")
    def get_solo_clip(review_id: str, seg: str):
        """我的某段慢放切片（前端 playbackRate 0.25× 慢放；-c copy 不重编码）。"""
        s = _safe_seg(seg)
        path = os.path.join(_review_dir(review_id), "clips", f"mine{s}.mp4")
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Clip not found")
        return FileResponse(path, media_type="video/mp4")

    @router.get("/review/{review_id}/frame/{pair}")
    def get_solo_frame(review_id: str, pair: str):
        """对比帧：默认返回「我的」中帧 mine{seg}.jpg。
        （标准帧在 A/C 入口来自缓存拆解目录，前端可直接引 /api/decompose/{std}/frame/pN；
         B 入口标准帧存 std{seg}.jpg，本端点也放行。）"""
        s = _safe_seg(pair)
        fdir = os.path.join(_review_dir(review_id), "frames")
        for cand in (f"mine{s}.jpg", f"std{s}.jpg", f"{s}.jpg"):
            path = os.path.join(fdir, cand)
            if os.path.exists(path):
                return FileResponse(path, media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Frame not found")

except ImportError:
    router = None
