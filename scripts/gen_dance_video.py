#!/usr/bin/env python3
"""
舞镜 · AI舞蹈素材生成脚本
用途：生成TikTok演示用舞蹈视频（无真人出镜版）
跑法：python3 gen_dance_video.py
输出：当前目录下 dance_A.mp4 / dance_B.mp4 / dance_C.mp4
"""

import os, time, requests, json
from pathlib import Path

ARK_KEY = os.environ.get("ARK_API_KEY", "")  # export ARK_API_KEY=your_key before running
MODEL   = "doubao-seedance-2-0-260128"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

SHOTS = [
    {
        "name": "dance_A",
        "desc": "练舞困惑·开头钩子",
        "prompt": (
            "Wide shot, Chinese female dancer (20s, black training clothes, hair bun) "
            "standing in front of large mirror in dance studio, mid-movement pause, "
            "looking at phone with confused expression. Soft fluorescent overhead light, "
            "neutral gray mirror background. 24mm lens, shallow depth of field. "
            "Color grade: desaturated, slightly cold. Slow motion 50%. "
            "Negative: no smile, no performance makeup, no stage lighting, "
            "no extra people, no bokeh."
        ),
        "duration": 3,
        "ratio": "9:16",
    },
    {
        "name": "dance_B",
        "desc": "古典舞动作片段·分屏演示用",
        "prompt": (
            "Medium shot, Chinese female dancer (20s, red hanfu sleeve costume) "
            "performing classical Chinese dance arm sequence: raise—contract—extend—drop, "
            "front-facing camera, pure black background. Key light 45 degree left, fill right. "
            "50mm lens, full body frame. Color grade: warm amber, high contrast. "
            "Normal speed then 50% slow-mo. "
            "Negative: no facial close-up, no stage fog, no jump cuts, "
            "no multiple dancers, no modern clothing."
        ),
        "duration": 5,
        "ratio": "9:16",
    },
    {
        "name": "dance_C",
        "desc": "跳成功·结尾正向",
        "prompt": (
            "Medium shot, same Chinese female dancer (20s, black training clothes, hair bun) "
            "performing clean arm sequence smoothly in front of mirror, slight natural smile, "
            "confident posture. Same dance studio. Warm golden side light from left. "
            "35mm lens, full body. Color grade: warm, slightly saturated. Real-time speed. "
            "Negative: no extreme emotion, no performance lighting, "
            "no text overlay, no phone in hand."
        ),
        "duration": 4,
        "ratio": "9:16",
    },
]

OUT_DIR = Path(__file__).parent.parent / "docs" / "marketing" / "dance_assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def submit(shot):
    payload = {
        "model": MODEL,
        "content": [{"type": "text", "text": shot["prompt"]}],
        "parameters": {
            "duration": shot["duration"],
            "resolution": "1080p",
            "aspect_ratio": shot["ratio"],
        },
    }
    headers = {"Authorization": f"Bearer {ARK_KEY}", "Content-Type": "application/json"}
    r = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    task_id = r.json()["id"]
    print(f"  ✅ 提交成功 task_id={task_id}")
    return task_id


def poll(task_id, timeout=300):
    url = f"{API_URL}/{task_id}"
    headers = {"Authorization": f"Bearer {ARK_KEY}"}
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        status = data.get("status")
        print(f"  状态: {status}")
        if status == "succeeded":
            return data["content"][0]["video_url"]
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"生成失败: {data}")
        time.sleep(10)
    raise TimeoutError("超时 300s")


def download(url, path):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    path.write_bytes(r.content)
    print(f"  💾 已保存 → {path}")


def main():
    jobs = []
    print("=== 提交所有任务 ===")
    for shot in SHOTS:
        print(f"\n▶ {shot['name']} ({shot['desc']})")
        task_id = submit(shot)
        jobs.append((shot, task_id))

    print("\n=== 轮询结果 ===")
    for shot, task_id in jobs:
        print(f"\n▶ {shot['name']} 等待中...")
        video_url = poll(task_id)
        out_path = OUT_DIR / f"{shot['name']}.mp4"
        download(video_url, out_path)

    print(f"\n🎉 全部完成！文件在 {OUT_DIR}")


if __name__ == "__main__":
    main()
