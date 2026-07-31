#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八拍卡 v3 —— 参考《清别欢》风格
左：序号 + 超大核心字 + 时间 + 口诀(金色) + 动作描述 + 歌词
右：8帧均匀分段采样（每段最清晰一帧）
"""
import json, os, subprocess, sys, statistics
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

FONT_B = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_L = "/System/Library/Fonts/STHeiti Light.ttc"

def F(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_L, sz, index=0)

LYRICS = [
    "远方有琴  愀然空灵",
    "声声催天雨  涓涓心事说给自己听",
    "月影憧憧  烟火几重  烛花红",
    "红尘旧梦  梦断都成空",
    "雨打湿了眼眶",
    "年年倚井盼归堂",
    "最怕不觉  泪已拆两行",
    "我在人间彷徨  寻不到你的天堂",
    "东瓶西镜放  恨不能遗忘",
    "又是清明雨上  折菊寄到你身旁",
]

def grab_frame(src, t, out, w=200, crop=None):
    vf = f"crop={crop[0]}:{crop[1]}:{crop[2]}:0,scale={w}:-1" if crop else f"scale={w}:-1"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src,
                    "-frames:v", "1", "-vf", vf, out], check=False)

def sharpness(path):
    try:
        im = Image.open(path).convert("L").resize((80, 80))
        edges = im.filter(ImageFilter.FIND_EDGES)
        return statistics.mean(edges.getdata())
    except Exception:
        return 0.0

def pick_best_frames(src, t0, t1, tmp, phrase_i, n=8, step=0.2, crop=None):
    """时间均匀分 n 段，每段取最清晰一帧"""
    dur = t1 - t0
    candidates = []
    t = t0 + step
    while t < t1 - step * 0.5:
        out = os.path.join(tmp, f"cand_{phrase_i}_{len(candidates)}.jpg")
        grab_frame(src, t, out, w=200, crop=crop)
        if os.path.exists(out):
            candidates.append((t, sharpness(out), out))
        t += step
    if not candidates:
        return []
    seg_dur = dur / n
    selected = []
    for i in range(n):
        seg_t0 = t0 + i * seg_dur
        seg_t1 = t0 + (i + 1) * seg_dur
        seg = [c for c in candidates if seg_t0 <= c[0] < seg_t1]
        if seg:
            selected.append(max(seg, key=lambda x: x[1]))
    selected.sort(key=lambda x: x[0])
    return [p for _, _, p in selected]

COLORS = [
    (90, 150, 255), (80, 210, 130), (255, 160, 60), (220, 100, 200),
    (100, 210, 255), (255, 200, 80), (160, 130, 255), (80, 220, 180),
    (255, 120, 120), (200, 220, 80),
]

W       = 1100
LEFT_W  = 290
RIGHT_W = W - LEFT_W
N_FR    = 8
FR_GAP  = 3
PAD_L   = 14
PAD_R   = 8

def main():
    src, outdir = sys.argv[1], sys.argv[2]
    data = json.load(open(os.path.join(outdir, "breakdown.json")))
    ph = data["phrases"]

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
        capture_output=True, text=True)
    vw, vh = 1920, 1080
    try:
        parts = probe.stdout.strip().split(",")
        vw, vh = int(parts[0]), int(parts[1])
    except Exception:
        pass

    crop = None
    if vw > vh:
        crop_w = int(vh * 9 // 16)
        crop_x = (vw - crop_w) // 2
        crop = (crop_w, vh, crop_x)
        FR_W = (RIGHT_W - PAD_R * 2 - FR_GAP * (N_FR - 1)) // N_FR
        FR_H = int(FR_W * vh / crop_w)
    else:
        FR_W = (RIGHT_W - PAD_R * 2 - FR_GAP * (N_FR - 1)) // N_FR
        FR_H = int(FR_W * vh / vw)

    PHRASE_H = max(FR_H + 30, 220)
    HEADER_H = 100
    FOOTER_H = 80
    H = HEADER_H + PHRASE_H * len(ph) + FOOTER_H

    tmp = os.path.join(outdir, "_v3_tmp")
    os.makedirs(tmp, exist_ok=True)
    print(f"视频 {vw}×{vh}  帧 {FR_W}×{FR_H}  句高 {PHRASE_H}px")

    strips = []
    for p in ph:
        print(f"  句{p['i']} {p['name']} {p['t0']:.1f}–{p['t1']:.1f}s")
        frames = pick_best_frames(src, p["t0"], p["t1"], tmp, p["i"],
                                  n=N_FR, step=0.2, crop=crop)
        strips.append((p, frames))

    canvas = Image.new("RGB", (W, H), (10, 12, 20))
    d = ImageDraw.Draw(canvas)

    # 头部
    d.rectangle([0, 0, W, HEADER_H], fill=(17, 21, 38))
    title = data.get("title", "")
    d.text((PAD_L, 16), f"《{title}》·  八拍卡", font=F(40, bold=True), fill=(255, 255, 255))
    d.text((PAD_L, 66), f"口诀 · 动作 · 歌词  ——  {len(ph)} 句完整拆解",
           font=F(18), fill=(110, 155, 210))

    y = HEADER_H
    for idx, (p, frames) in enumerate(strips):
        col    = COLORS[idx % len(COLORS)]
        key    = p.get("key", p.get("name", "")[:1])   # 核心大字
        kou    = p.get("kou", "").replace("—", " · ")
        action = p.get("action", "")[:38]
        lyric  = p.get("lyric") or (LYRICS[idx] if idx < len(LYRICS) else "")
        t0, t1 = p["t0"], p["t1"]

        row_bg = (15, 19, 31) if idx % 2 == 0 else (12, 15, 26)
        d.rectangle([0, y, W, y + PHRASE_H], fill=row_bg)
        d.rectangle([0, y, 5, y + PHRASE_H], fill=col)

        # ── 左面板 ──────────────────────────────────
        lx = PAD_L + 6

        # 序号（小）+ 时间
        d.text((lx, y + 10), str(p["i"]), font=F(32, bold=True), fill=col)
        t_str = f"  {t0:.1f}–{t1:.1f}s"
        d.text((lx + 36, y + 16), t_str, font=F(14), fill=(80, 110, 155))

        # 核心大字
        key_y = y + 46
        d.text((lx, key_y), key, font=F(110, bold=True), fill=(255, 255, 255))

        # 口诀（金色粗体）
        kou_y = key_y + 100
        d.text((lx, kou_y), kou, font=F(20, bold=True), fill=(255, 212, 55))

        # 动作描述（灰白，2行）
        MAX_A = 18
        a1 = action[:MAX_A]
        a2 = action[MAX_A:MAX_A * 2]
        act_y = kou_y + 28
        if a1:
            d.text((lx, act_y),      a1, font=F(16), fill=(185, 195, 225))
        if a2:
            d.text((lx, act_y + 20), a2, font=F(16), fill=(185, 195, 225))

        # 歌词（蓝色，与动作同大小）
        lyric_y = act_y + 48
        if lyric and lyric_y < y + PHRASE_H - 20:
            d.text((lx, lyric_y), "♪  " + lyric, font=F(16), fill=(140, 200, 255))

        # ── 右帧区 ──────────────────────────────────
        rx = LEFT_W + PAD_R
        fy = y + (PHRASE_H - FR_H) // 2

        for fi, fp in enumerate(frames):
            fx = rx + fi * (FR_W + FR_GAP)
            if os.path.exists(fp):
                im = Image.open(fp).convert("RGB")
                im = im.resize((FR_W, FR_H), Image.LANCZOS)
                canvas.paste(im, (fx, fy))
            else:
                d.rectangle([fx, fy, fx + FR_W, fy + FR_H], fill=(25, 30, 50))

        d.line([(0, y + PHRASE_H - 1), (W, y + PHRASE_H - 1)], fill=(28, 36, 58), width=1)
        y += PHRASE_H

    d.rectangle([0, y, W, H], fill=(14, 18, 30))
    d.text((PAD_L, y + 20), f"舞镜 AI  ·  {title}  ·  《清明雨上》许嵩",
           font=F(18), fill=(80, 100, 150))

    for f in os.listdir(tmp):
        try:
            os.remove(os.path.join(tmp, f))
        except Exception:
            pass
    try:
        os.rmdir(tmp)
    except Exception:
        pass

    out = os.path.join(outdir, "八拍卡v3.png")
    canvas = canvas.resize((canvas.width * 2, canvas.height * 2), Image.LANCZOS)
    canvas.save(out, quality=95)
    print(f"✅ {out}  {canvas.size}")

if __name__ == "__main__":
    main()
