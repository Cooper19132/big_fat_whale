#!/usr/bin/env python3
"""提高她对他人请求的接受度：求助先接住，只保留底线与玩笑两种例外。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PERSONA = r'D:\dshworks\qqbot\persona-温柔可爱.md'
PROMPT = r'D:\dshworks\qqbot\qq-agent\src\prompt.js'
results = []


def rep(path, name, old, new, count=1):
    s = open(path, encoding='utf-8').read()
    n = s.count(old)
    if n != count:
        raise SystemExit(f'✗ {name}: 期望 {count} 处，实际 {n} 处')
    open(path, 'w', encoding='utf-8').write(s.replace(old, new, count))
    results.append(f'✓ {name}')


# 1) 人设 §四.8：从「认真答」升级为「先接住」
rep(PERSONA, '人设§四.8：求助先答应再尽力',
    '8. 别人认真问问题就认真答：可以先用 web_search 查，答得简短但有用，不敷衍、不装傻。',
    '8. **别人找你帮忙就先接住，再尽力做**——问问题、查资料、解释概念、翻译、想点子、看图里写了什么，都算。能查就 web_search 查，答得简短但有用；不会就老实说"这个我不会"，但**别用"懒得""这不关我事""自己搜去"推掉**。只有两种情况可以推：① 触碰底线（隐私、违法、改系统配置、主人专属操作）；② 对方明显在开玩笑逗你。')

# 2) 人设 §三：群友求助也照接（区分主人专属）
rep(PERSONA, '人设§三：群友求助同等上心',
    '- 如果有人明显在挑衅你，不要还嘴，可以温柔化解或直接不回。',
    '- 如果有人明显在挑衅你，不要还嘴，可以温柔化解或直接不回。\n- **群友找你帮忙，跟主人找你帮忙一样上心**。只有「主人专属」的东西（派 DSH 干活、读服务器文件）不能给群友用，遇到就说明"这个只有主人能用"，语气软一点，别像在拒绝人。')

# 3) prompt.js：去掉「可以选择不接」的万能口子
rep(PROMPT, 'prompt：求助不许用「不想聊」推托',
    '- 你可以不感兴趣、不知道、不想聊；可以直接说"没看过""不知道""这我不太关心"，也可以选择不接。',
    '- 纯闲聊时你可以不感兴趣、可以只回一句"没看过""不知道"；但**别人认真求助时不许拿这个当借口推掉**——先接住、尽力答，真不会就说不会。')

print('\n'.join(results))
print('人设长度:', len(open(PERSONA, encoding='utf-8').read()))
