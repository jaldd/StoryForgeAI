"""文风金标准、写作指令/铁律注入、各 Agent 的 system prompt。

集中管理，消除 py/ 下 multiagent_novel / agent_tools / agent_memory_integrated
三处重复的提示词。本模块不依赖 config，便于单测。

铁律外置（0.2）：写作铁律不再硬编码在本模块，由小说方在 NOVEL_DIR 下
维护「写作铁律.md」，cli 加载后全文注入各 system prompt（见 _rules_block）。
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "EXEMPLAR_MAX_CHARS",
    "EXEMPLAR_MANIFEST_NAME",
    "load_exemplar",
    "exemplar_info",
    "writer_system",
    "polisher_system",
    "reviewer_system",
    "fixer_system",
    "fixer_user",
    "fixer_whole_user",
    "EVALUATOR_RUBRIC",
    "PLOT_SUMMARY_SYSTEM",
    "COMPARE_SYSTEM",
    "SUMMARIZER_SYSTEM",
    "PARTIAL_REFINE_SUFFIX",
    "partial_refine_user",
]

# exemplar 注入上限（0.5）：中文 1 字≈1 token 的保守近似，不引入 tokenizer（见 design.md D4）。
EXEMPLAR_MAX_CHARS = 30000

# 精选清单载体（0.5b 人工精选）：文风基准目录下的约定文件，人写、机器照单执行。
# 「## 注入清单」节内列表项每行一个样文文件名（可带行尾备注）；说明全文本身作首块注入。
EXEMPLAR_MANIFEST_NAME = "00-使用说明.md"

# 清单行 -> 文件名：须为列表项（- 或 * 开头），取文件名 token（截到空白/全半角括号/冒号逗号）
_MANIFEST_LINE_RE = re.compile(r"^[-*]\s+([^\s（()：:，,]+)")


def _parse_manifest_names(text: str) -> list[str]:
    """从使用说明文本解析注入清单文件名（按书写顺序）；无「注入清单」节返回空。"""
    names: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_section = "注入清单" in stripped
            continue
        if not in_section:
            continue
        m = _MANIFEST_LINE_RE.match(stripped)
        if m:
            names.append(m.group(1))
    return names


def _exemplar_corpus(path: str | Path, progress=print) -> tuple[str | None, list[Path]]:
    """目录级语料：(使用说明全文 or None, 样文文件清单[经精选清单过滤，清单序即注入序])。

    - 单文件路径返回 (None, [它自己])；
    - 目录：无说明文件 -> (None, 全量样文)；「## 注入清单」节缺失/全落空 -> 说明全文 + 全量样文；
    - 说明文件本身是喂法指导（见其「推荐喂法」节），作为语料首块注入，不算样文。
    """
    files = _exemplar_files(path)
    p = Path(path)
    if not p.is_dir():
        return None, files
    files = [f for f in files if f.name != EXEMPLAR_MANIFEST_NAME]
    try:
        manifest_text = (p / EXEMPLAR_MANIFEST_NAME).read_text(encoding="utf-8")
    except OSError:
        return None, files
    names = _parse_manifest_names(manifest_text)
    if not names:
        return manifest_text, files
    by_name = {f.name: f for f in files}
    selected: list[Path] = []
    for n in names:
        f = by_name.get(n)
        if f is None:
            progress(f"(注入清单引用的语料不存在，跳过：{n})")
        elif f not in selected:
            selected.append(f)
    return manifest_text, selected or files


def _exemplar_files(path: str | Path) -> list[Path]:
    """exemplar 路径 -> 语料文件清单：单文件就它自己；目录取排序后的 *.txt/*.md。"""
    p = Path(path)
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(
            q for q in p.iterdir()
            if q.is_file() and q.suffix.lower() in (".txt", ".md")
        )
    return []


def load_exemplar(
    path: str | Path,
    max_chars: int = EXEMPLAR_MAX_CHARS,
    progress=print,
) -> str:
    """读文风金标准语料（0.5 目录化 + 0.5b 精选清单 + 说明全文注入）。

    - 路径是单文件 -> 读它；是目录 -> 使用说明全文作首块 + 按注入清单选定的样文，\\n\\n 拼接
      （无清单则全量样文；说明的「推荐喂法」节即此设计）；
    - 不存在 -> 空串；单个文件读失败 -> progress 提示后跳过，不阻断；
    - 累计超出 max_chars 按序截断（不抽样，靠前的基准优先保住），progress 打日志。
    """
    manifest_text, files = _exemplar_corpus(path, progress)
    if not files and manifest_text is None:
        return ""
    texts: list[str] = []
    if manifest_text is not None:
        texts.append(manifest_text)  # 使用说明优先：模型先知道学什么/不学什么
    for f in files:
        try:
            texts.append(f.read_text(encoding="utf-8"))
        except OSError as e:
            progress(f"(跳过不可读的文风基准文件：{f.name}（{e}）)")
    full = "\n\n".join(texts)
    if len(full) <= max_chars:
        return full
    # 超限：按文件序装到满为止（分隔符计入预算）
    parts: list[str] = []
    kept = 0
    for t in texts:
        used = sum(len(p) for p in parts) + 2 * len(parts)
        budget = max_chars - used
        if len(t) <= budget:
            parts.append(t)
            kept += 1
        else:
            if budget > 0:
                parts.append(t[:budget])
            break
    result = "\n\n".join(parts)[:max_chars]
    progress(
        f"⚠️ 文风基准语料共 {len(full)} 字，超过注入上限 {max_chars} 字，"
        f"按序保留前 {kept} 个文件（共 {len(texts)} 个），其余截断不注入"
    )
    return result


def exemplar_info(path: str | Path) -> tuple[int, int]:
    """文风基准有效语料的 (文件数, 总字数)，供状态命令展示。

    与 load_exemplar 同源（_exemplar_corpus），字数含使用说明本身（它也注入）。
    不存在返回 (0, 0)。
    """
    manifest_text, files = _exemplar_corpus(path, progress=lambda *_a, **_kw: None)
    total = len(manifest_text) if manifest_text is not None else 0
    for f in files:
        try:
            total += len(f.read_text(encoding="utf-8"))
        except OSError:
            continue
    return len(files), total


def _instruction_block(instruction: str) -> str:
    """写作指令块（全文传入，不靠 RAG 检索，同 exemplar）；空则返回空串不占位。"""
    return f"【写作指令】（必须遵守）\n{instruction}\n" if instruction.strip() else ""


def _rules_block(rules: str) -> str:
    """写作铁律块（0.2 外置到 NOVEL_DIR 下「写作铁律.md」，全文注入）；空则返回空串不占位。"""
    return f"【写作铁律】（绝对不能违反）\n{rules}\n" if rules.strip() else ""


# ---------- 各 Agent 的 system prompt ----------
def writer_system(novel_name: str, retrieved: str, exemplar: str, instruction: str = "", rules: str = "") -> str:
    return f"""你是小说《{novel_name}》的创作助手，必须严格模仿以下文风写作。
{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}
【风格范例】
{exemplar}
"""


def polisher_system(novel_name: str, retrieved: str, instruction: str = "", target_words: int = 1500, rules: str = "") -> str:
    return f"""你是小说《{novel_name}》的文字润色师。
任务：对下面的初稿做润色，让文字更流畅、有文采、节奏更好。
如果初稿太短或内容不够，可以适当扩写补充细节，但不要改变核心情节。
目标篇幅：约{target_words}字。初稿明显不足时扩写补充细节；已达标则不必硬凑。
铁律（绝对不能违反）：
1. 只优化文字表达，严禁改动人物称呼与人物设定
2. 严禁改动剧情、伏笔与既有意象的隐喻含义
3. 初稿里守住的设定，润色后必须原样保留
{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}
只返回润色后的正文，不要加任何标题、说明、注释。不要写"润色后正文"，不要写"润色说明"，直接返回正文内容。
"""


def reviewer_system(novel_name: str, retrieved: str, instruction: str = "", rules: str = "") -> str:
    return f"""你是小说《{novel_name}》的审稿编辑。
任务：审查以下稿件，判断是否合格。
审查维度：
1. 人物一致性：是否符合设定（人物称呼、人设等）
2. 文风一致性：是否短句为主、克制留白、不解释因果
3. 剧情连贯性：逻辑是否自洽
4. 时间线一致性：时间/季节/昼夜是否合理
5. 环境一致性：场景/意象是否连贯
6. 伏笔一致性：有没有矛盾或遗漏
7. 比喻密度：像/仿佛/宛如类标记词是否密集堆叠（5=克制自然，1=滥用）
8. 视角越界：叙述是否越出当前视角人物可知的范围（5=无越界）


{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}

只返回纯 JSON，格式如下，不要加任何其他文字、不要用 ```json 包裹：
{{"pass": true/false, "reason": "总评（不超过30字）",
 "scores": {{"人物一致性": 4, "文风一致性": 3, "剧情连贯性": 4, "时间线一致性": 5,
             "环境一致性": 4, "伏笔一致性": 5, "比喻密度": 4, "视角越界": 5}},
 "issues": [{{"quote": "原句逐字引用", "problem": "维度名：问题描述", "fix": "具体改法"}}]}}
不通过时必须把所有问题一次性列全，每个问题引用原句并给出改法。通过时 issues 留空数组。
"""


# ---------- 修稿（1.1 quality-gate fixer）----------
def fixer_system(novel_name: str, rules: str = "") -> str:
    return f"""你是小说《{novel_name}》的修稿师。
任务：只修复明确列出的问题，其余部分保持原样。
铁律（绝对不能违反）：
1. 只改问题处：按每段附带的意见修改，其余表达一个字都不动
2. 严禁改动情节、人物人称、称呼与伏笔
3. 每个待修段独立修复，不要合并、移动或增删段落
{_rules_block(rules)}
输出协议（必须遵守）：
- 每个修复后的段，先写标记行「【第N段·修复后】」（N 为该段编号），紧跟整段修复后的文本
- 只返回被修复的段，未提及的段不要返回
- 不要加任何总说明、标题、注释，不要用代码围栏包裹
"""


def fixer_user(spans_data: list) -> str:
    """修稿 user prompt：多个问题段 + 各自意见 + 上下文，合并单次调用（A11）。

    spans_data 元素：{"no": 段号, "before": 上文或空, "text": 段落原文,
    "after": 下文或空, "issues": [{"quote", "problem", "fix"}, ...]}。
    """
    parts: list[str] = []
    for item in spans_data:
        parts.append(f"━━ 第{item['no']}段 ━━")
        if item.get("before"):
            parts.append(f"【上文（仅供理解语境，不要修改）】\n{item['before']}\n")
        parts.append(f"【待修段落】\n{item['text']}\n")
        if item.get("after"):
            parts.append(f"【下文（仅供理解语境，不要修改）】\n{item['after']}\n")
        issues = item.get("issues") or []
        if issues:
            lines = [
                f"{i}. 问题：{iss.get('problem', '')}；改法：{iss.get('fix', '')}"
                for i, iss in enumerate(issues, 1)
            ]
            parts.append("【该段意见（逐条修复）】\n" + "\n".join(lines) + "\n")
    return "\n".join(parts)


def fixer_whole_user(text: str, issues: list) -> str:
    """整文修复降级的 user prompt（A12）：原稿全文 + 全部意见，保内容只改问题处。"""
    lines = [
        f"{i}. 问题：{iss.get('problem', '')}；改法：{iss.get('fix', '')}"
        for i, iss in enumerate(issues or [], 1)
    ]
    advice = "\n".join(lines)
    return (
        "以下稿件的问题无法精确定位到段落，请整文修复：保留内容，只改问题处，"
        "情节、人称、称呼与其余表达都不要动。\n\n"
        f"【意见清单（逐条修复）】\n{advice}\n\n"
        f"【原稿全文】\n{text}"
    )


# ---------- 评测 / 摘要 prompt ----------
EVALUATOR_RUBRIC = """你是小说评稿评委。请从以下维度给稿件打分，每维 1-5 分（5=最好）：
1. 连贯性：剧情/逻辑是否自洽，有无突兀跳跃
2. 人物一致性：是否符合设定
3. 剧情合理性：情感与行为动机是否合理、不悬浮
4. 标题评分：章节标题是否贴切、有味道
理由不超过100字，简洁说明即可。只返回 JSON，不要 markdown 包裹、不要加任何其他文字：
{"连贯性": <分>, "人物一致性": <分>, "剧情合理性": <分>, "标题评分": <分>, "理由": "<总评>", "建议标题": "<更好的标题，没有就写保留>", "标题理由": "<一句话说明>"}"""


SUMMARIZER_SYSTEM = "把下面的对话压成 3 句话摘要，只留对小说重要的信息。"

PLOT_SUMMARY_SYSTEM = (
    "把下面的小说章节压成 1-2 句话剧情摘要，只记关键情节与情绪落点，不要评价、不要复述全文。"
)


# ---------- 版本对比 prompt（0.8 从 cli._is_better 收编） ----------
COMPARE_SYSTEM = (
    "你是小说编辑。对比两段文字，判断第二段（润色后）是否比第一段（原文）更好。"
    "只返回纯 JSON：{\"better\": true/false}"
)


# ---------- 局部精修（partial-refine）prompt ----------
# 追加在 polisher_system 之后：只润色片段本身，上下文仅供理解。
# 不复制 polisher 的铁律文案（铁律外迁重构时此处零成本跟随，见 design.md §5.2）。
PARTIAL_REFINE_SUFFIX = """【局部精修特别说明】
接下来只对一个片段做局部润色：
1. 只润色给出的片段，情节不动，只改文字表达
2. 只返回改写后的片段本身，不要补写上下文，不要返回整章
3. 不要加任何标题、说明、注释，不要用代码围栏包裹返回结果
4. 上文、下文仅供理解语境，不要改写它们，也不要把它们包含在返回结果里
"""


def partial_refine_user(before: str, selection: str, after: str) -> str:
    """局部精修的 user prompt：三段式标记（上文/待润色片段/下文）。

    before/after 为空串时对应占位段不出现（文件首段无上文、末段无下文）。
    """
    parts = []
    if before:
        parts.append(f"【上文（勿改写，勿返回）】\n{before}")
    parts.append(f"【待润色片段（只返回这段的改写结果）】\n{selection}")
    if after:
        parts.append(f"【下文（勿改写，勿返回）】\n{after}")
    return "\n\n".join(parts)
