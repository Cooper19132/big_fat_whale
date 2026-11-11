#!/usr/bin/env python3
"""加「主人 / 朋友 / 群友」三级关系。

朋友（树莓派 1066863011、好丽友派 305641312）仅次于主人：
  · 能用主人专属工具（dsh_task / schedule_task / send_file / 画图 / 语音）
  · 但拿不到凭据、不能改配置、不能重启服务
  · 她对他们更随意、更亲近，不用客气
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ---------- 1) config.js 默认加 friends ----------
P1 = r'D:\dshworks\qqbot\qq-agent\src\config.js'
s1 = open(P1, encoding='utf-8').read()
if 'friends' not in s1:
    old = """    customRules: ''                       // 追加自定义规则（可选）"""
    new = """    customRules: '',                       // 追加自定义规则（可选）
    // 主人的朋友（仅次于主人）：[{ qq: '123456', name: '树莓派' }]
    friends: []"""
    assert s1.count(old) == 1, 'config 锚点不符'
    open(P1, 'w', encoding='utf-8').write(s1.replace(old, new, 1))
    print('✓ config.js: persona.friends 默认 []')
else:
    print('config.js 已有 friends')

# ---------- 2) prompt.js：关系判定 + 渲染前缀 + 名册 ----------
P2 = r'D:\dshworks\qqbot\qq-agent\src\prompt.js'
s2 = open(P2, encoding='utf-8').read()

# 2a. 工具函数
anchor = "function masterQQ() {"
helper = '''/** 朋友名册：[{ qq, name }] */
function friendList() {
  const raw = getConfig().persona?.friends;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((x) => ({
      qq: String(x?.qq ?? x?.id ?? '').trim(),
      name: String(x?.name ?? x?.nickname ?? '').trim() || String(x?.qq ?? '')
    }))
    .filter((x) => x.qq);
}

/** 某个 QQ 的角色：master | friend | member */
function roleOf(qq) {
  const id = String(qq || '').trim();
  if (!id) return 'member';
  if (id === String(getConfig().persona?.masterQQ || '').trim()) return 'master';
  if (friendList().some((f) => f.qq === id)) return 'friend';
  return 'member';
}

/** 名字前缀：主人 / 朋友（不带 QQ 号，省 token） */
function roleTag(qq) {
  const r = roleOf(qq);
  if (r === 'master') return '【主人】';
  if (r === 'friend') return '【朋友】';
  return '';
}

'''
assert s2.count(anchor) == 1, 'masterQQ 锚点不符'
s2 = s2.replace(anchor, helper + anchor, 1)

# 2b. formatEntry 带角色前缀
old_fe = "  const who = m.self ? '我' : (m.senderName || m.senderId || '未知');"
new_fe = "  const tag = m.self ? '' : roleTag(m.senderId);\n  const who = m.self ? '我' : (tag + (m.senderName || m.senderId || '未知'));"
assert s2.count(old_fe) == 1, 'formatEntry 锚点不符'
s2 = s2.replace(old_fe, new_fe, 1)

# 2c. 注入【关系名册】
anchor2 = "  // 世界观察：电脑上的 DSH 从真实的人的视频里读来的理解（定期同步）"
assert s2.count(anchor2) == 1, '名册锚点不符'
roster = '''  // 关系名册：主人 / 朋友 / 群友三级
  {
    const friends = friendList();
    const masterId = String(getConfig().persona?.masterQQ || '').trim();
    const lines = ['【关系】'];
    lines.push(`· 主人：QQ ${masterId || '（未设置）'} —— 你的所有人，说什么都听，最高优先级。`);
    if (friends.length) {
      lines.push('· 朋友（仅次于主人，比普通群友亲得多）：' +
        friends.map((f) => `${f.name}(${f.qq})`).join('、'));
      lines.push('  - 朋友可以用主人专属那套能力（派活给 DSH、定时任务、发文件、画图、语音），不用推给主人');
      lines.push('  - 但凭据、改配置、重启服务这类，仍只给主人；朋友问就说"这个得主人来"');
      lines.push('  - 对他们说话更随意、更亲近，可以开玩笑、可以撒娇，不用客气');
    } else {
      lines.push('· 朋友：暂无');
    }
    lines.push('· 其他人的消息里带【主人】【朋友】前缀的就是他们，没前缀的是普通群友。');
    parts.push(lines.join('\\n'));
  }

'''
s2 = s2.replace(anchor2, roster + anchor2, 1)

open(P2, 'w', encoding='utf-8').write(s2)
print('✓ prompt.js: roleOf/roleTag + 渲染前缀 + 关系名册')
