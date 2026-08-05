#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆卡 v3 —— 参考《清别欢》大字风格
每句：序号 + 超大核心字 | 句名 + 歌词 + 动作 | 底部金条口诀
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
from card_engine import font, safe, COLORS
from PIL import Image, ImageDraw

LYRICS = []  # 兜底空，避免印错歌曲的歌词到其他舞蹈卡片

def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "output/青山烟雨客"
    data   = json.load(open(os.path.join(outdir, "breakdown.json"), encoding="utf-8"))
    ph     = data["phrases"]
    title  = safe(data.get("title", ""))
    story  = data.get("story", {})
    mnemo  = safe((data.get("story") or {}).get("chain", ""))
    mnemo_sub = safe(data.get("mnemo_sub", ""))

    W       = 900
    PAD     = 20
    KEY_W   = 160    # 大字区宽度
    TEXT_X  = KEY_W + PAD   # 右侧文字起点

    ROW_H   = 220
    SZ_KEY  = 110    # 核心大字
    SZ_NUM  = 28     # 序号
    SZ_NAME = 30     # 句名
    SZ_LYR  = 22     # 歌词（蓝色，与动作同大小）
    SZ_ACT  = 22     # 动作描述（白色粗体）
    SZ_KOU  = 20     # 口诀金条

    HEADER_H = 160
    FOOTER_H = 200
    H = HEADER_H + ROW_H * len(ph) + FOOTER_H

    canvas = Image.new("RGB", (W, H), (11, 13, 22))
    d      = ImageDraw.Draw(canvas)

    # ── 头部 ──────────────────────────────────────────
    d.rectangle([0, 0, W, HEADER_H], fill=(17, 21, 38))
    d.text((PAD, 14), f"《{title}》·  动作记忆卡",
           font=font(36, bold=True), fill=(255, 255, 255))
    d.text((PAD, 60), "大字记忆 · 歌词 · 动作 · 口诀  ——  看一眼就记住",
           font=font(18), fill=(100, 140, 200))

    # 串联口诀条
    d.rectangle([0, 90, W, HEADER_H], fill=(22, 26, 48))
    if mnemo:
        d.text((PAD, 96), mnemo, font=font(26, bold=True), fill=(255, 218, 70))
    if mnemo_sub:
        d.text((PAD, 130), mnemo_sub, font=font(13), fill=(130, 160, 210))

    # ── 每行 ──────────────────────────────────────────
    y = HEADER_H
    for idx, p in enumerate(ph):
        col   = COLORS[idx % len(COLORS)]
        key   = safe(p.get("key", p.get("name", "")[:1]))
        name  = safe(p.get("name", ""))
        kou   = safe(p.get("kou", "")).replace("—", " · ")
        act   = safe(p.get("action", ""))[:36]
        lyric = p.get("lyric") or (LYRICS[idx] if idx < len(LYRICS) else "")

        row_bg = (15, 19, 32) if idx % 2 == 0 else (12, 15, 26)
        d.rectangle([0, y, W, y + ROW_H], fill=row_bg)
        d.rectangle([0, y, 5, y + ROW_H], fill=col)

        # ── 左：序号 + 大字 ──────────────────────────
        d.text((PAD, y + 8),  str(p["i"]), font=font(SZ_NUM, bold=True), fill=col)
        # 核心大字居中显示在左区
        key_x = PAD
        key_y = y + 34
        d.text((key_x, key_y), key, font=font(SZ_KEY, bold=True), fill=(255, 255, 255))

        # 竖向分隔线
        d.line([(KEY_W + 8, y + 12), (KEY_W + 8, y + ROW_H - 12)],
               fill=(40, 52, 80), width=1)

        # ── 右：句名 + 歌词 + 动作 + 口诀 ──────────
        tx = TEXT_X + 8
        ty = y + 14

        # 句名（句色）
        d.text((tx, ty), name, font=font(SZ_NAME, bold=True), fill=col)
        ty += SZ_NAME + 10

        # 歌词（蓝色，大且清晰）
        if lyric:
            d.text((tx, ty), "♪  " + lyric, font=font(SZ_LYR, bold=True), fill=(140, 200, 255))
            ty += SZ_LYR + 10

        # 动作（白色粗体）
        a1 = act[:20]
        a2 = act[20:40]
        if a1:
            d.text((tx, ty), a1, font=font(SZ_ACT, bold=True), fill=(235, 242, 255))
            ty += SZ_ACT + 6
        if a2:
            d.text((tx, ty), a2, font=font(SZ_ACT, bold=True), fill=(235, 242, 255))
            ty += SZ_ACT + 6

        # 口诀金条（底部）
        bar_y  = y + ROW_H - SZ_KOU - 22
        bar_x1 = tx - 6
        bar_x2 = W - PAD
        d.rounded_rectangle([bar_x1, bar_y, bar_x2, bar_y + SZ_KOU + 16],
                            radius=6, fill=(44, 37, 6))
        d.text((bar_x1 + 12, bar_y + 6), "★  " + kou,
               font=font(SZ_KOU, bold=True), fill=(255, 218, 70))

        d.line([(0, y + ROW_H - 1), (W, y + ROW_H - 1)], fill=(28, 35, 55), width=1)
        y += ROW_H

    # ── 串记故事 ──────────────────────────────────────
    chain = safe(story.get("chain", "")).replace("→", " > ")
    body  = safe(story.get("body", ""))

    d.rectangle([0, y, W, H], fill=(17, 21, 36))
    d.text((PAD, y + 16), "整支串记故事",
           font=font(22, bold=True), fill=(130, 170, 230))

    chain_lines = [chain[i:i+38] for i in range(0, len(chain), 38)]
    cy = y + 52
    for ln in chain_lines[:2]:
        d.text((PAD, cy), ln, font=font(18), fill=(255, 218, 80))
        cy += 28

    body_lines = [body[i:i+38] for i in range(0, len(body), 38)]
    by2 = cy + 8
    for ln in body_lines[:4]:
        d.text((PAD, by2), ln, font=font(17), fill=(195, 210, 240))
        by2 += 26

    out = os.path.join(outdir, "记忆卡v3.png")
    canvas = canvas.resize((canvas.width * 2, canvas.height * 2), Image.LANCZOS)
    canvas.save(out, quality=95)
    print(f"✅ {out}  {canvas.size}")

if __name__ == "__main__":
    main()
