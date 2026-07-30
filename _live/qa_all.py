#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 全功能后端 QA。在服务器上跑：python3 qa_all.py"""
import json, time, urllib.request, urllib.error, uuid

BASE = "http://127.0.0.1:3006"
P = [0]; F = [0]
def ok(m): print("  ✅", m); P[0]+=1
def no(m): print("  ❌", m); F[0]+=1

def req(method, path, tok=None, jbody=None, files=None):
    url = BASE + path
    headers = {}
    data = None
    if tok: headers["Authorization"] = "Bearer " + tok
    if jbody is not None:
        data = json.dumps(jbody).encode(); headers["Content-Type"]="application/json"
    if files is not None:
        # multipart
        boundary = "----wj" + uuid.uuid4().hex
        body = b""
        for k, v in files["fields"].items():
            body += ("--"+boundary+"\r\n").encode()
            body += ('Content-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (k, v)).encode()
        fn = files["file"]
        with open(fn, "rb") as fp: fc = fp.read()
        body += ("--"+boundary+"\r\n").encode()
        body += ('Content-Disposition: form-data; name="video"; filename="v.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode()
        body += fc + b"\r\n" + ("--"+boundary+"--\r\n").encode()
        data = body; headers["Content-Type"]="multipart/form-data; boundary="+boundary
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=60)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def jget(b, k):
    try: return json.loads(b).get(k)
    except: return None

print("== 1. 健康 ==")
s,b = req("GET","/api/health")
ok("health") if s==200 and jget(b,"status")=="ok" else no("health %s"%s)

print("== 2. 注册/登录/me/鉴权 ==")
U = "qa_%s@t.com" % uuid.uuid4().hex[:10]
s,b = req("POST","/api/register_json",jbody={"email":U,"password":"test1234"})
TOK = jget(b,"token"); ok("注册拿token") if TOK else no("注册 %s"%s)
s,b = req("POST","/api/login_json",jbody={"email":U,"password":"test1234"})
ok("登录拿token") if jget(b,"token") else no("登录 %s"%s)
s,b = req("GET","/api/me",tok=TOK)
me_email = (json.loads(b).get("user") or {}).get("email") if s==200 else None
ok("me鉴权") if me_email==U else no("me %s email=%s"%(s,me_email))
s,b = req("GET","/api/me",tok="WRONG")
ok("错token被拒") if s in (401,403) else no("错token没拒 %s"%s)

print("== 3. 老师列表(真舞/genre) ==")
s,b = req("GET","/api/teachers")
ts = jget(b,"teachers") or []
ok("老师列表 %d 支"%len(ts)) if len(ts)>=10 else no("老师少 %d"%len(ts))
gs = set(t.get("genre") for t in ts)
ok("genre双类:%s"%gs) if {"kpop","guofeng"} <= gs else no("genre缺 %s"%gs)

print("== 4. 上传任意舞→自动拆解(核心) ==")
s,b = req("POST","/api/decompose",tok=TOK,files={"file":"/www/wujing/qingluu/reference.mp4","fields":{"title":"QA青绿","genre":"guofeng"}})
DID = jget(b,"decompose_id"); ok("decompose上传") if DID else no("上传 %s %s"%(s,b[:120]))
ST=None
for _ in range(50):
    time.sleep(3); s,b = req("GET","/api/decompose/%s"%DID,tok=TOK); ST=jget(b,"status")
    if ST in ("completed","failed"): break
ok("拆解完成") if ST=="completed" else no("拆解 %s"%ST)
d = json.loads(b)
ph = d.get("phrases",[])
checks = []
checks.append((len(ph)>=5,"段数>=5(%d)"%len(ph)))
checks.append((all(p.get("action") for p in ph),"每段有action"))
checks.append((bool(d.get("story",{}).get("title")),"故事卡"))
checks.append((bool(d.get("memory",{}).get("video")),"记忆卡"))
c=d.get("coach") or {}
checks.append((bool(c.get("comment") and c.get("improve")),"点评齐"))
ang=sum(1 for p in ph if p.get("angles"))
checks.append((ang>=1,"有角度段%d/%d"%(ang,len(ph))))
checks.append(("°" in " ".join(c.get("improve",[])),"点评引用角度°"))
checks.append((d.get("strip")==4,"胶片strip=4"))
for good,name in checks:
    ok("拆解·"+name) if good else no("拆解·"+name)
# 资源
for path,name in [("/frame/p1_0","胶片帧"),("/clip/p1","分段切片"),("/clip/full","整片")]:
    s,_ = req("GET","/api/decompose/%s%s"%(DID,path))
    ok(name) if s==200 else no(name+" %s"%s)
# 越权
s,b = req("POST","/api/register_json",jbody={"email":"qax_%s@t.com"%uuid.uuid4().hex[:8],"password":"test1234"})
TOKX=jget(b,"token")
s,_ = req("GET","/api/decompose/%s"%DID,tok=TOKX)
ok("越权被拒") if s==403 else no("越权没拒 %s"%s)

print("== 5. 对着老师打分(compare) ==")
# 用独立新用户(decompose已耗掉TOK的免费额度·避免402误判)
s,b = req("POST","/api/register_json",jbody={"email":"qac_%s@t.com"%uuid.uuid4().hex[:8],"password":"test1234"})
TOKC=jget(b,"token")
s,b = req("POST","/api/upload",tok=TOKC,files={"file":"/www/wujing/babymonster/reference.mp4","fields":{"teacher_key":"babymonster"}})
RID=jget(b,"review_id"); ok("compare上传") if RID else no("上传 %s %s"%(s,b[:100]))
RST=None
if RID:
    for _ in range(40):
        time.sleep(3); s,b=req("GET","/api/review/%s"%RID,tok=TOKC); RST=jget(b,"status")
        if RST in ("completed","failed"): break
    ok("打分完成") if RST=="completed" else no("打分 %s"%RST)
    rd=json.loads(b)
    ok("打分产物(score/dims/problems)") if (rd.get("score") is not None and rd.get("dims") and rd.get("problems")) else no("打分产物缺")
else:
    no("打分完成(上传失败跳过)"); no("打分产物(上传失败跳过)")

print("== 6. 练习计划 ==")
if RID:
    s,b=req("GET","/api/plan/%s"%RID,tok=TOKC)
    ok("练习计划") if (jget(b,"plan")) else no("练习计划 %s"%s)
else:
    no("练习计划(上传失败跳过)")

print("== 7. stats/reviews ==")
s,_=req("GET","/api/stats",tok=TOKC); ok("stats") if s==200 else no("stats %s"%s)
s,b=req("GET","/api/reviews",tok=TOKC)
ok("reviews历史") if (RID and RID in b.decode("utf-8","ignore")) else no("reviews历史")

print("== 8. 防刷:未登录不能传 ==")
s,_=req("POST","/api/decompose",files={"file":"/www/wujing/qingluu/reference.mp4","fields":{"title":"x"}})
ok("未登录被拒") if s in (401,403) else no("未登录能传! %s"%s)

print("\n==== 通过 %d · 失败 %d ====" % (P[0],F[0]))
