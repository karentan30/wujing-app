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
            size = os.path.getsize(out) if os.path.exists(out) else 0
            print(f"✅ {card_name}  {size//1024}KB")
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"❌ {script_name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: gen_cards.py <did> <video_path> <output_dir>"); sys.exit(1)
    gen_all(sys.argv[1], sys.argv[2], sys.argv[3])
