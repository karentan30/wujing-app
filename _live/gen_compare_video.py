#!/usr/bin/env python3
"""
舞镜 AI 对比视频生成器 — 真实数据版
用法: python3 gen_compare_video.py <review_json> <blogger_video> <learner_video> <output_mp4>

review_json 格式（来自 /api/solo/review/{id}）：
{
  "status": "completed",
  "score": 78,
  "dimensions": {"rhythm": 82, "posture": 74, "expression": 71, "coordination": 80, "flow": 76},
  "corrections": [
    {"phrase": "起势·沉肩", "praise": "节奏感很好", "suggestion": "呼气时双肩主动下沉",
     "encouragement": "已经有古典舞的骨架了", "score": 78},
    ...
  ],
  "summary": "整体流畅度高，建议加强..."
}
"""
import sys, os, json, subprocess, shutil
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ── 解析参数 ──────────────────────────────────────────────────────
if len(sys.argv) < 5:
    print("用法: gen_compare_video.py <review_json> <blogger_video> <learner_video> <output_mp4>")
    sys.exit(1)

REVIEW_JSON  = sys.argv[1]
BLOGGER      = sys.argv[2]
LEARNER      = sys.argv[3]
OUTPUT       = sys.argv[4]
TMP          = "/tmp/wj_compare_real"
os.makedirs(TMP, exist_ok=True)

# ── 读取真实 review 数据 ──────────────────────────────────────────
with open(REVIEW_JSON, encoding="utf-8") as f:
    review = json.load(f)

TOTAL_SCORE = int(review.get("score", 75))
raw_dims    = review.get("dimensions", {})
raw_corrs   = review.get("corrections", [])
SUMMARY     = review.get("summary", "")

# 五维标签映射（服务端字段名 → 显示名）
DIM_MAP = [
    ("rhythm",       "节奏"),
    ("posture",      "姿态"),
    ("expression",   "眼神"),
    ("coordination", "协调"),
    ("flow",         "流畅"),
]
DIMS_DISPLAY = [(label, int(raw_dims.get(key, TOTAL_SCORE))) for key, label in DIM_MAP]

# 把 corrections 转成视频用的 CORRECTIONS 列表
# 格式：(t_start, t_end, 动作名, 夸赞, 建议, 鼓励, 五维分数tuple)
def _build_corrections(raw, total_dur=20):
    if not raw:
        # 降级：只有 summary，构造一条占满全程的记录
        avg = TOTAL_SCORE
        dims_tuple = tuple(v for _, v in DIMS_DISPLAY)
        return [(0, total_dur, "AI 点评",
                 SUMMARY or "整体表现不错，继续加油！",
                 "保持练习，感受身体与音乐的连接",
                 "你已经在进步了",
                 dims_tuple)]
    seg = total_dur / len(raw)
    result = []
    for i, c in enumerate(raw):
        t0 = round(i * seg, 2)
        t1 = round((i + 1) * seg, 2)
        phrase   = c.get("phrase", f"段落{i+1}")
        praise   = c.get("praise", "表现很好！")
        suggest  = c.get("suggestion", "继续保持")
        encourage= c.get("encouragement", "你在进步！")
        sc       = int(c.get("score", TOTAL_SCORE))
        # 五维：如果 correction 里有细分就用，否则基于总分做微扰
        dims_tuple = tuple(
            int(raw_dims.get(key, max(60, sc + (j*3 - 6))))
            for j, (key, _) in enumerate(DIM_MAP)
        )
        result.append((t0, t1, phrase, praise, suggest, encourage, dims_tuple))
    return result

CORRECTIONS = _build_corrections(raw_corrs)
DUR = 20

# ── 视频参数 ──────────────────────────────────────────────────────
W, H      = 1080, 1920
VIDEO_H   = 960
PANEL_H   = 960
VIDEO_W   = 540
FPS       = 15

HOOK_END_FRAME   = int(FPS * 1.5)
OUTRO_START_FRAME= int((DUR - 2) * FPS)

# ── 颜色 ──────────────────────────────────────────────────────────
GOLD     = (181, 146, 42)
GOLD2    = (220, 185, 80)
RED      = (220, 60, 60)
YEL      = (240, 170, 50)
GRN      = (70, 200, 110)
WHITE    = (255, 255, 255)
GRAY     = (160, 155, 145)
BG_PANEL = (18, 14, 9)
BG_VIDEO = (8, 6, 4)
CREAM    = (250, 246, 238)
INK      = (30, 22, 12)
GOLD_D   = (160, 120, 28)
GOLD_L   = (200, 162, 60)
SEP      = (228, 216, 192)
SAGE     = (45, 110, 65)
TAUPE    = (120, 100, 68)
SCORE_BG = (245, 238, 218)

# ── 字体 ──────────────────────────────────────────────────────────
def find_font(size):
    for p in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── 工具函数 ──────────────────────────────────────────────────────
def get_corr(t):
    for c in CORRECTIONS:
        if c[0] <= t < c[1]:
            return c
    return CORRECTIONS[-1]

def wrap_text(draw, text, font, x, y, max_w, fill, line_h=34):
    line = ""
    for ch in text:
        test = line + ch
        try: tw = draw.textbbox((0, 0), test, font=font)[2]
        except: tw = len(test) * 16
        if tw > max_w:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h
            line = ch
        else:
            line = test
    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y

def animated_dim_score(base_score, t, seg_start):
    elapsed = t - seg_start
    if elapsed < 0.8:
        start = int(base_score * 0.80)
        return start + int((base_score - start) * elapsed / 0.8)
    return base_score

# ── 首帧钩子 ──────────────────────────────────────────────────────
def draw_hook_overlay(canvas, draw, frame_idx):
    alpha = max(0.0, 1.0 - frame_idx / HOOK_END_FRAME)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(200 * alpha)))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(overlay, (0, 0), overlay)
    result = canvas_rgba.convert("RGB")
    d = ImageDraw.Draw(result)

    title = "AI 正在分析你的舞蹈"
    f_big = find_font(72)
    f_sub = find_font(36)
    f_sm  = find_font(28)
    try: tw = d.textbbox((0, 0), title, font=f_big)[2]
    except: tw = 600
    d.text(((W - tw) // 2, H // 2 - 120), title, font=f_big, fill=GOLD2)

    sub = "· 逐动作鼓励点评 ·"
    try: sw = d.textbbox((0, 0), sub, font=f_sub)[2]
    except: sw = 300
    d.text(((W - sw) // 2, H // 2 - 30), sub, font=f_sub, fill=(200, 180, 100))

    brand = "舞镜 WuJing AI"
    try: bw = d.textbbox((0, 0), brand, font=f_sm)[2]
    except: bw = 200
    d.text(((W - bw) // 2, H // 2 + 60), brand, font=f_sm, fill=(120, 100, 60))
    return result

# ── 结尾帧 ──────────────────────────────────────────────────────
def draw_outro(canvas, draw, t):
    elapsed = t - (DUR - 2)
    alpha = min(1.0, elapsed / 0.5)
    overlay = Image.new("RGBA", (W, H), (12, 9, 4, int(220 * alpha)))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(overlay, (0, 0), overlay)
    result = canvas_rgba.convert("RGB")
    d = ImageDraw.Draw(result)

    f_huge = find_font(110)
    f_big  = find_font(56)
    f_mid  = find_font(36)
    f_sm   = find_font(26)

    cx, cy = W // 2, H // 2 - 180
    r = 140
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 24, 14), outline=GOLD, width=5)
    sc = str(int(TOTAL_SCORE * min(1.0, elapsed / 0.8)))
    try: sw = d.textbbox((0, 0), sc, font=f_huge)[2]
    except: sw = 80
    d.text((cx - sw // 2, cy - 66), sc, font=f_huge, fill=GOLD)
    d.text((cx - 40, cy + 60), "综合评分", font=f_sm, fill=GRAY)

    msg = "继续练，你在进步！"
    try: mw = d.textbbox((0, 0), msg, font=f_big)[2]
    except: mw = 400
    d.text(((W - mw) // 2, cy + r + 30), msg, font=f_big, fill=WHITE)

    # 五维评分条（使用真实数据）
    bar_y = cy + r + 120
    for idx, (dname, dval) in enumerate(DIMS_DISPLAY):
        bx = 80 + idx * 184
        col = GRN if dval >= 85 else (GOLD if dval >= 75 else YEL)
        d.text((bx, bar_y), dname, font=f_sm, fill=GRAY)
        d.rectangle([bx, bar_y + 30, bx + 100, bar_y + 44], fill=(35, 28, 16))
        d.rectangle([bx, bar_y + 30, bx + int(100 * dval / 100), bar_y + 44], fill=col)
        d.text((bx + 28, bar_y + 50), str(dval), font=f_sm, fill=col)

    # 结尾 summary（如果有）
    if SUMMARY:
        sum_y = cy + r + 260
        try: sum_w = d.textbbox((0, 0), SUMMARY[:20], font=f_sm)[2]
        except: sum_w = 400
        wrap_text(d, SUMMARY[:60], f_sm, 80, sum_y, W - 160, GRAY, line_h=36)

    cheer = "上传你的视频，看你的AI报告"
    cheer_y = cy + r + 380
    try: cw = d.textbbox((0, 0), cheer, font=f_mid)[2]
    except: cw = 450
    d.text(((W - cw) // 2, cheer_y), cheer, font=f_mid, fill=WHITE)

    brand_y = H - 140
    d.line([(120, brand_y), (W - 120, brand_y)], fill=(50, 42, 28), width=1)
    b_txt = "wujing.mylumee.app"
    try: btw = d.textbbox((0, 0), b_txt, font=f_sm)[2]
    except: btw = 300
    d.text(((W - btw) // 2, brand_y + 16), b_txt, font=f_sm, fill=(90, 76, 48))
    return result

# ── AI 点评面板 ──────────────────────────────────────────────────
def draw_panel(draw, canvas, t, y_off, frame_idx):
    c = get_corr(t)
    dims_base = c[6]
    anim_scores = [animated_dim_score(d, t, c[0]) for d in dims_base]

    score = int(62 + min(20, t * 1.0))
    seg_elapsed = t - c[0]
    if seg_elapsed < 1.5:
        start = int(score * 0.80)
        score = start + int((score - start) * seg_elapsed / 1.5)

    M = 36
    panel_img = Image.new("RGB", (W, PANEL_H), CREAM)
    pd = ImageDraw.Draw(panel_img)

    pd.rectangle([0, 0, W, 4], fill=GOLD_D)
    pd.rectangle([0, 4, W, 8], fill=(235, 224, 196))

    y = 22
    f_act   = find_font(56)
    f_score = find_font(72)
    f_lg    = find_font(36)
    f_md    = find_font(29)
    f_sm    = find_font(22)
    f_xs    = find_font(19)

    pd.text((M, y), c[2], font=f_act, fill=GOLD_D)

    r = 62
    cx, cy_c = W - M - r, y + r + 6
    pd.ellipse([cx - r, cy_c - r, cx + r, cy_c + r], fill=SCORE_BG, outline=GOLD_D, width=2)
    sc_str = str(score)
    try: sw = pd.textbbox((0, 0), sc_str, font=f_score)[2]
    except: sw = 52
    pd.text((cx - sw // 2, cy_c - 40), sc_str, font=f_score, fill=GOLD_D)
    pd.text((cx - 24, cy_c + 30), "AI评分", font=f_xs, fill=TAUPE)
    y += r * 2 + 28

    prog = min(1.0, t / DUR)
    bw = W - M * 2 - 120
    pd.rectangle([M, y, M + bw, y + 4], fill=SEP)
    pd.rectangle([M, y, M + int(bw * prog), y + 4], fill=GOLD_L)
    pd.text((M + bw + 14, y - 6), f"{int(prog * 100)}%", font=f_xs, fill=TAUPE)
    y += 28

    pd.line([(M, y), (W - M, y)], fill=SEP, width=1)
    y += 26

    pd.text((M, y), "◆  做得好", font=f_md, fill=SAGE)
    y += 42
    y = wrap_text(pd, c[3], f_lg, M + 4, y, W - M * 2, SAGE, line_h=48)
    y += 28

    pd.line([(M, y), (W - M, y)], fill=SEP, width=1)
    y += 26

    pd.text((M, y), "进阶一步", font=f_sm, fill=TAUPE)
    y += 34
    y = wrap_text(pd, c[4], f_md, M + 4, y, W - M * 2, TAUPE, line_h=38)
    y += 28

    pd.line([(M, y), (W - M, y)], fill=SEP, width=1)
    y += 20
    pd.text((M, y), "本段评估", font=f_xs, fill=TAUPE)
    y += 30

    dim_labels = [label for _, label in DIM_MAP]
    cell_w = (W - M * 2) // 5
    dot_r = 36
    for j, (dname, dval) in enumerate(zip(dim_labels, anim_scores)):
        cx2 = M + j * cell_w + cell_w // 2
        col = SAGE if dval >= 85 else (GOLD_D if dval >= 75 else (180, 140, 60))
        pd.ellipse([cx2 - dot_r, y, cx2 + dot_r, y + dot_r * 2], fill=SCORE_BG, outline=col, width=2)
        sc2 = str(dval)
        try: sw2 = pd.textbbox((0, 0), sc2, font=f_md)[2]
        except: sw2 = 22
        pd.text((cx2 - sw2 // 2, y + dot_r - 16), sc2, font=f_md, fill=col)
        try: lw = pd.textbbox((0, 0), dname, font=f_xs)[2]
        except: lw = len(dname) * 11
        pd.text((cx2 - lw // 2, y + dot_r * 2 + 8), dname, font=f_xs, fill=TAUPE)
    y += dot_r * 2 + 48

    pd.line([(M, y), (W - M, y)], fill=SEP, width=1)
    y += 26
    y = wrap_text(pd, c[5], f_lg, M, y, W - M * 2, GOLD_D, line_h=42)

    # 底部导航（动作名标签）
    nav_y = PANEL_H - 52
    pd.line([(M, nav_y), (W - M, nav_y)], fill=SEP, width=1)
    nav_y += 10
    xb = M
    for ci in CORRECTIONS:
        is_cur = (ci == c)
        lbl = ci[2]
        try: tw = pd.textbbox((0, 0), lbl, font=f_xs)[2] + 20
        except: tw = len(lbl) * 11 + 20
        if xb + tw > W - M:
            break
        bg = (240, 228, 196) if is_cur else CREAM
        ol = GOLD_D if is_cur else SEP
        pd.rectangle([xb, nav_y, xb + tw, nav_y + 28], fill=bg, outline=ol)
        pd.text((xb + 9, nav_y + 5), lbl, font=f_xs, fill=GOLD_D if is_cur else TAUPE)
        xb += tw + 8

    brand = "舞镜 WuJing AI"
    try: btw = pd.textbbox((0, 0), brand, font=f_xs)[2]
    except: btw = 140
    pd.text((W // 2 - btw // 2, PANEL_H - 20), brand, font=f_xs, fill=(180, 165, 130))

    canvas.paste(panel_img, (0, y_off))

# ── Step 1: 提取帧 ────────────────────────────────────────────────
print("[1/4] 提取帧...")
subprocess.run([
    "ffmpeg", "-y", "-i", BLOGGER,
    "-vf", (f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}"),
    "-q:v", "2", f"{TMP}/b_%05d.jpg"
], capture_output=True)

subprocess.run([
    "ffmpeg", "-y", "-i", LEARNER,
    "-vf", (f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},"
            f"eq=brightness=0.06:contrast=1.1:saturation=1.1"),
    "-q:v", "2", f"{TMP}/l_%05d.jpg"
], capture_output=True)

b_frames = sorted([f for f in os.listdir(TMP) if f.startswith("b_")])
l_frames = sorted([f for f in os.listdir(TMP) if f.startswith("l_")])
n = min(len(b_frames), len(l_frames), DUR * FPS)
print(f"  博主{len(b_frames)}帧，学员{len(l_frames)}帧，取{n}帧")

# ── Step 2: 合成每帧 ──────────────────────────────────────────────
print("[2/4] PIL 合成中...")
FRAMES_OUT = os.path.join(TMP, "out")
os.makedirs(FRAMES_OUT, exist_ok=True)

fn_label = find_font(26)

for i in range(n):
    t = i / FPS
    bf = Image.open(os.path.join(TMP, b_frames[i])).convert("RGB")
    lf = Image.open(os.path.join(TMP, l_frames[i])).convert("RGB")

    canvas = Image.new("RGB", (W, H), BG_VIDEO)
    draw   = ImageDraw.Draw(canvas)

    canvas.paste(bf, (0, 0))
    canvas.paste(lf, (VIDEO_W, 0))

    draw.line([(VIDEO_W - 1, 0), (VIDEO_W - 1, VIDEO_H)], fill=GOLD, width=3)
    draw.line([(VIDEO_W + 1, 0), (VIDEO_W + 1, VIDEO_H)], fill=(80, 64, 20), width=1)

    draw.rectangle([0, 0, VIDEO_W, 50], fill=(12, 9, 4))
    draw.text((16, 12), "◆ 博主示范", font=fn_label, fill=GOLD)
    draw.rectangle([VIDEO_W, 0, W, 50], fill=(12, 9, 4))
    draw.text((VIDEO_W + 16, 12), "▷ 你的跟练", font=fn_label, fill=GRAY)

    draw.rectangle([0, VIDEO_H, W, H], fill=BG_PANEL)

    if i >= OUTRO_START_FRAME:
        canvas = draw_outro(canvas, draw, t)
    else:
        draw_panel(draw, canvas, t, VIDEO_H, i)
        if i < HOOK_END_FRAME:
            canvas = draw_hook_overlay(canvas, draw, i)

    canvas.save(os.path.join(FRAMES_OUT, f"f_{i:05d}.jpg"), quality=90)
    if i % 30 == 0:
        print(f"  {i}/{n} ({t:.1f}s)")

print("[2/4] 合成完成")

# ── Step 3: 编码 ──────────────────────────────────────────────────
print("[3/4] 编码视频...")
no_audio = os.path.join(TMP, "no_audio.mp4")
subprocess.run([
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", f"{TMP}/out/f_%05d.jpg",
    "-c:v", "libx264", "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
    no_audio
], capture_output=True)

# ── Step 4: 加音频 ────────────────────────────────────────────────
print("[4/4] 加原声...")
r = subprocess.run([
    "ffmpeg", "-y",
    "-i", no_audio, "-i", BLOGGER,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
    "-shortest", OUTPUT
], capture_output=True, text=True)

if r.returncode != 0:
    shutil.copy(no_audio, OUTPUT)
    print("  (音频合并失败，输出无声版)")

if os.path.exists(OUTPUT):
    size = os.path.getsize(OUTPUT) / 1024 / 1024
    print(f"\n✅ {OUTPUT}")
    print(f"   {size:.1f}MB | {DUR}s | {W}x{H} | {FPS}fps | score={TOTAL_SCORE}")
else:
    print(f"\n❌ 输出文件未生成: {OUTPUT}")
    sys.exit(1)
