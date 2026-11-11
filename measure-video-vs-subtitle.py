#!/usr/bin/env python3
"""实测：6 帧画面 vs 一段字幕文字，谁更费 token。用真实 DeepSeek API 的 usage 计。"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

CFG = "/opt/qq-agent/data/config.json"
cfg = json.load(open(CFG, encoding="utf-8"))
api = cfg["api"]
KEY = api["apiKey"]
BASE = api["baseUrl"].rstrip("/")
MODEL = api["model"]

tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "v.mp4")
# 造一个 8 秒测试视频
subprocess.run([
    "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
    "-i", "testsrc2=size=640x360:rate=15:duration=8",
    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", src,
], check=True)
# 抽 6 帧（和工具里同样的参数）
subprocess.run([
    "ffmpeg", "-y", "-v", "error", "-i", src,
    "-vf", "fps=0.75,scale='min(640,iw)':-2",
    "-frames:v", "6", "-q:v", "5", os.path.join(tmp, "f%02d.jpg"),
], check=True)
frames = sorted(f for f in os.listdir(tmp) if f.startswith("f") and f.endswith(".jpg"))
data_urls = []
for f in frames:
    b = open(os.path.join(tmp, f), "rb").read()
    data_urls.append("data:image/jpeg;base64," + base64.b64encode(b).decode())

print(f"抽到 {len(data_urls)} 帧，单帧约 {len(data_urls[0])*3//4//1024} KB")


def usage(messages, label):
    body = json.dumps({"model": MODEL, "messages": messages, "max_tokens": 8}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    u = d.get("usage") or {}
    pt = u.get("prompt_tokens")
    print(f"{label}: prompt_tokens = {pt}")
    return pt


# A. 6 帧图
parts = [{"type": "text", "text": "这几帧视频画面里在发生什么？"}]
for u in data_urls:
    parts.append({"type": "image_url", "image_url": {"url": u}})
a = usage([{"role": "user", "content": parts}], "A 6 帧画面")

# B. 一段 2000 字中文字幕（B站 5~8 分钟视频的典型量）
subtitle = "这是B站视频字幕的模拟文本，用来测量中文文字的token消耗。" * 40
subtitle = subtitle[:2000]
b = usage([{"role": "user", "content": "总结这段字幕：" + subtitle}], f"B {len(subtitle)} 字字幕")

print()
print(f"结论：6 帧画面 {a} tokens vs 2000 字字幕 {b} tokens")
if a and b:
    print(f"比值：画面是字幕的 {a/b:.1f} 倍" if a > b else f"比值：画面是字幕的 {a/b:.1f} 倍（字幕更贵）")
price_in = float(cfg["api"].get("priceInputPerM") or 0)
if price_in:
    print(f"按 {price_in} 元/百万 token：6 帧 {a*price_in/1e6:.5f} 元 | 2000字字幕 {b*price_in/1e6:.5f} 元")
