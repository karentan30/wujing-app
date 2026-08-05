#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成三张PNG卡片（八拍卡/镜面卡/记忆卡），自动patch服务器字体路径。
用法: python3 gen_cards.py <did> <video_path> <output_dir>
"""
import sys, os, types as _types

FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_L = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
CARDS_DIR = os.path.dirname(os.path.abspath(__file__))

def _patch(src):
    src = src.replace("/System/Library/Fonts/STHeiti Medium.ttc", FONT_B)
    src = src.replace("/System/Library/Fonts/STHeiti Light.ttc", FONT_L)
    return src

# patch card_engine 并注入 sys.modules
_ce_src = _patch(open(os.path.join(CARDS_DIR, "card_engine.py"), encoding="utf-8").read())
_ce_mod = _types.ModuleType("card_engine")
exec(compile(_ce_src, "card_engine.py", "exec"), _ce_mod.__dict__)
sys.modules["card_engine"] = _ce_mod

def _qa_check(path, name):
    """生成后自动 sanity check，有问题立刻报警而不是静默通过。"""
    from PIL import Image
    issues = []
    if not os.path.exists(path):
        print(f"❌ QA FAIL [{name}]: 文件不存在"); return
    size = os.path.getsize(path)
    if size < 500_000:
        issues.append(f"文件 {size//1024}KB 过小（预期>500KB，可能渲染失败）")
    try:
        im = Image.open(path)
        w, h = im.size
        if h < w:
            issues.append(f"尺寸 {w}×{h} 异常（卡片应竖版，高>宽）")
        if h < 2000:
            issues.append(f"高度 {h}px 过矮（预期>2000px，可能内容被截断）")
        # 检查 header 区域不是纯黑（说明背景色正常渲染）
        header = im.crop((0, 0, min(w, 200), min(h, 60))).convert("RGB")
        pixels = list(header.getdata())
        avg = sum(r+g+b for r,g,b in pixels) / (len(pixels)*3)
        if avg < 5:
            issues.append("Header 区域接近纯黑，背景可能未渲染")
    except Exception as e:
        issues.append(f"图片读取失败: {e}")
    if issues:
        print(f"⚠️  QA WARNING [{name}]:")
        for iss in issues:
            print(f"   · {iss}")
    else:
        print(f"✅ {name}  {size//1024}KB  QA通过")

def gen_all(did, video_path, outdir):
    if not os.path.exists(os.path.join(outdir, "breakdown.json")):
        raise FileNotFoundError(f"breakdown.json not found in {outdir}")

    scripts = [
        ("八拍卡_v3.py",  "八拍卡v3.png",  [video_path, outdir]),
        ("镜面卡_v3.py",  "镜面卡v3.png",  [video_path, outdir]),
        ("记忆卡_v3.py",  "记忆卡v3.png",  [outdir]),
    ]
    for script_name, card_name, argv in scripts:
        script = os.path.join(CARDS_DIR, script_name)
        if not os.path.exists(script):
            print(f"⚠️  {script_name} not found"); continue
        src = _patch(open(script, encoding="utf-8").read())
        mod = _types.ModuleType(f"card_{script_name}")
        mod.__dict__["__name__"] = "__main__"
        mod.__dict__["__file__"] = script
        sys.argv = [script] + argv
        try:
            exec(compile(src, script, "exec"), mod.__dict__)
            mod.main()
            out = os.path.join(outdir, card_name)
            _qa_check(out, card_name)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"❌ {script_name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: gen_cards.py <did> <video_path> <output_dir>"); sys.exit(1)
    gen_all(sys.argv[1], sys.argv[2], sys.argv[3])
