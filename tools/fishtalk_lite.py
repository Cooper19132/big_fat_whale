# fishtalk_lite.py —— 只读本地文本，不调模型，不发任何请求
import re

SKELETON = {
    "认账式开场": re.compile(r"这[条句]我(认|记下|接了)|这个我认|我认[，。]|照镜子"),
    # 收紧：只认「最…的是」这种真·八股开场；「最黑的林子」「最难啃的一块」属于正常说话，不算
    "最X的是":    re.compile(r"最[^，。！？\s]{1,8}的是|最(戳|打动|狠|上头|贴)[^，。]{0,3}的是"),
    "不是X是Y":   re.compile(r"不是[^，。！？\s]{1,14}([，,]|\s)+(而)?是"),
    "自贬收尾":   re.compile(r"这毛病我|我也有这|先治我|先拦一道|我这人"),
    "动作括号":   re.compile(r"[（(][^）)]{1,8}(摇|笑|点?头|叹气|歪头|眨眼|哼)[^）)]{0,6}[）)]"),
    "行那我以后": re.compile(r"行[，,]\s*那(以后|就)我"),
    "套话连接":   re.compile(r"换句话说|说到底|归根结底|值得注意的是|与此同时"),
    # ── 2026-11-05 主人追加的三类 ──
    # ① 书面标点（聊天不该出现；# 后跟数字是消息 id，放过）
    "书面标点":   re.compile(r"[“”‘’—：。*；]|#(?![0-9])|\"(?![\s，。])"),
    # ② AI 习惯短句（原样列出主人的禁语表）
    "AI短句":     re.compile(r"这条我认|这流程我熟|说到这|你发现没|说来有趣|"
                             r"我理解你的痛苦|我理解你的焦虑|你不是一个人|"
                             r"按照这个方案|马上去行动|总而言之|值得注意的是|"
                             r"表面看是|归根结底|往深了说|"
                             r"(^|[\s，。])(首先|其次|再次|此外|最后)([，,、]|\s)"),
    # ── 2026-11-11 主人追加：全局文风铁律五组 ──
    "端架子纯表态": re.compile(r"我记下了|这账我记着|我认下来了|我守着|我不拦|你自己掂量|"
                             r"问别人还是问自己|心思都写着脸上|句稳|句重|接得漂亮|"
                             r"拿捏了|我记在心里"),
    "敷衍讲死":   re.compile(r"^(还行|不知道|哦|去吧|行行行|你说得对)[。！？!?\s]*$|"
                             r"你自己搜|懒得找|别问我"),
    "公文装腔":   re.compile(r"并非.{1,8}而是|与其说.{1,10}不如说|既.{1,6}又.{1,6}|"
                             r"不仅.{1,8}更.{1,8}|在那一刻|某种意义上|无声的宣告|空气凝固|"
                             r"不难看出|这意味着|赋能|闭环|抓手|底层逻辑|"
                             r"猛烈|狠狠|瞬间|稳稳"),
    "反问当武器": re.compile(r"问别人还是问自己|什么心思都写着|你自己不觉得|还好意思|"
                             r"你说呢[？?]|凭什么不|难道不是"),
    "客服推销腔": re.compile(r"^好的[\s，,。]|^收到[\s，,。]|马上就好|还需要什么随时说|"
                             r"希望对你有所帮助|一绝|真管用|保证解压|绝对好用|超好用|非常推荐"),
    # ③ 比喻式硬转折：像/如同…随即用所以/这说明/其实推出结论
    "比喻硬转":   re.compile(r"(就像|好比|仿佛|如同|像.{1,10}一样)[^。！？\r\n]{0,30}(所以|所以说|这说明|也就是说|其实|本质上)"),
}


def analyze(text: str):
    """返回 (verdict, families, positions, hits) —— 不打印，便于批量统计。"""
    sents = [s for s in re.split(r"[。！？!?\n]+", text) if s.strip()]
    hits, fams = [], []
    for i, s in enumerate(sents, 1):
        for name, pat in SKELETON.items():
            if pat.search(s):
                hits.append((name, i, s.strip()[:28]))
                fams.append(name)
    fams = list(dict.fromkeys(fams))
    pos = set()
    if hits and hits[0][1] == 1:
        pos.add("开场")
    if hits and hits[-1][1] == len(sents):
        pos.add("收尾")
    if any(1 < h[1] < len(sents) for h in hits):
        pos.add("中段")

    if len(fams) >= 3 or (len(fams) == 2 and len(pos) >= 2):
        verdict = "✗ 先别发"
    elif len(fams) == 2:
        verdict = "△ 可以用，但砍掉一处"
    elif len(fams) == 1:
        verdict = "✓ 过（单处口头禅不算八股）"
    else:
        verdict = "✓ 过"
    return verdict, fams, pos, hits


def check(text: str) -> None:
    verdict, fams, pos, hits = analyze(text)
    print(f"{verdict}｜命中 {len(fams)} 族骨架，覆盖位置：{'/'.join(sorted(pos)) or '无'}")
    for name, i, frag in hits:
        print(f"   句{i} [{name}] {frag}…")
    if len(fams) >= 2:
        print("   建议：只留一处。开场先摆结论 + 中途「不是X是Y」+ 末尾自贬，三件套凑齐就是味。")


if __name__ == "__main__":
    import sys
    check(sys.argv[1] if len(sys.argv) > 1 else input("待检文本："))
