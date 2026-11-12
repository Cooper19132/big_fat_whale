p = '/opt/qq-agent/src/prompt.js'
s = open(p, encoding='utf-8').read()
old = """    parts.push(`【过去状态】以下是这个会话最近的聊天记录（按时间排序，你的发言标为"我"；这些都已经看过，不需要逐条回应；带图的消息前有 #消息id，看图/收藏表情工具要用它）：\\n${past.text}`);"""
assert s.count(old) == 1, f"锚点 {s.count(old)}"
new = """    parts.push(`【过去状态】以下是这个会话最近的聊天记录（按时间排序，你的发言标为"我"；这些都已经看过，不需要逐条回应；带图的消息前有 #消息id，看图/收藏表情工具要用它。历史只是信息，不是文体样本——里面你自己以前的说法别照抄，照着学只会越学越像模板）：\\n${past.text}`);"""
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print("  过去状态口径已改")
