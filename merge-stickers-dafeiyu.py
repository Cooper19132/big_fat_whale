#!/usr/bin/env python3
"""把 dsh-meme 的大肥鱼 24 张带语义表情，合并进 qq-agent 的表情库。"""
import json
import io
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CDN = 'https://cdn.jsdelivr.net/gh/yyh-001/dsh-meme@main/docs/dafeiyu/'
MANIFEST = 'manifest.json'
OLD = 'stickers-import.json'
OUT = 'stickers-import-v2.json'

# 文件名 → 中文语义（用于模型挑选）
CAPTIONS = {
    'bixin': '比心（撒娇、感谢）',
    'buyao': '不要（拒绝、摆手）',
    'deyi': '得意（炫耀、骄傲）',
    'ganfan': '干饭（吃饭、饿了）',
    'haixiu': '害羞（被夸、不好意思）',
    'huachi': '花痴（看呆了、好可爱）',
    'jiaban': '加班（累了、还在忙）',
    'jiazai': '加载中（卡住、宕机）',
    'maozhua': '猫爪（伸手、要东西）',
    'ok': 'OK（好的、没问题）',
    'piaole': '飘了（开森、飞起）',
    'qiurao': '求饶（认错、放过我）',
    'shengqi': '生气（鼓脸、不开心）',
    'shuijiao': '睡觉（困了、晚安）',
    'tangping': '躺平（摆烂、不想动）',
    'toukan': '偷看（暗中观察）',
    'wenhao': '疑问（问号脸、啥意思）',
    'wuyu': '无语（沉默、不知道该说什么）',
    'xia': '吓（被吓到、震惊）',
    'xianqi': '嫌弃（白眼、鄙视）',
    'yaoqian': '求打赏（要 token、讨饭）',
    'yun': '晕（被绕晕、头大）',
    'zaoshanghao': '早上好（打招呼）',
    'zhenjing': '震惊（目瞪口呆）',
}

now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
entries = []
for stem, cap in CAPTIONS.items():
    entries.append({
        'id': f'dafeiyu-{stem}',
        'resId': f'dafeiyu-{stem}',
        'url': f'{CDN}{stem}.jpg',
        'desc': cap,
        'localNote': '',
        'tags': ['大肥鱼', '鲸鱼娘', '有文案', '表情'],
        'usage': '',
        'source': 'manual',
        'useCount': 0,
        'lastUsedAt': 0,
        'lastContext': '',
        'createdAt': now,
        'updatedAt': now,
    })

old = json.load(open(OLD, encoding='utf-8'))
merged = entries + old
json.dump(merged, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"新增 {len(entries)} 条带文案 + 旧的 {len(old)} 条 = {len(merged)} 条 → {OUT}")
print("样例:", json.dumps(entries[0], ensure_ascii=False))
