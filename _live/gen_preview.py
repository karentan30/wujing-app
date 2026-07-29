#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 auto_decompose 的 breakdown_auto.json 渲染成国风主题跟练页（给Karen看效果）。"""
import json, os, shutil, sys, html

src = sys.argv[1]  # out dir with breakdown_auto.json + frames/
d = json.load(open(os.path.join(src, "breakdown_auto.json")))
outdir = sys.argv[2]
os.makedirs(os.path.join(outdir, "frames"), exist_ok=True)
for f in os.listdir(os.path.join(src, "frames")):
    shutil.copy(os.path.join(src, "frames", f), os.path.join(outdir, "frames", f))

def esc(s): return html.escape(str(s or ""))

beats = ""
for p in d["phrases"]:
    beats += f"""
    <div class="gf-beat">
      <div class="grid"><div class="fr"><img src="frames/p{p['i']}.jpg" loading="lazy"></div></div>
      <div class="bd">
        <div class="nm">{esc(p['name'])} <i>{p['t0']}–{p['t1']}s</i></div>
        <div class="row"><b>动作</b>{esc(p['action'])}</div>
        <div class="row"><b>脚下</b>{esc(p['feet'])}</div>
        <div class="row intent"><b>意境</b>{esc(p['intent'])}</div>
        <div class="kou">怎么记 · {esc(p['kou'])}</div>
        <div class="play"><span class="on">慢放 0.5×</span><span>▷ 正常速</span></div>
      </div>
    </div>"""

story = d.get("story", {})
tpl = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#d6d9de;padding:26px 16px 40px;display:flex;flex-direction:column;align-items:center}}
.cap{{font-size:12px;color:#7a8390;margin-bottom:14px;text-align:center;line-height:1.7}}
.cap b{{color:#3a3f47}}
.phone{{width:370px;border-radius:38px;overflow:hidden;box-shadow:0 24px 64px rgba(0,0,0,.28);border:8px solid #18171c}}
.scr{{height:760px;overflow-y:auto;scrollbar-width:none;background:#FAF7F0}}
.scr::-webkit-scrollbar{{display:none}}
.gf-hero{{position:relative;padding:26px 20px 0;background:linear-gradient(180deg,#F4EDD8 0%,#FAF7F0 100%);overflow:hidden}}
.gf-title{{font-family:"Noto Serif SC",serif;font-size:28px;font-weight:900;color:#1F1A14;letter-spacing:3px;margin-bottom:6px}}
.gf-sub{{font-size:11px;color:#9A8768;letter-spacing:1.5px;padding-bottom:18px}}
.gf-hero-line{{position:absolute;bottom:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,#C4A052 30%,#C4A052 70%,transparent);opacity:.35}}
.auto-badge{{display:inline-block;margin:0 20px;margin-top:14px;background:#EFE6CE;color:#7A5C2A;font-size:11px;font-weight:600;padding:5px 12px;border-radius:20px;letter-spacing:.5px}}
.gf-sec{{display:flex;align-items:center;gap:8px;margin:20px 20px 10px}}
.gf-sec-bar{{width:3px;height:16px;background:#B5922A;border-radius:2px}}
.gf-sec-label{{font-family:"Noto Serif SC",serif;font-size:14px;font-weight:700;color:#4A3820;letter-spacing:2px}}
.gf-beat{{background:#fff;border:1px solid #EDE4CF;border-radius:16px;margin:0 20px 12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.05)}}
.gf-beat .grid{{display:flex;gap:3px;padding:0;background:#FAF7F0;border-bottom:1px solid #EDE4CF}}
.gf-beat .fr{{flex:1;aspect-ratio:16/10;overflow:hidden;position:relative;background:linear-gradient(160deg,#2a2418,#4a3f2a)}}
.gf-beat .fr img{{width:100%;height:100%;object-fit:cover;object-position:center 30%;display:block}}
.gf-beat .bd{{padding:14px 16px 16px}}
.gf-beat .nm{{font-family:"Noto Serif SC",serif;font-size:20px;font-weight:900;color:#1F1A14;display:flex;align-items:baseline;gap:10px}}
.gf-beat .nm i{{font-size:11px;color:#9A8768;font-style:normal}}
.gf-beat .row{{font-size:12px;color:#4A3820;line-height:1.75;margin-top:3px}}
.gf-beat .row b{{color:#B5922A;font-weight:600;margin-right:6px;font-size:11px}}
.gf-beat .kou{{background:#FAF5E8;border:1px solid #EDE4CF;border-radius:8px;padding:8px 12px;margin-top:10px;font-size:12px;color:#7A5C2A}}
.gf-beat .play{{display:flex;gap:8px;margin-top:10px}}
.gf-beat .play span{{flex:1;text-align:center;font-size:12px;padding:8px;border-radius:20px;border:1px solid #D8CBA8;color:#7A5C2A}}
.gf-beat .play span.on{{background:#B5922A;color:#fff;border-color:#B5922A}}
.gf-story{{background:#fff;border:1px solid #EDE4CF;border-radius:16px;padding:18px 20px;margin:0 20px 28px;box-shadow:0 2px 12px rgba(0,0,0,.05)}}
.gf-story .h{{font-family:"Noto Serif SC",serif;font-size:16px;font-weight:900;color:#1F1A14;margin-bottom:10px;letter-spacing:1px}}
.gf-story .p{{font-size:13px;color:#4A3820;line-height:1.9}}
.gf-story .chain{{margin-top:12px;padding-top:12px;border-top:1px solid #EDE4CF;font-size:12px;color:#7A5C2A;line-height:1.8}}
</style></head><body>
<div class="cap"><b>舞镜 · 任意舞自动拆解（真实验证）</b><br>只上传了《洛神赋》一支视频，八拍卡/动作描述/口诀/故事卡 <b>100% AI自动生成</b>，零人工填写</div>
<div class="phone"><div class="scr">
  <div class="gf-hero">
    <div class="gf-title">{esc(d['title'])}</div>
    <div class="gf-sub">自动拆解 · {d['bpm']} BPM · {len(d['phrases'])}段 · {d['dur']}s</div>
    <div class="gf-hero-line"></div>
  </div>
  <div class="auto-badge">✦ AI 自动拆解 · 上传即得</div>
  <div class="gf-sec"><div class="gf-sec-bar"></div><div class="gf-sec-label">八拍卡 · 跟练</div></div>
  {beats}
  <div class="gf-sec"><div class="gf-sec-bar"></div><div class="gf-sec-label">故事卡</div></div>
  <div class="gf-story">
    <div class="h">{esc(story.get('title'))}</div>
    <div class="p">{esc(story.get('body'))}</div>
    <div class="chain">串记 · {esc(story.get('chain'))}</div>
  </div>
</div></div>
</body></html>"""
open(os.path.join(outdir, "index.html"), "w").write(tpl)
print("wrote", os.path.join(outdir, "index.html"))
