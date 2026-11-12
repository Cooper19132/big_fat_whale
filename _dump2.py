import json, datetime
d = json.load(open("group_1035218437.json", encoding="utf-8"))
ms = [m for m in (d.get("messages") if isinstance(d, dict) else d) or [] if m.get("text")]
ms.sort(key=lambda m: m.get("ts") or 0)
target = {"哦鲸鲸", "扶她奶昔"}
sel = [m for m in ms if str(m.get("senderName")) in target]
print("两人消息数", len(sel))
for m in sel[-40:]:
    st = datetime.datetime.fromtimestamp((m.get("ts") or 0) / 1000).strftime("%m-%d %H:%M")
    t = str(m.get("text"))[:150]
    print(st, str(m.get("senderName")), ":", t)
