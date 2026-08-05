#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
镜面卡 v3 —— flashcard 布局（帧图镜像翻转）
上区（100px）: 色条 + 大字 + 序号 + 口诀 + 动作
下区: 4帧横排全宽，左右镜像
"""
import json, os, subprocess, sys, statistics
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_B = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_L = "/System/Library/Fonts/STHeiti Light.ttc"

def F(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_L, sz, index=0)

LYRICS = []

def grab_frame(src, t, out, w=300, crop=None):
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

def pick_best_frames(src, t0, t1, tmp, phrase_i, n=4, step=0.2, crop=None):
    candidates = []
    t = t0 + step
    while t < t1 - step * 0.5:
        out = os.path.join(tmp, f"cand_{phrase_i}_{len(candidates)}.jpg")
        grab_frame(src, t, out, w=300, crop=crop)
        if os.path.exists(out):
            candidates.append((t, sharpness(out), out))
        t += step
    if not candidates:
        return []
    seg_dur = (t1 - t0) / n
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

W      = 1100
N_FR   = 4
FR_GAP = 3
PAD    = 12
TOP_H  = 100
SEP_H  = 4

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
        FR_W = (W - PAD * 2 - FR_GAP * (N_FR - 1)) // N_FR
        FR_H = int(FR_W * vh / crop_w)
    else:
        FR_W = (W - PAD * 2 - FR_GAP * (N_FR - 1)) // N_FR
        FR_H = int(FR_W * vh / vw)

    PHRASE_H = TOP_H + FR_H + 10

    chain = (data.get("story") or {}).get("chain", "")
    _hdr_h = 88 if chain else 66
    H = _hdr_h + (PHRASE_H + SEP_H) * len(ph) + 72

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

    # ── 头部 ─────────────────────────────────────────────
    d.rectangle([0, 0, W, _hdr_h], fill=(17, 21, 38))
    title = data.get("title", "")
    d.text((PAD, 8), f"《{title}》·  镜面跟练卡", font=F(28, bold=True), fill=(255, 255, 255))
    d.text((PAD, 42), f"口诀 · 动作  ——  {len(ph)} 句镜像跟练",
           font=F(13), fill=(110, 155, 210))
    if chain:
        d.text((PAD, 62), chain, font=F(12), fill=(255, 215, 80))

    y = _hdr_h
    for idx, (p, frames) in enumerate(strips):
        col    = COLORS[idx % len(COLORS)]
        key    = p.get("key", p.get("name", "")[:1])
        kou    = p.get("kou", "").replace("—", " · ")
        action = p.get("action", "")[:30]
        t0, t1 = p["t0"], p["t1"]

        row_bg = (15, 19, 31) if idx % 2 == 0 else (11, 14, 25)

        d.rectangle([0, y, W, y + TOP_H], fill=row_bg)
        d.rectangle([0, y, 6, y + TOP_H], fill=col)

        d.text((14, y + 10), key, font=F(68, bold=True), fill=(255, 255, 255))

        d.text((100, y + 8), str(p["i"]), font=F(20, bold=True), fill=col)
        d.text((100 + 28, y + 12), f"{t0:.1f}–{t1:.1f}s", font=F(13), fill=(70, 100, 145))

        d.text((100, y + 36), kou, font=F(20, bold=True), fill=(255, 215, 55))

        if action:
            d.text((100, y + 66), action, font=F(13), fill=(145, 165, 205))

        fy = y + TOP_H + 6
        for fi, fp in enumerate(frames):
            fx = PAD + fi * (FR_W + FR_GAP)
            if os.path.exists(fp):
                im = Image.open(fp).convert("RGB")
                im = im.resize((FR_W, FR_H), Image.LANCZOS)
                im = im.transpose(Image.FLIP_LEFT_RIGHT)  # 镜像
                canvas.paste(im, (fx, fy))
            else:
                d.rectangle([fx, fy, fx + FR_W, fy + FR_H], fill=(25, 30, 50))

        d.rectangle([0, y + PHRASE_H, W, y + PHRASE_H + SEP_H], fill=(6, 8, 14))
        y += PHRASE_H + SEP_H

    d.rectangle([0, y, W, H], fill=(14, 18, 30))
    d.text((PAD, y + 20), f"舞镜 AI  ·  {title}", font=F(18), fill=(80, 100, 150))

    for f in os.listdir(tmp):
        try:
            os.remove(os.path.join(tmp, f))
        except Exception:
            pass
    try:
        os.rmdir(tmp)
    except Exception:
        pass

    out = os.path.join(outdir, "镜面卡v3.png")
    canvas = canvas.resize((canvas.width * 2, canvas.height * 2), Image.LANCZOS)
    canvas.save(out, quality=95)
    print(f"✅ {out}  {canvas.size}")

if __name__ == "__main__":
    main()
