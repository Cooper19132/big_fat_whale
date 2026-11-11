#!/usr/bin/env python3
# 探测 B 站字幕接口在当前服务器（阿里云，未登录）能不能拿到
import json
import urllib.parse
import urllib.request

BV = "BV1d8pU6xEZX"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


print("=== 1) 视频基本信息 ===")
info = get(f"https://api.bilibili.com/x/web-interface/view?bvid={BV}")
d = info.get("data") or {}
print("code:", info.get("code"), info.get("message"))
print("标题:", d.get("title"))
print("cid:", d.get("cid"), "| aid:", d.get("aid"), "| 时长:", d.get("duration"), "秒")
print("UP:", (d.get("owner") or {}).get("name"))

cid, aid = d.get("cid"), d.get("aid")

print()
print("=== 2) 字幕列表（未登录状态） ===")
try:
    p = get(f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}")
    print("code:", p.get("code"), p.get("message"))
    subs = ((p.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    print("字幕条数:", len(subs))
    for s in subs[:5]:
        print("  -", s.get("lan_doc"), "|", (s.get("subtitle_url") or "")[:70])
    if subs:
        url = subs[0].get("subtitle_url", "")
        if url.startswith("//"):
            url = "https:" + url
        print()
        print("=== 3) 拉一条字幕正文看看 ===")
        body = get(url)
        items = body.get("body") or []
        print("字幕行数:", len(items))
        text = " ".join(i.get("content", "") for i in items[:40])
        print("前 200 字:", text[:200])
except Exception as e:
    print("字幕接口异常:", e)
