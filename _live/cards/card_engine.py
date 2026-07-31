#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
舞镜卡片公共引擎 v1
- 字体：Arial Unicode (支持→、所有中文、特殊符号)
- 文字过滤：自动清除 PIL 无法渲染的 emoji
- 布局：根据视频比例+句数+时长自动计算
"""
import os, re, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import statistics

# ─── 字体 ────────────────────────────────────────────────────────────────────
FONT_UNICODE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD    = "/System/Library/Fonts/STHeiti Medium.ttc"   # 粗体备用
FONT_LIGHT   = "/System/Library/Fonts/STHeiti Light.ttc"    # 细体备用

def font(sz, bold=False):
    """STHeiti 渲染（清晰粗体中文）；特殊字符在文字层提前替换，不靠字体兜底"""
    f = FONT_BOLD if bold else FONT_LIGHT
    return ImageFont.truetype(f, sz, index=0)

# ─── 文字清洗 ─────────────────────────────────────────────────────────────────
# 只匹配 emoji 区段，绝不包含 CJK（中文 U+4E00–U+9FFF 在 U+24C2 之后，会被宽范围误删）
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # 表情
    "\U0001F300-\U0001F5FF"   # 杂项符号
    "\U0001F680-\U0001F6FF"   # 交通/地图
    "\U0001F700-\U0001F77F"   # 炼金术符号
    "\U0001F780-\U0001F7FF"   # 几何形状
    "\U0001F800-\U0001F8FF"   # 补充箭头
    "\U0001F900-\U0001FAFF"   # 补充符号
    "\U00002600-\U000026FF"   # 杂项符号（☀☁等）
    "\U00002700-\U000027BF"   # 装饰符号
    "]+", flags=re.UNICODE
)

# STHeiti 不支持的字符（→←↑↓ 箭头 + emoji），其余中文符号均支持
_ARROW_MAP = {"→": ">", "←": "<", "↑": "^", "↓": "v",
              "➜": ">", "➡": ">", "⇒": ">"}

def safe(text):
    """去 emoji + 替换箭头；STHeiti 能渲染的 ★♪「」等保留"""
    t = _EMOJI_RE.sub("", str(text or ""))
    for bad, good in _ARROW_MAP.items():
        t = t.replace(bad, good)
    return t

def wrap(text, max_chars=26):
    """按字符数折行"""
    text = safe(text)
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return lines

# ─── 颜色 ────────────────────────────────────────────────────────────────────
COLORS = [
    (90,  150, 255),
    (80,  210, 130),
    (255, 160,  60),
    (220, 100, 200),
    (100, 210, 255),
    (255, 200,  80),
    (160, 130, 255),
    (80,  220, 180),
    (255, 130, 100),
    (200, 220,  80),
]

# ─── 视频尺寸探测 ─────────────────────────────────────────────────────────────
def video_size(src):
    """返回 (width, height)"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
            capture_output=True, text=True
        )
        w, h = [int(x) for x in r.stdout.strip().split(",")]
        return w, h
    except Exception:
        return 1920, 1080

# ─── 帧提取 ──────────────────────────────────────────────────────────────────
def grab_frame(src, t, out, w=200, crop=None):
    """
    crop: (crop_w, crop_h, crop_x) 用于横屏→竖切
    """
    if crop:
        cw, ch, cx = crop
        vf = f"crop={cw}:{ch}:{cx}:0,scale={w}:-1"
    else:
        vf = f"scale={w}:-1"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src,
         "-frames:v", "1", "-vf", vf, out],
        check=False
    )

def sharpness(path):
    try:
        im = Image.open(path).convert("L").resize((80, 80))
        edges = im.filter(ImageFilter.FIND_EDGES)
        return statistics.mean(edges.getdata())
    except Exception:
        return 0.0

def pick_frames(src, t0, t1, tmp, phrase_i, n=6, step=0.3, crop=None):
    """
    每 step 秒采样，按清晰度取 top-n 帧，按时间排序返回路径列表
    n 根据句子时长自动调整：短句少帧，长句多帧
    """
    dur = t1 - t0
    # 自动帧数：每 2s 一帧，最少 3 帧，最多 8 帧
    n_auto = max(3, min(8, int(dur / 2)))
    n = min(n, n_auto)

    candidates = []
    t = t0 + step
    while t < t1 - step * 0.5:
        out = os.path.join(tmp, f"c{phrase_i}_{len(candidates)}.jpg")
        grab_frame(src, t, out, w=220, crop=crop)
        if os.path.exists(out):
            candidates.append((t, sharpness(out), out))
        t += step

    if not candidates:
        return []
    candidates.sort(key=lambda x: -x[1])
    top = sorted(candidates[:n], key=lambda x: x[0])
    return [p for _, _, p in top]

# ─── 布局参数计算 ─────────────────────────────────────────────────────────────
def layout(vw, vh, n_phrases, card_w=900, left_frac=0.34, n_fr=6):
    """
    返回 dict：
      crop, fr_w, fr_h, phrase_h, left_w, right_w, n_fr
    """
    left_w  = int(card_w * left_frac)
    right_w = card_w - left_w
    fr_gap  = 3
    pad_r   = 10

    # 横屏 → 中心竖切
    if vw > vh:
        crop_w = int(vh * 9 / 16)
        crop_x = (vw - crop_w) // 2
        crop   = (crop_w, vh, crop_x)
        ar_h, ar_w = vh, crop_w        # 竖切后比例
    else:
        crop   = None
        ar_h, ar_w = vh, vw

    fr_w = (right_w - pad_r * 2 - fr_gap * (n_fr - 1)) // n_fr
    fr_h = int(fr_w * ar_h / ar_w)
    phrase_h = max(fr_h + 40, 200)

    return dict(
        crop=crop, fr_w=fr_w, fr_h=fr_h,
        phrase_h=phrase_h, left_w=left_w, right_w=right_w,
        n_fr=n_fr, fr_gap=fr_gap, pad_r=pad_r, card_w=card_w
    )
