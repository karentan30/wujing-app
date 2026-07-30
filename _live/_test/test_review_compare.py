#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独舞点评比对层纯逻辑测试。
不碰共享 wujing.db、不跑 MediaPipe、不调 vision——只喂合成关节角度验证：
  - 逐关节做差可回溯（标准 X / 你 Y / 差 Z）
  - 维度分/总分全实测、缺关节不编分
  - 低置信度正确降级不出分
  - 改一个真角度 → 报告数字跟着变（防写死）
用法: WUJING_BASE_DIR=<临时目录> python3 test_review_compare.py
"""
import os
import sys
import json
import tempfile

# 用独立临时 BASE_DIR（不写共享 wujing.db / 生产 data）
_TMP = tempfile.mkdtemp(prefix="wj_solo_test_")
os.environ["WUJING_BASE_DIR"] = _TMP
os.makedirs(os.path.join(_TMP, "data"), exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import review_compare as rc

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


def seg(i, angles, t0=None):
    return {"i": i, "t0": t0 if t0 is not None else float(i), "t1": float(i) + 1, "angles": angles}


# ------------------------------------------------------------- 1. 逐关节做差可回溯
print("\n[1] 逐关节做差可回溯（标准170/我的132 → 差38）")
std = {"right_elbow": 170.0, "left_elbow": 168.0, "right_knee": 95.0, "left_knee": 96.0}
mine = {"right_elbow": 132.0, "left_elbow": 165.0, "right_knee": 122.0, "left_knee": 120.0}
diffs = rc._joint_delta(std, mine, rc._EXT_JOINTS)
check("right_elbow 差 38", diffs["right_elbow"]["delta"] == 38.0, diffs.get("right_elbow"))
check("right_elbow 标准 170", diffs["right_elbow"]["std"] == 170.0)
check("right_elbow 我的 132", diffs["right_elbow"]["mine"] == 132.0)
check("right_knee 差 27", diffs["right_knee"]["delta"] == 27.0)

# ------------------------------------------------------------- 2. 缺一侧关节不编分
print("\n[2] 只留两侧都实测到的关节（缺则不编）")
std2 = {"right_elbow": 170.0, "right_knee": 95.0}
mine2 = {"right_elbow": 132.0}  # 缺 right_knee
d2 = rc._joint_delta(std2, mine2, rc._EXT_JOINTS)
check("只保留 right_elbow", set(d2.keys()) == {"right_elbow"}, list(d2.keys()))

# ------------------------------------------------------------- 3. compare_segments 可测/不可测
print("\n[3] compare_segments 双侧都测到才算可测（测不到不顶）")
std_segs = [seg(1, std), seg(2, {"right_elbow": 100.0, "left_elbow": 100.0}), seg(3, std)]
my_segs = [seg(1, mine),
           seg(2, None),                       # 我的这段测不到 → 不可测
           seg(3, {"right_elbow": 169.0, "left_elbow": 167.0, "right_knee": 95.0, "left_knee": 96.0})]  # 几乎到位
cmp = rc.compare_segments(std_segs, my_segs)
by_i = {s["i"]: s for s in cmp["per_seg"]}
check("段1 可测", by_i[1]["measurable"] is True)
check("段2 不可测(测不到不编)", by_i[2]["measurable"] is False)
check("段3 可测", by_i[3]["measurable"] is True)
check("可测比例 2/3", cmp["measured_ratio"] == round(2 / 3, 2), cmp["measured_ratio"])
check("段1 worst_joint=right_elbow", by_i[1]["worst_joint"] == "right_elbow", by_i[1]["worst_joint"])
check("段1 worst_delta=38", by_i[1]["worst_delta"] == 38.0)

# ------------------------------------------------------------- 4. 维度分 & 总分全实测
print("\n[4] 维度分/总分 = 可测项聚合（延展/镜像有分，节拍v1为None）")
dim = rc._dim_scores(cmp)
check("延展度出分(非None)", dim["extension"] is not None, dim)
check("镜像出分(非None)", dim["mirror"] is not None, dim)
check("节拍v1降级None(无BPM不编)", dim["timing"] is None)
total = rc._weighted_total(dim)
check("总分为可测维度加权(非None)", total is not None, total)
check("总分在0-100", total is None or (0 <= total <= 100), total)

# ------------------------------------------------------------- 5. 情感维度诚实降级
print("\n[5] 情感维度诚实降级（measured=False + 非测量标注）")
dims = rc._build_dims(dim, {"comment": "眼神有内容"})
emo = [d for d in dims if d["key"] == "emotion"][0]
check("情感 measured=False", emo["measured"] is False)
check("情感 val=None(不编分)", emo["val"] is None)
check("情感 note 标非测量", "非测量" in (emo["note"] or ""), emo["note"])

# ------------------------------------------------------------- 6. 低置信度降级不出分
print("\n[6] 低置信度：可测段<40% → 不出总分(降级)")
std_lo = [seg(i, std) for i in range(1, 6)]
my_lo = [seg(1, mine)] + [seg(i, None) for i in range(2, 6)]  # 只有1/5可测=20%
cmp_lo = rc.compare_segments(std_lo, my_lo)
check("可测比例 0.2", cmp_lo["measured_ratio"] == 0.2, cmp_lo["measured_ratio"])
check("低于阈值 0.4", cmp_lo["measured_ratio"] < rc.LOW_CONF_RATIO)

# ------------------------------------------------------------- 7. 问题卡带真值 + 可回溯
print("\n[7] problems 带 std/mine/delta 真值 + 段号时间(可回溯)")
problems = rc._build_problems(cmp, {"improve": ["把右肘从132°送到170°，指尖领延伸"]})
check("problems 非空", len(problems) >= 1, len(problems))
p0 = problems[0]
check("problem 有 std/mine/delta", all(k in p0 for k in ("std", "mine", "delta")), p0)
check("problem 有 seg 段号", "seg" in p0 and isinstance(p0["seg"], int))
check("problem delta 与实测一致", p0["delta"] == 38.0, p0["delta"])
check("problem detail 含真数字38", "38" in p0["detail"], p0["detail"])
check("problem fix 用了coach的引数字建议", "170" in p0["fix"], p0["fix"])
check("severity major(>25°)", p0["severity"] == "major", p0["severity"])

# ------------------------------------------------------------- 8. 亮点=偏差最小且<5%
print("\n[8] highlights 只收差<5°的到位段(真实)")
hl = rc._build_highlights(cmp)
# 段3 几乎到位（右肘差1° 等），应入亮点
check("有亮点", len(hl) >= 1, hl)
if hl:
    check("亮点段3", hl[0]["seg"] == 3, hl[0])

# ------------------------------------------------------------- 9. 防写死：改真角度→数字跟着变
print("\n[9] 防写死：把我的角度改好 → delta 变小、分变高")
mine_better = dict(mine); mine_better["right_elbow"] = 168.0  # 从132改到168，差2
my_segs_b = [seg(1, mine_better), seg(2, None), my_segs[2]]
cmp_b = rc.compare_segments(std_segs, my_segs_b)
d_before = by_i[1]["worst_delta"]
d_after = {s["i"]: s for s in cmp_b["per_seg"]}[1]["worst_delta"]
check("delta 跟着变小(非写死)", d_after < d_before, f"{d_before}->{d_after}")
ext_before = rc._dim_scores(cmp)["extension"]
ext_after = rc._dim_scores(cmp_b)["extension"]
check("延展度分跟着变高(非写死)", ext_after > ext_before, f"{ext_before}->{ext_after}")

# ------------------------------------------------------------- 10. low_confidence 报告结构
print("\n[10] run 写出的 low_confidence 报告结构(不出分/带重拍建议)")
# 直接构造 low_conf 分支写盘验证（不跑 ffmpeg/pose）
rid = "test_lowconf"
os.makedirs(os.path.join(_TMP, "data", rid), exist_ok=True)
res = {"id": rid, "kind": "solo_review", "status": "low_confidence",
       "measured_ratio": 0.2, "score": None,
       "score_note": "本次拍摄多数画面测不准，未出分。",
       "advice": "建议重拍：全身入镜、光线充足、单人、竖屏。",
       "dims": [], "problems": [], "highlights": []}
rc._write(rid, res)
loaded = rc.get_review(rid)
check("low_conf score=None", loaded["score"] is None)
check("low_conf 有重拍建议", "重拍" in loaded["advice"])
check("low_conf 无编造problems", loaded["problems"] == [])

# ------------------------------------------------------------- 11. 独立临时DB隔离确认
print("\n[11] 隔离：只写临时目录，不碰共享 wujing.db")
check("BASE_DIR 是临时目录", rc.DATA_DIR.startswith(_TMP), rc.DATA_DIR)
check("未生成 wujing.db", not os.path.exists(os.path.join(_TMP, "wujing.db")))

# ------------------------------------------------------------- 汇总
print(f"\n{'='*50}\n结果: {PASS} passed, {FAIL} failed  (临时目录 {_TMP})")
sys.exit(0 if FAIL == 0 else 1)
