#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MediaPipe 姿态 → 真实关节角度。独立 venv 运行(避开主服务numpy冲突)。
用法: mpvenv/bin/python3 pose_angles.py <frame1.jpg> [frame2.jpg ...]
  → 输出 {"帧名": {angles...}} JSON。模型只加载一次(批量快)。
"""
import sys, json, math, os

MODEL = "/www/wujing-api/models/pose_landmarker.task"

def _ang(a, b, c):
    """B 点处 A-B-C 夹角(度)。a/b/c=(x,y)。"""
    v1 = (a[0] - b[0], a[1] - b[1]); v2 = (c[0] - b[0], c[1] - b[1])
    d = v1[0]*v2[0] + v1[1]*v2[1]
    n = math.hypot(*v1) * math.hypot(*v2)
    if n == 0: return None
    cos = max(-1.0, min(1.0, d / n))
    return round(math.degrees(math.acos(cos)), 1)

def _angles_from(lm):
    P = lambda i: (lm[i].x, lm[i].y)
    angles = {
        "right_elbow": _ang(P(12), P(14), P(16)),
        "left_elbow":  _ang(P(11), P(13), P(15)),
        "right_shoulder": _ang(P(24), P(12), P(14)),
        "left_shoulder":  _ang(P(23), P(11), P(13)),
        "right_knee": _ang(P(24), P(26), P(28)),
        "left_knee":  _ang(P(23), P(25), P(27)),
        "right_hip":  _ang(P(12), P(24), P(26)),
        "left_hip":   _ang(P(11), P(23), P(25)),
    }
    sh = ((lm[11].x+lm[12].x)/2, (lm[11].y+lm[12].y)/2)
    hp = ((lm[23].x+lm[24].x)/2, (lm[23].y+lm[24].y)/2)
    dx, dy = sh[0]-hp[0], sh[1]-hp[1]
    angles["torso_tilt"] = round(math.degrees(math.atan2(abs(dx), abs(dy) or 1e-6)), 1)
    return angles

def main():
    frames = sys.argv[1:]
    out = {}
    try:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        opts = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=MODEL), num_poses=1)
        det = vision.PoseLandmarker.create_from_options(opts)
        import numpy as np
        for f in frames:
            name = os.path.splitext(os.path.basename(f))[0]
            try:
                img = mp.Image.create_from_file(f)
                res = det.detect(img)
                if not res.pose_landmarks:
                    # 暗场/低对比重试：提亮+增对比（K-pop暗场舞台常检不到骨架）
                    try:
                        arr = img.numpy_view()
                        bright = np.clip(arr.astype(np.int16) * 1.6 + 45, 0, 255).astype(np.uint8)
                        img2 = mp.Image(image_format=mp.ImageFormat.SRGB,
                                        data=np.ascontiguousarray(bright))
                        res = det.detect(img2)
                    except Exception:
                        pass
                if not res.pose_landmarks:
                    out[name] = {"ok": False, "reason": "no_pose"}; continue
                lm = res.pose_landmarks[0]
                vis = round(sum(getattr(l, "visibility", 1) for l in lm) / len(lm), 2)
                out[name] = {"ok": True, "angles": _angles_from(lm), "visibility": vis}
            except Exception as e:
                out[name] = {"ok": False, "reason": str(e)[:120]}
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"_error": str(e)[:200]}))

if __name__ == "__main__":
    main()
