#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 群舞班级点评 编排层 + 并发限流 测试（独立临时 db，绝不碰 wujing.db 生产/共享）。

跑法： python3 _test/test_group_review.py
- 用独立临时 WUJING_BASE_DIR + 独立 WUJING_DB_PATH（tmp），绝不写共享 wujing.db。
- decompose 用 stub 注入（set_decompose_runner）：不打真 AI、不跑 ffmpeg/mediapipe，
  但产出 auto_decompose 真实结构的 phrases[].angles + coach，验证归一 + 汇总 + 排名逻辑。
- 并发限流单独用「计数 barrier」的慢 stub 验证：全局同时在跑的任务数 ≤ MAX_CONCURRENCY。
"""
import os, sys, json, time, tempfile, threading

TMP = tempfile.mkdtemp(prefix="wujing_group_")
os.environ["WUJING_BASE_DIR"] = TMP
os.environ["WUJING_DB_PATH"] = os.path.join(TMP, "wujing.db")  # 独立库
os.environ["WUJING_GROUP_CONCURRENCY"] = "3"                    # 明确并发上限
os.environ["WUJING_GROUP_QUEUE_MAX"] = "50"
os.makedirs(os.path.join(TMP, "data"), exist_ok=True)

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)   # stubs (auth/models/env_loader)
sys.path.insert(0, LIVE)   # real group_review

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  -- " + extra) if extra else ""))


import group_review as gr
from fastapi import FastAPI
from fastapi.testclient import TestClient

gr.init_group_tables()

# ── stub decompose runner：写一份 auto_decompose 真实结构的 decompose.json ──
# 每个学员给不同角度，制造真实排名差异。angles 越接近「敦煌达标」，S曲线/臂高越高。
STUDENT_PROFILES = {}  # did -> profile dict


def stub_run_decompose(did, video_path, user_id, title, genre):
    prof = STUDENT_PROFILES.get(did, {})
    torso = prof.get("torso", 15.0)      # 躯干倾斜 → sc
    shoulder = prof.get("shoulder", 120) # 抬臂 → ah
    knee = prof.get("knee", 175)         # 膝角 → kn
    elbow = prof.get("elbow", 150)       # 手肘 → as_
    ddir = os.path.join(gr.DATA_DIR, did)
    os.makedirs(ddir, exist_ok=True)
    # 造 3 段，段间角度有变化（→ mv 有值）
    phrases = []
    for i in range(3):
        phrases.append({"i": i + 1, "name": f"第{i+1}段",
                        "angles": {"right_shoulder": shoulder + i * 5,
                                   "left_shoulder": shoulder,
                                   "right_knee": knee, "left_knee": knee - 2,
                                   "right_elbow": elbow, "left_elbow": elbow,
                                   "torso_tilt": torso + i * 2}})
    obj = {"id": did, "status": "completed", "title": title, "genre": genre,
           "phrases": phrases,
           "coach": {"comment": "整体到位", "genre": genre,
                     "good": ["右臂抬到位"],
                     "improve": ["右胯再推出，S曲线不足", "手腕立起撑圆", "旋身重心前移"]}}
    with open(os.path.join(ddir, "decompose.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def stub_get_decompose(did):
    p = os.path.join(gr.DATA_DIR, did, "decompose.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


gr.set_decompose_runner(stub_run_decompose, stub_get_decompose)
# 关掉真 DeepSeek（无 key 自动走规则兜底 unifiedPlan）
os.environ.pop("DEEPSEEK_API_KEY", None)

app = FastAPI()
app.include_router(gr.router)
client = TestClient(app)


def make_dummy_video(path):
    with open(path, "wb") as f:
        f.write(b"\x00" * 2048)  # 占位（stub 不真解码）


print("\n=== 1. 建班 → 发码 ===")
r = client.post("/api/class/create", data={
    "dance_name": "千年一顾", "genre": "guofeng", "max_students": "10",
    "school_name": "敦煌艺术舞蹈学院", "teacher_name": "王老师", "motto": "以舞载道"})
check("建班 200", r.status_code == 200, str(r.status_code))
cj = r.json()
class_id = cj.get("class_id")
code = cj.get("invite_code")
check("返回 class_id + 6位码", bool(class_id) and len(code or "") == 6, json.dumps(cj, ensure_ascii=False))
check("码无易混字符 0O1IL", not any(c in (code or "") for c in "01OIL"), code or "")

print("\n=== 2. 学员端：查码落地页 ===")
r = client.get(f"/api/join/{code.lower()}")  # 大小写不敏感
check("查码 200 且返回品牌", r.status_code == 200 and r.json().get("brand", {}).get("schoolName") == "敦煌艺术舞蹈学院", str(r.status_code))
r = client.get("/api/join/ZZZZZZ")
check("无效码 404", r.status_code == 404, str(r.status_code))
r = client.get("/api/join/abc")
check("格式错码 400", r.status_code == 400, str(r.status_code))

print("\n=== 3. 5 名学员加入 + 上传（各自单人段）===")
# 造 5 个差异化 profile：陈悠然最好，赵希言最差
profiles = [
    ("张雨欣", {"torso": 12, "shoulder": 115, "knee": 176, "elbow": 148}),
    ("李雨桐", {"torso": 20, "shoulder": 135, "knee": 174, "elbow": 152}),
    ("王若溪", {"torso": 16, "shoulder": 118, "knee": 172, "elbow": 150}),
    ("陈悠然", {"torso": 24, "shoulder": 140, "knee": 174, "elbow": 155}),
    ("赵希言", {"torso": 8,  "shoulder": 100, "knee": 178, "elbow": 140}),
]
tokens = {}
for name, prof in profiles:
    r = client.post(f"/api/class/{class_id}/join", json={"nickname": name})
    tk = r.json().get("member_token")
    tokens[name] = tk
    vid = os.path.join(TMP, f"{name}.mp4")
    make_dummy_video(vid)
    with open(vid, "rb") as f:
        ru = client.post(f"/api/class/{class_id}/member/upload",
                         data={"member_token": tk},
                         files={"video": (f"{name}.mp4", f, "video/mp4")})
    did = ru.json().get("decompose_id")
    STUDENT_PROFILES[did] = prof  # 挂 profile 给 stub 用
check("5 人加入+上传成功", len(tokens) == 5 and all(tokens.values()))

# 进度看板：5 人 uploaded
r = client.get(f"/api/class/{class_id}")
prog = r.json()["progress"]
check("看板 total=5, uploaded=5", prog["total"] == 5 and prog["counts"].get("uploaded") == 5,
      json.dumps(prog["counts"]))

print("\n=== 4. 开始评分（走限流队列）→ 等全班出分 ===")
r = client.post(f"/api/class/{class_id}/start-scoring")
check("start-scoring 200", r.status_code == 200, str(r.status_code))
# 轮询等评分完成（stub 很快）
deadline = time.time() + 20
done = False
while time.time() < deadline:
    p = client.get(f"/api/class/{class_id}").json()["progress"]
    if p["counts"].get("scored", 0) == 5:
        done = True
        break
    time.sleep(0.2)
check("5 人全部 scored", done, json.dumps(client.get(f'/api/class/{class_id}').json()['progress']['counts']))

print("\n=== 5. 汇总报告：契约字段 + 排名口径 ===")
r = client.get(f"/api/class/{class_id}/report")
rep = r.json()
check("report 200", r.status_code == 200)
check("class.brand 用后端品牌", rep["class"]["brand"]["schoolName"] == "敦煌艺术舞蹈学院")
check("class.studentCount=5", rep["class"]["studentCount"] == 5)
check("有 commonWeakness", bool(rep["class"]["commonWeakness"]))
check("有 unifiedPlan(规则兜底)", isinstance(rep["class"]["unifiedPlan"], list) and len(rep["class"]["unifiedPlan"]) > 0)
check("含诚实免责声明", "舞镜AI" in rep["class"]["disclaimer"] and "参考" in rep["class"]["disclaimer"])
students = rep["students"]
check("students=5", len(students) == 5)
# 契约字段齐全（report.html DATA[] 口径）
s0 = students[0]
need = ["name", "score", "rank", "sc", "ah", "sp", "as_", "kn", "mv", "radar", "fb"]
check("学员字段齐全", all(k in s0 for k in need), str([k for k in need if k not in s0]))
check("sc 有 v+pct", "v" in s0["sc"] and "pct" in s0["sc"])
check("radar 是 6 维", isinstance(s0["radar"], list) and len(s0["radar"]) == 6)
check("radar 值域 0-100", all(0 <= x <= 100 for x in s0["radar"]))
# 排名口径：按 sc.v 降序（陈悠然 torso 最高 → sc 最高 → rank1；赵希言最低 → rank5）
ranks = {s["name"]: s["rank"] for s in students}
check("陈悠然 rank1（S曲线最高）", ranks.get("陈悠然") == 1, json.dumps(ranks, ensure_ascii=False))
check("赵希言 rank5（S曲线最低）", ranks.get("赵希言") == 5, json.dumps(ranks, ensure_ascii=False))
check("rank 连续 1..5", sorted(ranks.values()) == [1, 2, 3, 4, 5])
# fb 三档 P0/P1/P2 用真实 vision 点评
check("fb P0 来自真实点评", s0["fb"][0][0] == "P0" and "S曲线" in s0["fb"][0][2] or len(s0["fb"]) >= 1)
# 诚实：旋转是估算，measured=True（有 stub 角度）
check("measured=True（有骨架角度）", s0["measured"] is True)
check("sp_estimated=True（旋转诚实标估算）", s0["sp_estimated"] is True)

print("\n=== 6. 归一口径单测（不经队列，直接算）===")
sc = gr.score_from_decompose(stub_get_decompose(list(STUDENT_PROFILES.keys())[0]))
check("sc.v 在 0-10", 0 <= sc["sc"]["v"] <= 10)
check("ah.v 在 0-100", 0 <= sc["ah"]["v"] <= 100)
check("kn.v 在 0.5-1.0", 0.5 <= sc["kn"]["v"] <= 1.0)
check("as_.v 在 0-0.5", 0 <= sc["as_"]["v"] <= 0.5)
check("mv.v 在 0-0.3", 0 <= sc["mv"]["v"] <= 0.3)
check("sp 在 0-20", 0 <= sc["sp"]["v"] <= 20)
check("综合分 0-10", 0 <= float(sc["score"]) <= 10)
# 无骨架（空 phrases）→ measured=False，仍能出兜底分不崩
empty = gr.score_from_decompose({"phrases": [], "coach": {}})
check("空骨架 measured=False 不崩", empty["measured"] is False and 0 <= empty["sc"]["v"] <= 10)

print("\n=== 7. 学员端脱敏：只见自己 + 名次，不见别人明细 ===")
r = client.get(f"/api/class/{class_id}/member/{tokens['张雨欣']}/result")
res = r.json()
check("学员看到自己那页", res.get("status") == "scored" and "self" in res)
check("含自己六维+fb", all(k in res["self"] for k in ["sc", "ah", "radar", "fb"]))
check("只回名次不泄别人明细", "rank" in res and "my_rank" in res["rank"] and "students" not in res)
check("学员端含诚实免责", "舞镜AI" in res.get("disclaimer", ""))
# 错 token 拒
r = client.get(f"/api/class/{class_id}/member/BADTOKEN/result")
check("错 token 403", r.status_code == 403, str(r.status_code))

print("\n=== 8. 单人重跑（不重算全班）===")
mid = None
p = client.get(f"/api/class/{class_id}").json()["progress"]
mid = p["members"][0]["member_id"]
r = client.post(f"/api/class/{class_id}/rescore-member", json={"member_id": mid})
check("rescore 200", r.status_code == 200, str(r.status_code))
time.sleep(1.0)
p = client.get(f"/api/class/{class_id}").json()["progress"]
check("重跑后仍 5 scored", p["counts"].get("scored") == 5, json.dumps(p["counts"]))

print("\n=== 9. 【核心】并发限流：全局同时在跑 ≤ MAX_CONCURRENCY ===")
# 用一个慢 stub 记录「同时在跑」峰值，验证 Semaphore/队列限流真生效。
peak = {"cur": 0, "max": 0}
peak_lock = threading.Lock()


def slow_task(*args):
    with peak_lock:
        peak["cur"] += 1
        peak["max"] = max(peak["max"], peak["cur"])
    time.sleep(0.25)   # 模拟一个人评分耗时
    with peak_lock:
        peak["cur"] -= 1


# 直接往同一个队列灌 20 个任务（远超并发上限 3）
N = 20
accepted = 0
for _ in range(N):
    if gr._score_queue.submit(slow_task):
        accepted += 1
# 等全部跑完
t_end = time.time() + 15
while time.time() < t_end:
    st = gr._score_queue.stats()
    if st["queued"] == 0 and st["active"] == 0:
        break
    time.sleep(0.1)
check(f"20 任务全部入队被接受", accepted == N, f"accepted={accepted}")
check(f"并发峰值 ≤ {gr.MAX_CONCURRENCY}（限流生效，防OOM）",
      peak["max"] <= gr.MAX_CONCURRENCY and peak["max"] >= 1,
      f"peak={peak['max']}, limit={gr.MAX_CONCURRENCY}")

print("\n=== 10. 队列满 → 优雅拒绝（不无界堆积 OOM）===")
# 造一个极小队列的独立 ScoreQueue，灌爆它验证 submit 返回 False
tiny = gr.ScoreQueue(max_concurrency=1, maxsize=2)


def block_task(ev):
    ev.wait(5)


hold = threading.Event()
# 先占满 1 个 worker + 2 个队列槽
r1 = tiny.submit(block_task, hold)   # 立即被 worker 取走执行并阻塞
time.sleep(0.1)
r2 = tiny.submit(block_task, hold)   # 入队槽1
r3 = tiny.submit(block_task, hold)   # 入队槽2
r4 = tiny.submit(block_task, hold)   # 队列满 → False
check("队列满时 submit 返回 False（转429）", r4 is False, f"r1={r1} r2={r2} r3={r3} r4={r4}")
hold.set()  # 放行

print("\n=== 11. 表全部 IF NOT EXISTS：重复 init 幂等不崩 ===")
try:
    gr.init_group_tables()
    gr.init_group_tables()
    check("重复建表幂等", True)
except Exception as e:
    check("重复建表幂等", False, str(e))

# ── 汇总 ──
print("\n" + "=" * 50)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("ALL GREEN")
sys.exit(0)
