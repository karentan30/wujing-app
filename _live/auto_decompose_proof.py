#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 任意舞自动拆解（证明版）
上传任意舞蹈视频 → 自动测BPM+按八拍切段 → vision看每段自动描述动作 → 出八拍卡+故事卡。
无需人肉起名、无需预制breakdown。复用 拆舞.py 的切段 + vision_score 的豆包调用 + cards 的DeepSeek。
用法: python3 auto_decompose_proof.py <视频> --title "洛神赋" --out out_luoshen
"""
import argparse, base64, json, math, os, subprocess, tempfile, urllib.request, concurrent.futures as cf

ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
EP = os.environ.get("ARK_VISION_EP", "ep-20260729155405-5l7dj")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

def run(cmd): return subprocess.run(cmd, capture_output=True, text=True)

def ffprobe_dur(p):
    r = run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", p])
    return float(r.stdout.strip())

def detect_bpm(audio):
    import librosa, numpy as np
    y, sr = librosa.load(audio, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    while bpm < 90:  bpm *= 2
    while bpm > 190: bpm /= 2
    return round(bpm, 1)

def grab_frame(src, t, out):
    run(["ffmpeg","-y","-ss",f"{t}","-i",src,"-frames:v","1","-q:v","3","-vf","scale=360:-1", out])

def _b64(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

def vision_describe(frame_path, idx, t0, t1):
    """豆包 vision 看一帧，自动描述这段舞在跳什么。关思考+压图=便宜。"""
    key = os.environ["ARK_API_KEY"]
    prompt = (
        f"这是一支舞蹈第{idx}段(约{t0:.1f}-{t1:.1f}秒)的定格画面。你是资深舞蹈老师，"
        "用中文描述这个动作，帮学员跟着练。只输出JSON不要解释：\n"
        '{"name":"2-3字段名如 起势/开手/旋身/亮相","action":"一句话身体和手臂动作要点",'
        '"feet":"脚下和重心一句话","intent":"这段的意境或情绪一句话","kou":"3-4字记忆口诀如 举—望—转"}'
    )
    body = {"model": EP, "thinking": {"type": "disabled"}, "max_output_tokens": 260,
            "input": [{"role":"user","content":[
                {"type":"input_image","image_url":_b64(frame_path)},
                {"type":"input_text","text":prompt}]}]}
    req = urllib.request.Request(ARK_URL, data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = "".join(c.get("text","") for o in r.get("output",[]) if o.get("type")=="message"
                  for c in o.get("content",[])).strip()
    if out.startswith("```"):
        out = out.split("```")[1]
        if out.lstrip().lower().startswith("json"): out = out.lstrip()[4:]
    d = json.loads(out.strip())
    return {"i":idx,"t0":round(t0,2),"t1":round(t1,2),
            "name":d.get("name",""),"full":d.get("action","")[:14],
            "action":d.get("action",""),"feet":d.get("feet",""),
            "intent":d.get("intent",""),"kou":d.get("kou","")}

def deepseek_story(title, phrases):
    key = os.environ["DEEPSEEK_API_KEY"]
    ctx = "\n".join(f"{p['i']}.{p['name']}｜{p['action']}｜意境:{p['intent']}" for p in phrases)
    prompt = (f"你是资深舞蹈老师。下面是《{title}》按八拍自动拆的分段：\n{ctx}\n\n"
              "请生成一张故事卡帮舞者跳出感觉。只输出严格JSON不要markdown：\n"
              '{"title":"故事标题","body":"120字以内情感叙事，讲这支舞的意境和该跳出的眼神状态","chain":"把整支舞串成一句好记的联想口诀"}')
    body = json.dumps({"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],
                       "max_tokens":800,"temperature":0.7}).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body,
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=90).read())["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"): raw = raw.lstrip()[4:]
    return json.loads(raw.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--beats", type=int, default=8)
    ap.add_argument("--bpm", type=float, default=None)
    args = ap.parse_args()
    os.makedirs(os.path.join(args.out,"frames"), exist_ok=True)

    dur = ffprobe_dur(args.video)
    if args.bpm: bpm = args.bpm
    else:
        aud = os.path.join(tempfile.gettempdir(), "_wj_a.wav")
        run(["ffmpeg","-y","-i",args.video,"-vn","-ac","1",aud]); bpm = detect_bpm(aud)
    phrase_len = args.beats * 60.0 / bpm
    n = max(1, min(12, math.ceil(dur / phrase_len)))  # 上限12段控成本
    bounds = [round(min(dur, i*phrase_len),2) for i in range(n)] + [round(dur,2)]
    print(f"⏱ {dur:.1f}s · 🥁 BPM {bpm} · ✂️ {phrase_len:.1f}s/段 → {n} 段 · vision描述中...")

    # 抽帧
    for i in range(n):
        t0,t1 = bounds[i],bounds[i+1]
        grab_frame(args.video, (t0+t1)/2, os.path.join(args.out,"frames",f"p{i+1}.jpg"))
    # vision 并行描述
    def _desc(i):
        t0,t1 = bounds[i],bounds[i+1]
        try: return vision_describe(os.path.join(args.out,"frames",f"p{i+1}.jpg"), i+1, t0, t1)
        except Exception as e:
            return {"i":i+1,"t0":round(t0,2),"t1":round(t1,2),"name":f"第{i+1}段","full":"","action":f"(描述失败:{e})","feet":"","intent":"","kou":""}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        phrases = sorted(ex.map(_desc, range(n)), key=lambda x:x["i"])
    for p in phrases: print(f"  {p['i']}. {p['name']} · {p['action'][:26]} · 口诀:{p['kou']}")

    story = {}
    try: story = deepseek_story(args.title, phrases)
    except Exception as e: story = {"title":"","body":f"(故事卡失败:{e})","chain":""}

    result = {"title":args.title,"bpm":bpm,"dur":round(dur,1),"phrases":phrases,"story":story}
    with open(os.path.join(args.out,"breakdown_auto.json"),"w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 自动拆解完成 → {args.out}/breakdown_auto.json  ({n}段+故事卡)")

if __name__ == "__main__":
    main()
