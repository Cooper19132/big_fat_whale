#!/usr/bin/env python3
"""把人设拆成两层：语言层 / 性格层。

为什么拆：
  语言层管「怎么说话」（句式、标点、语气词、回复规则、能力边界），
  性格层管「她是谁」（形象、关系、可爱点、尺度）。
  改规则不会碰到性格，改性格不会碰到规则。

产物：
  persona-语言层.md
  persona-性格层.md
推送时按「性格层 → 语言层」顺序拼接（先知道我是谁，再知道怎么开口）。
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = 'persona-温柔可爱.md'
src = open(SRC, encoding='utf-8').read()

parts = re.split(r'\n(?=## )', src)
blocks = {}
for p in parts[1:]:
    title = p.split('\n', 1)[0].strip()
    blocks[title] = p.rstrip() + '\n'

# 语言层：群聊规则 / 说话方式 / 硬规则 / 能力
LANG_KEYS = ['## 三、群聊规则', '## 四、说话方式',
             '## 五、说话硬规则（只留这几条，其余按第四节）',
             '## 八、能做到 / 做不到']
# 性格层：身份 / 主人 / 可爱点 / 示例 / 尺度
CHAR_KEYS = ['## 一、你是谁', '## 二、你的主人',
             '## 六、可爱的点（自然流露，不刻意）',
             '## 七、回复示例（引用回复由系统自动带上）',
             '## 九、话题尺度与自主分寸']

# 重新编号（各层内部从 1 开始）
def renumber(items, prefix):
    out = []
    for i, (key, body) in enumerate(items, 1):
        body = re.sub(r'^## [一二三四五六七八九十]+、', f'## {prefix}{i}、', body, count=1)
        out.append(body)
    return out

lang = renumber([(k, blocks[k]) for k in LANG_KEYS], '')
char = renumber([(k, blocks[k]) for k in CHAR_KEYS], '')

LANG_HEAD = '''# 语言层：小鲸鱼怎么说话

> 这一层只管「怎么说」，不管「她是谁」。性格、关系、尺度在《性格层》里。
> 两层合起来才是完整人设，推送时按「性格层 → 语言层」拼接。
> 语言层优先：说话句式以本层为准，性格不覆盖本层的硬规则。

'''
CHAR_HEAD = '''# 性格层：小鲸鱼是谁

> 这一层只管「她是谁」——形象、性格、关系、可爱点、话题尺度。
> 「怎么说话」在《语言层》里，本层不重复那些句式规则。

'''

open('persona-语言层.md', 'w', encoding='utf-8').write(LANG_HEAD + '\n'.join(lang))
open('persona-性格层.md', 'w', encoding='utf-8').write(CHAR_HEAD + '\n'.join(char))

for f in ('persona-语言层.md', 'persona-性格层.md'):
    s = open(f, encoding='utf-8').read()
    print(f'  {f}: {len(s):,} 字符 / {s.count(chr(10))} 行')
