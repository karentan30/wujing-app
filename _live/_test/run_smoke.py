#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜后端「上传→付9.9→拆解出卡」全链路本地冒烟/沙箱测（不花真钱，不碰生产）。

跑法： python3 _test/run_smoke.py
- 用临时 WUJING_BASE_DIR（tmp），独立 wujing.db，绝不碰 /www/wujing-api。
- 把 _test/ 放 sys.path 最前，用 stub 顶替生产的 env_loader/models/auth/analyze（生产已有真版）。
- Stripe「测试模式」用我们自己控制的 STRIPE_WEBHOOK_SECRET 造合法签名 webhook，等价 Stripe CLI resend。
- run_decompose 的 vision/deepseek 调用被 monkeypatch（无 API key 也能产出真实结构的 decompose.json）。
"""
import os, sys, json, time, tempfile, subprocess, hmac, hashlib

TMP = tempfile.mkdtemp(prefix="wujing_smoke_")
os.environ["WUJING_BASE_DIR"] = TMP
os.environ["WUJING_DB_PATH"] = os.path.join(TMP, "wujing.db")
# 清掉任何真支付 key，先跑无 key 冒烟
for k in ("WECHAT_APP_ID", "WECHAT_MCH_ID", "WECHAT_API_KEY",
          "ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY_PATH", "ALIPAY_PUBLIC_KEY_PATH",
          "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
    os.environ.pop(k, None)

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)   # stubs first
sys.path.insert(0, LIVE)   # then real _live modules (server/pay/auto_decompose)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  -- " + extra) if extra else ""))


# ---- monkeypatch auto_decompose 的外部 AI 调用（无 key 也能出真结构） ----
import auto_decompose as ad
ad._vision_describe = lambda fp, i, t0, t1: {
    "i": i, "t0": round(t0, 2), "t1": round(t1, 2), "name": f"第{i}段",
    "full": "抬手起势", "action": "右手抬起", "feet": "重心居中",
    "intent": "起", "kou": "举—望"}
ad._vision_coach = lambda frames, title, measured=None: {
    "comment": "整体到位", "good": ["右臂抬到位"], "improve": ["旋身重心前移"], "genre": "guofeng"}
ad._deepseek_story = lambda title, phrases: {
    "title": title, "body": "一支好舞", "chain": "起—承—转—合"}
ad._run_pose = lambda frames: {}   # 跳过 mediapipe 子进程


from fastapi.testclient import TestClient
import server
client = TestClient(server.app)


def make_video(path):
    # 生成 ~6s 测试视频（testsrc），够 auto_decompose 分 5+ 段
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
                        "-t", "6", "-pix_fmt", "yuv420p", path],
                       capture_output=True, text=True)
    return os.path.exists(path) and os.path.getsize(path) > 1000


print("\n=== 0. 健康检查 + 挂载不崩 ===")
r = client.get("/api/health")
check("health ok", r.status_code == 200 and r.json().get("status") == "ok", str(r.status_code))

print("\n=== 1. 无 key 冒烟：三渠道 create 优雅 503，不崩 ===")
# 先建一支游客上传的舞拿 dance_id（上传免费无需登录）
vid = os.path.join(TMP, "in.mp4")
assert make_video(vid), "ffmpeg 生成测试视频失败"
with open(vid, "rb") as f:
    r = client.post("/api/decompose", files={"video": ("in.mp4", f, "video/mp4")},
                    data={"title": "测试舞", "genre": "guofeng"})
check("游客上传 decompose 200（免费·无需登录）", r.status_code == 200, str(r.status_code))
did = r.json().get("dance_id")
check("返回 awaiting_payment + dance_id",
      r.json().get("status") == "awaiting_payment" and bool(did), json.dumps(r.json(), ensure_ascii=False))

for ch in ("wechat", "alipay", "stripe"):
    r = client.post(f"/api/pay/{ch}/create", json={"dance_id": did})
    check(f"{ch}/create 无 key → 503", r.status_code == 503, str(r.status_code))

# 拆解门：未付费不出卡
r = client.get(f"/api/decompose/{did}")
check("未付费 GET decompose = awaiting_payment",
      r.status_code == 200 and r.json().get("status") == "awaiting_payment", str(r.status_code))
r = client.post(f"/api/decompose/{did}/run")
check("未付费 run = 402 拦截", r.status_code == 402, str(r.status_code))
r = client.get(f"/api/pay/dance/{did}/unlocked")
check("未付费 unlocked=false", r.status_code == 200 and r.json().get("unlocked") is False, str(r.json()))

print("\n=== 2. Stripe 测试模式全链路（造合法签名 webhook，等价 Stripe CLI）===")
# 开 Stripe：给 secret + webhook secret（测试值），重载 pay 模块级常量
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy_for_smoke"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_smoke_test_secret"
import pay
pay.STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
pay.STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

# create 会真打 Stripe API（sk_test dummy 会 401）→ 我们不依赖真 create，
# 直接手动插一条 pending 订单模拟 create 落库，再发 webhook 履约（这才是要验的核心链路）。
oid = pay._new_oid("WJST")
price_usd = float(os.environ.get("WJ_DANCE_PRICE_USD", "1.99"))
con = pay.get_db()
con.execute("INSERT INTO orders(out_trade_no,user_id,dance_id,amount,status,channel,currency,breakdown_status,created_at)"
            " VALUES(?,?,?,?, 'pending','stripe','USD','',?)",
            (oid, "guest", did, ("%.2f" % price_usd), pay._now_iso()))
con.commit(); con.close()
check("模拟 create：pending 订单落库", True)


def stripe_webhook_post(oid_in, amount_usd, sign=True, evt_id="evt_smoke_1"):
    body = json.dumps({
        "id": evt_id, "type": "checkout.session.completed",
        "data": {"object": {
            "payment_status": "paid",
            "amount_total": int(round(amount_usd * 100)),
            "payment_intent": "pi_smoke_123",
            "client_reference_id": oid_in,
            "metadata": {"out_trade_no": oid_in, "dance_id": did, "user_id": "guest"}}}
    }).encode()
    ts = str(int(time.time()))
    if sign:
        signed = ts.encode() + b"." + body
        v1 = hmac.new(os.environ["STRIPE_WEBHOOK_SECRET"].encode(), signed, hashlib.sha256).hexdigest()
        hdr = f"t={ts},v1={v1}"
    else:
        hdr = f"t={ts},v1=deadbeef"
    return client.post("/api/pay/stripe/webhook", content=body,
                       headers={"Stripe-Signature": hdr, "Content-Type": "application/json"})


# 2a. 假签名 → 400
r = stripe_webhook_post(oid, price_usd, sign=False)
check("假签名 webhook → 400", r.status_code == 400, str(r.status_code))

# 2b. 金额篡改（合法签名但金额不符）→ 拒履约，订单仍 pending
r = stripe_webhook_post(oid, price_usd + 5.0, sign=True, evt_id="evt_tamper")
con = pay.get_db(); st = con.execute("SELECT status FROM orders WHERE out_trade_no=?", (oid,)).fetchone()["status"]; con.close()
check("金额篡改 webhook → 订单仍 pending（不吞错单）", st == "pending", f"result={r.json()} status={st}")

# 2c. 正常签名+正确金额 → 履约触发 run_decompose
r = stripe_webhook_post(oid, price_usd, sign=True, evt_id="evt_ok")
check("合法 webhook → received", r.status_code == 200 and r.json().get("received"), str(r.json()))
con = pay.get_db(); row = con.execute("SELECT status,breakdown_status FROM orders WHERE out_trade_no=?", (oid,)).fetchone(); con.close()
check("订单翻 paid", row["status"] == "paid", str(dict(row)))

# 等履约后台线程产出 decompose.json（含真 ffmpeg 切片）
deadline = time.time() + 90
final = None
while time.time() < deadline:
    d = ad.get_decompose(did)
    if d and d.get("status") in ("completed", "failed"):
        final = d
        break
    time.sleep(1)
check("履约触发拆解并落地 decompose.json", final is not None, "")
if final:
    check("拆解 status=completed", final.get("status") == "completed", final.get("status"))
    check("拆解产出 phrases(八拍卡)", len(final.get("phrases", [])) >= 5, str(len(final.get("phrases", []))))
    check("拆解产出 story(故事卡)", bool(final.get("story", {}).get("title")), "")
    check("拆解产出 memory(记忆卡)", bool(final.get("memory")), "")
    p1 = os.path.join(TMP, "data", did, "clips", "p1.mp4")
    check("切片 p1.mp4 生成（慢放/镜像卡源）", os.path.exists(p1), p1)

# 2d. 付费后闸门放行
r = client.get(f"/api/decompose/{did}")
check("付费后 GET decompose = completed 出卡", r.status_code == 200 and r.json().get("status") == "completed", str(r.status_code))
r = client.get(f"/api/pay/dance/{did}/unlocked")
check("付费后 unlocked=true", r.json().get("unlocked") is True, str(r.json()))

print("\n=== 3. 幂等：重发同一 webhook 不重复履约 ===")
con = pay.get_db()
before = con.execute("SELECT COUNT(*) c FROM orders WHERE dance_id=? AND status='paid'", (did,)).fetchone()["c"]
con.close()
mtime_before = os.path.getmtime(os.path.join(TMP, "data", did, "decompose.json"))
r = stripe_webhook_post(oid, price_usd, sign=True, evt_id="evt_ok")   # 重发
check("重发 webhook → already（幂等命中）",
      r.status_code == 200 and r.json().get("result") == "already", str(r.json()))
con = pay.get_db()
after = con.execute("SELECT COUNT(*) c FROM orders WHERE dance_id=? AND status='paid'", (did,)).fetchone()["c"]
con.close()
check("重发不新增 paid 订单", before == after, f"{before}->{after}")
# 幂等：不应重新触发拆解（decompose.json 不被重写）
time.sleep(2)
mtime_after = os.path.getmtime(os.path.join(TMP, "data", did, "decompose.json"))
check("重发不重复生成拆解（decompose.json 未被重写）", mtime_before == mtime_after,
      f"{mtime_before} vs {mtime_after}")

print("\n=== 4. 源视频缺失兜底：付款但无源视频 → breakdown failed，不吞款语义 ===")
did2 = "no-source-dance-" + os.urandom(3).hex()
oid2 = pay._new_oid("WJST")
con = pay.get_db()
con.execute("INSERT INTO orders(out_trade_no,user_id,dance_id,amount,status,channel,currency,breakdown_status,created_at)"
            " VALUES(?,?,?,?, 'pending','stripe','USD','',?)",
            (oid2, "guest", did2, ("%.2f" % price_usd), pay._now_iso()))
con.commit(); con.close()
r = client.post("/api/pay/stripe/webhook", content=json.dumps({
    "id": "evt_nosrc", "type": "checkout.session.completed",
    "data": {"object": {"payment_status": "paid", "amount_total": int(round(price_usd*100)),
                        "payment_intent": "pi_x", "client_reference_id": oid2,
                        "metadata": {"out_trade_no": oid2, "dance_id": did2, "user_id": "guest"}}}
}).encode(), headers=(lambda: (lambda ts, body: {
    "Stripe-Signature": f"t={ts},v1=" + hmac.new(os.environ['STRIPE_WEBHOOK_SECRET'].encode(), (ts+'.').encode()+body, hashlib.sha256).hexdigest(),
    "Content-Type": "application/json"})(str(int(time.time())), json.dumps({
    "id": "evt_nosrc", "type": "checkout.session.completed",
    "data": {"object": {"payment_status": "paid", "amount_total": int(round(price_usd*100)),
                        "payment_intent": "pi_x", "client_reference_id": oid2,
                        "metadata": {"out_trade_no": oid2, "dance_id": did2, "user_id": "guest"}}}
}).encode()))())
# 等 breakdown_status 落 failed
deadline = time.time() + 20; bd = None
while time.time() < deadline:
    con = pay.get_db(); bd = con.execute("SELECT breakdown_status FROM orders WHERE out_trade_no=?", (oid2,)).fetchone()["breakdown_status"]; con.close()
    if bd in ("failed", "completed"):
        break
    time.sleep(1)
check("无源视频付款 → breakdown_status=failed（不吞款·可重试）", bd == "failed", str(bd))

print("\n=== 5. /api/pay/status 前端轮询 ===")
r = client.get(f"/api/pay/status?out_trade_no={oid}")
check("status 查已付订单 → paid", r.status_code == 200 and r.json().get("status") == "paid", str(r.json()))

print("\n" + "=" * 50)
print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("FAILED:", FAIL)
print("TMP:", TMP)
sys.exit(1 if FAIL else 0)
