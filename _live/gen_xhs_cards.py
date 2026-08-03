#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜小红书批量图片生成 - 功能介绍 + 使用场景"""

from PIL import Image, ImageDraw, ImageFont
import os, textwrap

FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_L = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

W, H = 1080, 1440

def F(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_L, sz, index=0)

# Color palette
BG_DARK   = (8, 10, 24)
BG_CARD   = (16, 19, 42)
PURPLE    = (130, 90, 220)
GOLD      = (255, 200, 60)
WHITE     = (255, 255, 255)
GRAY      = (160, 170, 200)
LIGHT_BLU = (140, 190, 255)
ACCENT    = (180, 120, 255)

def make_canvas():
    img = Image.new("RGB", (W, H), BG_DARK)
    d = ImageDraw.Draw(img)
    # top gradient bar
    for i in range(6):
        alpha = 255 - i * 30
        d.rectangle([0, i, W, i+1], fill=(130//2, 90//2, 220//2))
    d.rectangle([0, 6, W, 8], fill=PURPLE)
    return img, d

def draw_logo(d, y=30):
    d.text((54, y), "舞 镜", font=F(36, bold=True), fill=PURPLE)
    d.text((54, y+46), "WUJING · AI口诀学舞", font=F(20), fill=GRAY)

def draw_footer(d):
    d.rectangle([0, H-80, W, H], fill=(12, 14, 30))
    d.text((54, H-56), "wujing.mylumee.app", font=F(24), fill=PURPLE)
    d.text((54, H-28), "口诀刻进脑子 · 动作永不忘", font=F(18), fill=GRAY)

def wrap_text(d, text, x, y, width, font, fill, line_height=None):
    """Draw wrapped text, return final y"""
    chars_per_line = width // font.size if hasattr(font, 'size') else width // 28
    lines = []
    for para in text.split('\n'):
        if len(para) <= chars_per_line:
            lines.append(para)
        else:
            wrapped = textwrap.wrap(para, chars_per_line)
            lines.extend(wrapped if wrapped else [para])
    lh = line_height or int(font.size * 1.45) if hasattr(font, 'size') else 40
    for line in lines:
        d.text((x, y), line, font=font, fill=fill)
        y += lh
    return y

def draw_tag(d, text, x, y, bg=PURPLE, fg=WHITE, padding=16, radius=12):
    tw = F(22, bold=True).getlength(text) + padding*2
    d.rounded_rectangle([x, y, x+tw, y+38], radius=radius, fill=bg)
    d.text((x+padding, y+6), text, font=F(22, bold=True), fill=fg)
    return x + tw + 16

def draw_numbered_item(d, num, title, desc, x, y, accent_color=PURPLE):
    # Circle number
    d.ellipse([x, y, x+48, y+48], fill=accent_color)
    d.text((x+14, y+8), str(num), font=F(26, bold=True), fill=WHITE)
    # Title
    d.text((x+64, y+4), title, font=F(28, bold=True), fill=WHITE)
    # Desc
    d.text((x+64, y+38), desc, font=F(20), fill=GRAY)
    return y + 72

def save(img, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, name)
    img.save(path, quality=95)
    print(f"✓ {path}")
    return path

OUTDIR = "/www/wujing-api/static/xhs/wujing_launch"

# ============================================================
# 功能介绍 1: 舞镜是什么？六件套总览
# ============================================================
def card_f1():
    img, d = make_canvas()
    draw_logo(d)

    # Big headline
    d.text((54, 120), "上课前没法预习？", font=F(60, bold=True), fill=WHITE)
    d.text((54, 195), "上完课全忘了？", font=F(60, bold=True), fill=GOLD)

    # Divider
    d.rectangle([54, 280, 440, 284], fill=PURPLE)

    d.text((54, 306), "舞镜帮你把每支舞", font=F(36), fill=GRAY)
    d.text((54, 354), "变成永远记得住的口诀", font=F(36, bold=True), fill=WHITE)

    # Six-piece badge area
    d.rounded_rectangle([40, 420, W-40, 980], radius=24, fill=BG_CARD)
    d.text((54, 440), "六件套  ·  一支舞学会全靠它", font=F(26, bold=True), fill=ACCENT)

    items = [
        ("◆", "八拍卡", "每句动作+口诀 一眼全看清"),
        ("◇", "镜面卡", "镜面翻转 跟着帧图做"),
        ("★", "记忆卡", "AI老师总结记忆要诀"),
        ("▷", "慢放视频", "0.5倍速 动作全看清"),
        ("♪", "TTS朗读", "边听口诀边做动作"),
        ("●", "AI预习文字", "上课前2分钟读完"),
    ]
    y = 490
    for emoji, title, desc in items:
        d.text((70, y), emoji, font=F(32), fill=WHITE)
        d.text((120, y+2), title, font=F(28, bold=True), fill=WHITE)
        d.text((120, y+36), desc, font=F(20), fill=GRAY)
        y += 78

    # CTA
    d.rounded_rectangle([40, 1010, W-40, 1100], radius=20, fill=PURPLE)
    d.text((240, 1030), "上传视频  →  3分钟出六件套", font=F(30, bold=True), fill=WHITE)

    d.text((54, 1130), "免费体验", font=F(40, bold=True), fill=GOLD)
    d.text((54, 1180), "现在上传你的舞蹈视频", font=F(28), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "F1_六件套总览.jpg")

# ============================================================
# 功能介绍 2: 口诀卡是什么
# ============================================================
def card_f2():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "3个字", font=F(100, bold=True), fill=GOLD)
    d.text((54, 228), "记住一个动作", font=F(56, bold=True), fill=WHITE)

    d.rectangle([54, 318, 380, 322], fill=PURPLE)
    d.text((54, 340), "这就是口诀的力量", font=F(32), fill=GRAY)

    # Example card
    d.rounded_rectangle([40, 400, W-40, 820], radius=24, fill=BG_CARD)
    d.text((70, 430), "《清明雨上》 · 口诀示例", font=F(26, bold=True), fill=ACCENT)

    phrases = [
        ("1", "起手亮相", "抬—拧—展—笑"),
        ("2", "柔臂流水", "拧—落—柔—沉"),
        ("3", "仰首托月", "抬—仰—托"),
        ("4", "拢袖转身", "拢—转—扬"),
        ("5", "遮面含羞", "遮—伸—稳"),
    ]
    y = 490
    for num, name, kou in phrases:
        # Number circle
        d.ellipse([70, y, y-480+550, y+36], fill=(50, 30, 100))
        d.ellipse([70, y, 106, y+36], fill=PURPLE)
        d.text((80, y+4), num, font=F(22, bold=True), fill=WHITE)
        d.text((120, y+2), name, font=F(24), fill=GRAY)
        d.text((120, y+32), kou, font=F(28, bold=True), fill=GOLD)
        y += 76

    # How it works
    d.rounded_rectangle([40, 850, W-40, 1060], radius=24, fill=(20, 14, 50))
    d.text((70, 876), "怎么用口诀？", font=F(30, bold=True), fill=WHITE)
    steps = [
        "① 上课前：看口诀默念3遍",
        "② 上课中：身体记住口诀触发动作",
        "③ 下课后：闭眼过一遍口诀 = 复习完成",
    ]
    y = 928
    for s in steps:
        d.text((70, y), s, font=F(24), fill=LIGHT_BLU)
        y += 42

    d.text((54, 1100), "每个动作3-4个字", font=F(36, bold=True), fill=GOLD)
    d.text((54, 1148), "念一遍身体就知道该做什么", font=F(28), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "F2_口诀是什么.jpg")

# ============================================================
# 功能介绍 3: 慢放视频
# ============================================================
def card_f3():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "0.5倍速", font=F(96, bold=True), fill=GOLD)
    d.text((54, 228), "把动作看清楚", font=F(56, bold=True), fill=WHITE)

    d.rectangle([54, 315, 520, 319], fill=PURPLE)
    d.text((54, 338), "每一帧都是学习机会", font=F(32), fill=GRAY)

    # Before/After comparison
    d.rounded_rectangle([40, 400, W-40, 700], radius=24, fill=BG_CARD)
    d.text((70, 430), "普通视频 vs 舞镜慢放", font=F(26, bold=True), fill=ACCENT)

    # Left: normal
    d.rounded_rectangle([60, 480, 480, 670], radius=16, fill=(14, 12, 30))
    d.text((70, 500), "普通速度", font=F(24, bold=True), fill=(200, 80, 80))
    d.text((70, 540), "• 动作一闪而过", font=F(22), fill=GRAY)
    d.text((70, 574), "• 不知道脚怎么站", font=F(22), fill=GRAY)
    d.text((70, 608), "• 只能猜", font=F(22), fill=GRAY)

    # Right: slow
    d.rounded_rectangle([500, 480, 990+50, 670], radius=16, fill=(14, 30, 50))
    d.text((520, 500), "舞镜慢放", font=F(24, bold=True), fill=GOLD)
    d.text((520, 540), "• 手指位置看清楚", font=F(22), fill=WHITE)
    d.text((520, 574), "• 脚步重心全看到", font=F(22), fill=WHITE)
    d.text((520, 608), "• 跟练不费力", font=F(22), fill=WHITE)

    # Visual steps
    d.rounded_rectangle([40, 720, W-40, 1060], radius=24, fill=(20, 14, 50))
    d.text((70, 750), "慢放 + 口诀  =  学会的公式", font=F(28, bold=True), fill=WHITE)

    steps = [
        ("看", "慢放视频看清楚动作"),
        ("念", "同时听TTS朗读口诀"),
        ("做", "按口诀提示做动作"),
        ("记", "动作和口诀绑定记忆"),
    ]
    y = 810
    for key, desc in steps:
        d.rounded_rectangle([70, y, 130, y+52], radius=10, fill=PURPLE)
        d.text((84, y+10), key, font=F(28, bold=True), fill=WHITE)
        d.text((150, y+12), desc, font=F(26), fill=GRAY)
        y += 68

    d.text((54, 1100), "不再凭感觉", font=F(40, bold=True), fill=GOLD)
    d.text((54, 1150), "慢放让每个细节都清晰", font=F(28), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "F3_慢放视频.jpg")

# ============================================================
# 功能介绍 4: 上传即出六件套
# ============================================================
def card_f4():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "上传视频", font=F(72, bold=True), fill=WHITE)
    d.text((54, 204), "3分钟出六件套", font=F(56, bold=True), fill=GOLD)

    d.rectangle([54, 295, 560, 299], fill=PURPLE)
    d.text((54, 318), "AI全自动 · 不需要手动标注", font=F(30), fill=GRAY)

    # Timeline
    d.rounded_rectangle([40, 380, W-40, 1060], radius=24, fill=BG_CARD)
    d.text((70, 410), "全程自动 · 你只需要等3分钟", font=F(26, bold=True), fill=ACCENT)

    steps = [
        (PURPLE,    "上传",  "拍下舞蹈视频上传到舞镜"),
        (LIGHT_BLU, "拆解",  "AI自动识别动作分段"),
        ((100,200,120), "生成口诀", "DeepSeek生成3-4字口诀"),
        (GOLD,      "出卡",  "三张PNG卡片自动生成"),
        ((200,100,200), "慢放",  "0.5倍速慢放视频生成"),
        ((255,160,80),"TTS", "每句口诀音频自动朗读"),
    ]
    y = 468
    for i, (color, title, desc) in enumerate(steps):
        # Circle
        d.ellipse([70, y, 114, y+44], fill=color)
        d.text((84, y+8), str(i+1), font=F(24, bold=True), fill=WHITE)
        if i < len(steps)-1:
            d.line([(92, y+44), (92, y+76)], fill=(50, 60, 100), width=2)
        d.text((130, y+4), title, font=F(28, bold=True), fill=WHITE)
        d.text((130, y+36), desc, font=F(20), fill=GRAY)
        y += 86

    d.text((54, 1090), "一键搞定", font=F(40, bold=True), fill=GOLD)
    d.text((54, 1140), "再也不用手动整理舞蹈笔记", font=F(26), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "F4_上传即出.jpg")

# ============================================================
# 功能介绍 5: 会员权益
# ============================================================
def card_f5():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "舞蹈界的", font=F(50, bold=True), fill=GRAY)
    d.text((54, 178), "《九阳真经》", font=F(72, bold=True), fill=GOLD)

    d.rectangle([54, 275, 600, 279], fill=PURPLE)
    d.text((54, 298), "别人教你做什么  我们教你永远记住", font=F(28), fill=GRAY)

    # Tiers
    tiers = [
        ((40, 980), (30, 25, 60),   "免费版",   "体验3支舞口诀卡",         "¥0",    GRAY),
        ((40, 700), (20, 14, 50),   "个人会员", "无限舞库 + 全六件套",     "¥29/月", ACCENT),
        ((40, 420), (16, 10, 40),   "老师版",   "上传自己视频 + 学生分享", "¥99/月", GOLD),
    ]

    y = 380
    for rect, bg, title, desc, price, color in tiers:
        d.rounded_rectangle([40, y, W-40, y+200], radius=20, fill=bg)
        d.rectangle([40, y, 48, y+200], fill=color)
        d.text((70, y+20), title, font=F(32, bold=True), fill=color)
        d.text((70, y+66), desc, font=F(24), fill=GRAY)
        # Price on right
        d.text((W-180, y+30), price, font=F(36, bold=True), fill=color)
        y += 218

    d.text((54, 1050), "1000+支舞蹈", font=F(44, bold=True), fill=WHITE)
    d.text((54, 1106), "古风 · K-pop · 拉丁 · 爵士 · 广场", font=F(26), fill=GRAY)

    # CTA button
    d.rounded_rectangle([54, 1170, W-54, 1280], radius=24, fill=PURPLE)
    d.text((280, 1196), "免费开始体验  →", font=F(40, bold=True), fill=WHITE)

    draw_footer(d)
    return save(img, OUTDIR, "F5_会员权益.jpg")

# ============================================================
# 使用场景 1: 上课前10分钟预习
# ============================================================
def card_s1():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "上课前", font=F(52), fill=GRAY)
    d.text((54, 178), "10分钟预习", font=F(72, bold=True), fill=WHITE)
    d.text((54, 258), "上课效果翻倍", font=F(52, bold=True), fill=GOLD)

    d.rectangle([54, 336, 560, 340], fill=PURPLE)

    # Time blocks
    blocks = [
        (8, "-10min", "打开舞镜", "看口诀卡，看清8个动作"),
        (3, "-7min",  "听TTS朗读", "边走路边听口诀音频"),
        (2, "-5min",  "看慢放",   "0.5倍速把动作看一遍"),
        (5, "-3min",  "默念口诀", "闭眼过一遍，身体提前激活"),
    ]

    y = 370
    for dur, time_label, action, desc in blocks:
        d.rounded_rectangle([40, y, W-40, y+130], radius=18, fill=BG_CARD)
        # Time
        d.text((60, y+16), time_label, font=F(26, bold=True), fill=ACCENT)
        # Duration badge
        d.rounded_rectangle([W-120, y+16, W-54, y+54], radius=8, fill=PURPLE)
        d.text((W-108, y+24), f"{dur}min", font=F(20, bold=True), fill=WHITE)
        # Action
        d.text((60, y+56), action, font=F(32, bold=True), fill=WHITE)
        d.text((60, y+96), desc, font=F(20), fill=GRAY)
        y += 148

    d.text((54, 1000), "再也不是", font=F(36), fill=GRAY)
    d.text((54, 1046), "进教室才知道学什么", font=F(40, bold=True), fill=WHITE)

    d.rounded_rectangle([54, 1110, W-54, 1200], radius=20, fill=(20, 14, 50))
    d.text((70, 1128), "「每次上课前没有图片，我都不想去上课」", font=F(22), fill=LIGHT_BLU)
    d.text((70, 1164), "                              — 真实用户反馈", font=F(20), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "S1_上课前预习.jpg")

# ============================================================
# 使用场景 2: 舞室镜前练功
# ============================================================
def card_s2():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "站在舞室镜子前", font=F(44), fill=GRAY)
    d.text((54, 172), "忘了下一个动作？", font=F(60, bold=True), fill=WHITE)
    d.text((54, 244), "口诀瞬间想起来", font=F(56, bold=True), fill=GOLD)

    d.rectangle([54, 326, 580, 330], fill=PURPLE)

    # Scenario
    d.rounded_rectangle([40, 358, W-40, 680], radius=24, fill=BG_CARD)
    d.text((70, 388), "练功现场", font=F(28, bold=True), fill=ACCENT)

    scenes = [
        ("跳到第3段", "突然脑子空白", (200, 80, 80)),
        ("想起口诀", "「拧—落—柔—沉」", GOLD),
        ("身体接上", "动作自然流出来", (80, 200, 120)),
    ]
    y = 436
    for trigger, result, color in scenes:
        d.rounded_rectangle([60, y, W-60, y+78], radius=14, fill=(20, 18, 45))
        d.text((80, y+12), trigger, font=F(24), fill=GRAY)
        d.text((80, y+44), result, font=F(26, bold=True), fill=color)
        y += 94

    # Mirror card preview
    d.rounded_rectangle([40, 700, W-40, 1040], radius=24, fill=(16, 12, 38))
    d.text((70, 730), "镜面卡 · 对着镜子直接用", font=F(28, bold=True), fill=WHITE)
    d.text((70, 776), "• 帧图已镜面翻转，和你看镜子一模一样", font=F(22), fill=GRAY)
    d.text((70, 818), "• 8帧均匀采样，每个细节都有", font=F(22), fill=GRAY)
    d.text((70, 860), "• 口诀在旁边，手机放旁边随时看", font=F(22), fill=GRAY)
    d.text((70, 902), "• 不需要反复重播视频找那一帧", font=F(22), fill=GRAY)

    d.text((54, 1066), "练功效率", font=F(36), fill=GRAY)
    d.text((54, 1112), "直接翻倍", font=F(64, bold=True), fill=GOLD)

    draw_footer(d)
    return save(img, OUTDIR, "S2_镜前练功.jpg")

# ============================================================
# 使用场景 3: 睡前刷口诀
# ============================================================
def card_s3():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "睡前5分钟", font=F(64, bold=True), fill=WHITE)
    d.text((54, 196), "闭上眼睛过一遍口诀", font=F(40), fill=GRAY)
    d.text((54, 248), "隔天去跳  身体记住了", font=F(40, bold=True), fill=GOLD)

    d.rectangle([54, 310, 620, 314], fill=PURPLE)
    d.text((54, 334), "睡眠巩固记忆 · 科学原理", font=F(26), fill=GRAY)

    # Brain + sleep diagram
    d.rounded_rectangle([40, 380, W-40, 640], radius=24, fill=BG_CARD)
    d.text((70, 410), "为什么睡前复习有用？", font=F(28, bold=True), fill=ACCENT)
    d.text((70, 460), "睡眠期间大脑会巩固白天学到的动作记忆", font=F(22), fill=GRAY)
    d.text((70, 500), "口诀 = 给大脑一个钩子", font=F(28, bold=True), fill=WHITE)
    d.text((70, 542), "有钩子的记忆  比没钩子的记忆", font=F(22), fill=GRAY)
    d.text((70, 578), "巩固效率高 3-5 倍", font=F(32, bold=True), fill=GOLD)

    # Before/after
    d.rounded_rectangle([40, 660, W-40, 1020], radius=24, fill=(16, 12, 38))
    d.text((70, 690), "同一首舞  两种记法对比", font=F(28, bold=True), fill=WHITE)

    cols = [
        ("没有口诀", ["睡前反复看视频", "越看越焦虑", "第二天还是忘", "练10遍才隐约记住"], (200, 80, 80)),
        ("有口诀", ["睡前念一遍口诀", "3分钟念完放松", "第二天身体有印象", "练3遍就跑通"], GOLD),
    ]
    cx = 70
    for title, points, color in cols:
        d.text((cx, 730), title, font=F(26, bold=True), fill=color)
        py = 778
        for pt in points:
            d.text((cx, py), "· " + pt, font=F(20), fill=GRAY)
            py += 38
        cx = 580

    d.text((54, 1048), "从今晚开始", font=F(36, bold=True), fill=WHITE)
    d.text((54, 1094), "让口诀帮你睡着就在学舞", font=F(28), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "S3_睡前口诀.jpg")

# ============================================================
# 使用场景 4: 忘了某段秒回看
# ============================================================
def card_s4():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "跳到第6段", font=F(56), fill=GRAY)
    d.text((54, 184), "脑子突然空白？", font=F(64, bold=True), fill=WHITE)

    d.text((54, 280), "打开舞镜  3秒找到", font=F(48, bold=True), fill=GOLD)

    d.rectangle([54, 354, 560, 358], fill=PURPLE)

    # Phone mockup area
    d.rounded_rectangle([40, 380, W-40, 760], radius=24, fill=BG_CARD)
    d.text((70, 410), "舞镜八拍卡  快速导航", font=F(28, bold=True), fill=ACCENT)

    # Simulated phrase list
    phrases_demo = [
        ("1", "起手亮相", "抬—拧—展—笑"),
        ("2", "柔臂流水", "拧—落—柔—沉"),
        ("3", "仰首托月", "抬—仰—托"),
        ("4", "拢袖转身", "拢—转—扬"),
        ("5", "遮面含羞", "遮—伸—稳"),
        ("6", "举臂仰望", "举—仰—展", True),  # highlighted
        ("7", "遮面含羞", "举扇—侧腰—点地"),
    ]
    y = 468
    for item in phrases_demo:
        num, name, kou = item[:3]
        highlight = len(item) > 3 and item[3]
        bg = (60, 30, 120) if highlight else (20, 18, 45)
        d.rounded_rectangle([60, y, W-60, y+54], radius=10, fill=bg)
        d.text((76, y+10), f"第{num}段", font=F(20, bold=True), fill=ACCENT if highlight else GRAY)
        d.text((160, y+6), name, font=F(22), fill=WHITE)
        d.text((420, y+10), kou, font=F(22, bold=True), fill=GOLD if highlight else GRAY)
        y += 62

    # Bottom message
    d.rounded_rectangle([40, 780, W-40, 1060], radius=24, fill=(16, 12, 38))
    d.text((70, 810), "不用倒带  不用截图", font=F(32, bold=True), fill=WHITE)
    points = [
        "每段都有时间轴，精确到0.1秒",
        "口诀触发动作，看一眼就想起来",
        "帧图已标注，手脚位置全在",
        "点开clip片段，直接跳到那段",
    ]
    py = 870
    for pt in points:
        d.text((70, py), "✓  " + pt, font=F(22), fill=GRAY)
        py += 42

    d.text((54, 1090), "舞蹈笔记", font=F(40), fill=GRAY)
    d.text((54, 1138), "从此不用自己记", font=F(48, bold=True), fill=GOLD)

    draw_footer(d)
    return save(img, OUTDIR, "S4_忘了秒找.jpg")

# ============================================================
# 使用场景 5: 舞蹈老师备课
# ============================================================
def card_s5():
    img, d = make_canvas()
    draw_logo(d)

    d.text((54, 120), "舞蹈老师", font=F(56), fill=GRAY)
    d.text((54, 178), "备课新方式", font=F(72, bold=True), fill=WHITE)

    d.rectangle([54, 274, 500, 278], fill=GOLD)
    d.text((54, 298), "上传  →  学生提前预习  →  课堂效率翻倍", font=F(26), fill=GRAY)

    # Benefits grid
    d.rounded_rectangle([40, 360, W-40, 800], radius=24, fill=BG_CARD)
    d.text((70, 390), "老师专业版  ·  ¥99/月", font=F(28, bold=True), fill=GOLD)

    benefits = [
        ("↑", "上传自己的教学视频", "AI自动生成口诀和六件套"),
        ("⊕", "一键分享给所有学生", "学生上课前自行预习"),
        ("¥", "分成收入", "会员收入30%归你"),
        ("≡", "学生练习数据", "哪段最难 一眼看出来"),
    ]
    y = 448
    for emoji, title, desc in benefits:
        d.text((70, y), emoji, font=F(32), fill=WHITE)
        d.text((120, y+2), title, font=F(26, bold=True), fill=WHITE)
        d.text((120, y+36), desc, font=F(20), fill=GRAY)
        y += 78

    # Quote
    d.rounded_rectangle([40, 820, W-40, 1000], radius=24, fill=(20, 14, 50))
    d.text((70, 850), "「以前学生上课总问同一个问题", font=F(24), fill=LIGHT_BLU)
    d.text((70, 888), "  有了口诀预习  第一遍就跑通了」", font=F(24), fill=LIGHT_BLU)
    d.text((70, 940), "                        — 瑶瑶老师 古典舞老师", font=F(20), fill=GRAY)

    # CTA
    d.rounded_rectangle([54, 1020, W-54, 1130], radius=22, fill=GOLD)
    d.text((240, 1046), "申请老师合作  →", font=F(38, bold=True), fill=(20, 14, 30))

    d.text((54, 1160), "零广告费  靠口碑增长", font=F(30), fill=GRAY)

    draw_footer(d)
    return save(img, OUTDIR, "S5_老师备课.jpg")

# Run all
if __name__ == "__main__":
    results = []
    results.append(card_f1())
    results.append(card_f2())
    results.append(card_f3())
    results.append(card_f4())
    results.append(card_f5())
    results.append(card_s1())
    results.append(card_s2())
    results.append(card_s3())
    results.append(card_s4())
    results.append(card_s5())
    print(f"\n生成完成：{len(results)} 张图片")
    print("目录:", OUTDIR)
