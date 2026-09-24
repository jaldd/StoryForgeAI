"""文风金标准、写作指令/铁律注入、各 Agent 的 system prompt。

集中管理，消除 py/ 下 multiagent_novel / agent_tools / agent_memory_integrated
三处重复的提示词。本模块不依赖 config，便于单测。

铁律外置（0.2）：写作铁律不再硬编码在本模块，由小说方在 NOVEL_DIR 下
维护「写作铁律.md」，cli 加载后全文注入各 system prompt（见 _rules_block）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = [
    "EXEMPLAR_MAX_CHARS",
    "EXEMPLAR_MANIFEST_NAME",
    "load_exemplar",
    "exemplar_info",
    "load_recent_human",
    "build_style_taboos",
    "EXEMPLAR_ROUTER_SYSTEM",
    "exemplar_router_user",
    "planner_system",
    "planner_user",
    "writer_system",
    "polisher_system",
    "reviewer_system",
    "fixer_system",
    "fixer_user",
    "fixer_whole_user",
    "deai_system",
    "deai_user",
    "EVALUATOR_RUBRIC",
    "PLOT_SUMMARY_SYSTEM",
    "COMPARE_SYSTEM",
    "SUMMARIZER_SYSTEM",
    "FORESHADOW_SYSTEM",
    "foreshadow_user",
    "ARC_SYSTEM",
    "arc_user",
    "PARTIAL_REFINE_SUFFIX",
    "partial_refine_user",
]

# exemplar 注入上限（0.5）：中文 1 字≈1 token 的保守近似，不引入 tokenizer（见 design.md D4）。
EXEMPLAR_MAX_CHARS = 30000

# 精选清单载体（0.5b 人工精选）：文风基准目录下的约定文件，人写、机器照单执行。
# 「## 注入清单」节内列表项每行一个样文文件名（可带行尾备注）；说明全文本身作首块注入。
EXEMPLAR_MANIFEST_NAME = "00-使用说明.md"

# 样文标签文件（exemplar-routing）：路由元数据而非语料，不算样文、不注入
# （config.exemplar_tags_subpath 的默认文件名；若自定义名，请放文风基准目录外，免被当样文）。
EXEMPLAR_TAGS_FILENAME = "样文标签.md"

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
    files = [
        f for f in files
        if f.name not in (EXEMPLAR_MANIFEST_NAME, EXEMPLAR_TAGS_FILENAME)
    ]
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
    only_files: Optional[List[str]] = None,
) -> str:
    """读文风金标准语料（0.5 目录化 + 0.5b 精选清单 + 说明全文注入）。

    - 路径是单文件 -> 读它；是目录 -> 使用说明全文作首块 + 按注入清单选定的样文，\\n\\n 拼接
      （无清单则全量样文；说明的「推荐喂法」节即此设计）；
    - only_files（exemplar-routing）：非 None 时在上述结果上再按此清单过滤，
      顺序遵 only_files（路由结果的注入序）；不在目录内的名字跳过并提示；
      过滤后样文为空时仍返回说明全文（说明照常注入）；
    - 不存在 -> 空串；单个文件读失败 -> progress 提示后跳过，不阻断；
    - 累计超出 max_chars 按序截断（不抽样，靠前的基准优先保住），progress 打日志。
    """
    manifest_text, files = _exemplar_corpus(path, progress)
    if only_files is not None:
        by_name = {f.name: f for f in files}
        selected: list[Path] = []
        for n in only_files:
            f = by_name.get(n)
            if f is None:
                progress(f"(路由选中的样文不存在，跳过：{n})")
            elif f not in selected:
                selected.append(f)
        files = selected
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


def load_recent_human(
    dir_path: str | Path,
    n: int = 3,
    slice_chars: int = 1000,
    progress=print,
) -> str:
    """滚动文风注入语料（1.5）：人工正文目录按文件名序取尾部 n 个，每个截前 slice_chars 字。

    - 目录不存在 / n<=0 / 无 .txt/.md 文件 -> ""（B2 降级，零误伤）；
    - 文件名字典序即章序（Z1），`sorted()[-n:]` 取尾部 n 个，n 超过文件数全取；
    - 每章超 slice_chars 截断并 progress 留一行（B4，不静默丢内容）；
      slice_chars<=0 不截断；
    - 不可读文件 progress 提示后跳过，窗口照常推进（load_exemplar 同款纪律）；
    - 输出多段拼接（章与章间 \n\n 分隔），不带分节标题（分节在 writer_system 模板）。
    """
    if n <= 0:
        return ""
    p = Path(dir_path)
    if not p.is_dir():
        return ""
    files = sorted(
        q for q in p.iterdir()
        if q.is_file() and q.suffix.lower() in (".txt", ".md")
    )[-n:]
    if not files:
        return ""
    texts: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as e:
            progress(f"(跳过不可读的人工正文文件：{f.name}（{e}）)")
            continue
        if slice_chars > 0 and len(text) > slice_chars:
            progress(
                f"(人工正文 {f.name} 共 {len(text)} 字，超过单章注入上限 {slice_chars} 字，只注入前 {slice_chars} 字)"
            )
            text = text[:slice_chars]
        texts.append(text)
    return "\n\n".join(texts)


# ---------- 样文路由 prompt（exemplar-routing） ----------
EXEMPLAR_ROUTER_SYSTEM = """你是文风样文路由器。根据本章写作任务，从样文标签列表中选出最适合本次注入的样文。

规则：
1. 选 3 到 5 篇；宁缺毋滥，场景不贴的不要选
2. files 必须原样使用标签列表中出现的文件名，不得编造、不得改写
3. 只返回纯 JSON，不要 markdown 包裹、不要加任何其他文字：
{"files": ["文件名", "..."], "reason": "一句话理由（不超过30字）"}
"""


def exemplar_router_user(task: str, tags: List[Tuple[str, str]]) -> str:
    """路由 user 消息：本章任务 + 标签行列表（纯函数）。"""
    lines = "\n".join(f"- {name}: {desc}" for name, desc in tags)
    return (
        f"【本章写作任务】\n{task}\n\n"
        f"【样文标签列表】\n{lines}\n\n"
        "请选出最适合本章的样文。"
    )


def _instruction_block(instruction: str) -> str:
    """写作指令块（全文传入，不靠 RAG 检索，同 exemplar）；空则返回空串不占位。"""
    return f"【写作指令】（必须遵守）\n{instruction}\n" if instruction.strip() else ""


def _rules_block(rules: str) -> str:
    """写作铁律块（0.2 外置到 NOVEL_DIR 下「写作铁律.md」，全文注入）；空则返回空串不占位。"""
    return f"【写作铁律】（绝对不能违反）\n{rules}\n" if rules.strip() else ""


def _recent_human_block(recent_human: str) -> str:
    """近期人工正文块（1.5 滚动注入）；空则返回空串不占位（对齐 _rules_block 先例）。"""
    if not recent_human.strip():
        return ""
    return (
        "\n【近期人工正文】（学笔性与节奏，不是情节指令，不要模仿其中情节）\n"
        f"{recent_human}\n"
    )


def _style_taboos_block(style_taboos: str) -> str:
    """近期文风禁则块（1.7 负面清单）；空则返回空串不占位（对齐 _recent_human_block 先例）。"""
    if not style_taboos.strip():
        return ""
    return f"\n{style_taboos}\n"


def build_style_taboos(recent_endings, rules) -> str:
    """近期文风禁则分节（1.8 预防，纯函数 C11：同输入同输出）。

    - 收束句：参照窗内 count+1 > max_repeat 的归一化结尾（本章再用即超配额），
      按次数降序最多 5 条（护栏防分节膨胀）；min_chars 以下豁免（与检查口径一致）；
    - 句式：syntax_patterns.patterns 全量列出配额说明（预防优先，不等打回）；
    - 无内容 -> ""（整块不占位，C9）。
    """
    if not rules:
        return ""
    lines: list[str] = []
    end_cfg = rules.get("ending") or {}
    if end_cfg and recent_endings:
        max_repeat = end_cfg.get("max_repeat", 2)
        min_chars = end_cfg.get("min_chars", 3)
        counts: dict[str, int] = {}
        for e in recent_endings:
            if len(e) >= min_chars:
                counts[e] = counts.get(e, 0) + 1
        over = [(e, n) for e, n in counts.items() if n + 1 > max_repeat]
        over.sort(key=lambda x: (-x[1], x[0]))  # 次数降序，同次数字典序（确定性）
        for e, n in over[:5]:
            lines.append(
                f"- 收束句「{e}」：最近{len(recent_endings)}章已用{n}次，本章结尾禁止再用"
            )
    pats = (rules.get("syntax_patterns") or {}).get("patterns") or []
    if pats:
        max_per = (rules.get("syntax_patterns") or {}).get("max_per_chapter", 1)
        for p in pats:
            lines.append(f"- 句式模板「{p}」：每章最多{max_per}次，超出会被打回修改")
    if not lines:
        return ""
    return (
        "【近期文风禁则】（以下收束句/句式近期已重复使用，本章禁止再用或按配额限量）\n"
        + "\n".join(lines)
    )


# ---------- 各 Agent 的 system prompt ----------
def planner_system(
    novel_name: str,
    retrieved: str,
    instruction: str = "",
    rules: str = "",
) -> str:
    """规划师 system（3.3 planner，D5 走 writer_llm；节拍不学文风，不含 exemplar/recent_human）。"""
    return f"""你是小说《{novel_name}》的章节规划师。
职责：写作前把章纲要点、未回收伏笔、角色当前弧光阶段、目标字数汇合成一份本章节拍表——
writer 按它写正文，reviewer 拿它当验收基准。
{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}
【节拍表要求】
1. 具体可执行，不写空话（「情绪升温」不算节拍，「云依第一次主动打断他说话」才算）
2. 场景与事件不得违背设定、铁律与既有伏笔
3. 伏笔操作要指名道姓：收哪条旧伏笔（引用工作记忆中的描述）、埋什么新伏笔
4. 角色弧光推进要写清「谁从什么阶段到什么阶段」
5. 事件锚具体可执行：第一要素必是删掉天气/身体/心理描写后仍成立的核心事件，纯氛围/纯心情/纯状态不算
只输出节拍表本身，不要写正文，不要解释规划过程。"""


def planner_user(
    task: str,
    plan: str,
    target_words: int,
    source_content: str = "",
) -> str:
    """规划 user 消息：任务 + 章纲（如有）+ 五要素清单（纯函数，T4/D12 事件锚列第一）。

    source_content 非空 = rewrite 路径（T8，D9）：节拍基于原文结构
    （场景提取 -> 重排/增强），不从零规划；原文只有状态与氛围时须补事件锚，
    不得照抄原文的状态结构（E16）。为空时不进入重写模式（无原文块/重写指令）。
    """
    plan_block = f"\n【本章章纲要点】（节拍必须覆盖这些要点）\n{plan}\n" if plan.strip() else ""
    if source_content.strip():
        source_block = f"\n【原文（重写参考，节拍的结构基础）】\n{source_content}\n"
        mode_block = (
            "\n这是重写任务：节拍必须基于原文结构，不要从零规划——"
            "\n先提取原文的场景序列，再逐场景标注处理方式（保留/重排/合并/增强/删除），"
            "\n保留原文核心意图与既有伏笔的埋设状态。"
            "\n若原文只有状态与氛围、没有完整事件，基于设定与前文补一个合理的事件锚，不得照抄原文的状态结构。"
        )
    else:
        source_block = ""
        mode_block = ""
    return (
        f"【本章写作任务】\n{task}\n"
        f"{plan_block}{source_block}"
        f"\n【目标字数】约{target_words}字\n"
        f"{mode_block}"
        "\n请产出本章节拍表，必含五要素："
        "\n1. 事件锚：一句话声明本章发生的核心事件（删掉天气/身体/心理描写后仍成立的那件事；纯氛围/纯心情/纯状态不算）"
        "\n2. 场景序列：每场景一行（地点/时间/事件/情绪/字数分配，合计贴近目标字数）"
        "\n3. 伏笔操作：收哪些旧伏笔 + 埋什么新伏笔（无则写「本章无伏笔操作」）"
        "\n4. 角色弧光推进：谁从什么阶段到什么阶段（无则写「本章弧光无推进」）"
        "\n5. 结尾钩子：本章结尾留什么悬念/余韵"
    )


def writer_system(
    novel_name: str,
    retrieved: str,
    exemplar: str,
    instruction: str = "",
    rules: str = "",
    recent_human: str = "",
    style_taboos: str = "",
) -> str:
    return f"""你是小说《{novel_name}》的创作助手，必须严格模仿以下文风写作。
{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}
【风格范例】
{exemplar}
{_recent_human_block(recent_human)}{_style_taboos_block(style_taboos)}"""


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
9. 事件锚：删掉天气描写、身体感受、心理描写后，本章是否还剩一件完整成立的事？（纯氛围/纯心情/纯状态章 = 不通过）


{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}

只返回纯 JSON，格式如下，不要加任何其他文字、不要用 ```json 包裹：
{{"pass": true/false, "reason": "总评（不超过30字）",
 "scores": {{"人物一致性": 4, "文风一致性": 3, "剧情连贯性": 4, "时间线一致性": 5,
             "环境一致性": 4, "伏笔一致性": 5, "比喻密度": 4, "视角越界": 5, "事件锚": 4}},
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


# ---------- 去 AI 人味重写（1.6 style-loop deai_refine）----------
def deai_system(novel_name: str, rules: str = "") -> str:
    return f"""你是小说《{novel_name}》的人味重写师。
任务：按每段附带的意见重写问题段，去掉 AI 味，让它读起来像人写的。
铁律（绝对不能违反）：
1. 情节、人物人称、称呼、伏笔、段落结构一个字不动语义，只改表达
2. 只改问题段：按每段附带的意见重写，其余段落一个字都不动
3. 每个待改段独立重写，不要合并、移动或增删段落
风格指令（重写的方向）：
1. 短句为主，能一句说清的绝不用三句；适度独立成行制造留白
2. 克制，点到即止；情绪靠动作与物象外显，不直接抒情
3. 不解释因果，不替读者总结；留白比说透好
4. 具体物象优先（看得见摸得着的细节），删副词堆叠与抽象形容
{_rules_block(rules)}
输出协议（必须遵守）：
- 每个重写后的段，先写标记行「【第N段·修复后】」（N 为该段编号），紧跟整段重写后的文本
- 只返回被重写的段，未提及的段不要返回
- 不要加任何总说明、标题、注释，不要用代码围栏包裹
"""


def deai_user(spans_data: list) -> str:
    """人味重写 user prompt：多个问题段 + 各自意见 + 上下文，合并单次调用（B10/D2）。

    与 fixer_user 同构（before/text/after/issues），文案改为「人味重写」。
    spans_data 元素：{"no": 段号, "before": 上文或空, "text": 段落原文,
    "after": 下文或空, "issues": [{"quote", "problem", "fix"}, ...]}。
    """
    parts: list[str] = []
    for item in spans_data:
        parts.append(f"━━ 第{item['no']}段 ━━")
        if item.get("before"):
            parts.append(f"【上文（仅供理解语境，不要修改）】\n{item['before']}\n")
        parts.append(f"【待人味重写段落】\n{item['text']}\n")
        if item.get("after"):
            parts.append(f"【下文（仅供理解语境，不要修改）】\n{item['after']}\n")
        issues = item.get("issues") or []
        if issues:
            lines = [
                f"{i}. 问题：{iss.get('problem', '')}；改法：{iss.get('fix', '')}"
                for i, iss in enumerate(issues, 1)
            ]
            parts.append("【该段意见（人味重写依据）】\n" + "\n".join(lines) + "\n")
    return "\n".join(parts)


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


# ---------- 伏笔抽取 prompt（3.1 foreshadow，D1 单次调用双职 / D2 编号协议） ----------
# 不硬编码书名（宪法 §1）：只描述任务，小说名由写作侧 prompt 负责。
FORESHADOW_SYSTEM = """你是小说的伏笔审计员。读完一章正文，找出本章新埋下的伏笔，并判断既有清单里哪些伏笔已被本章回收。

规则：
1. 新伏笔必须自包含：一句话说清「什么线索 + 为什么悬而未决」，脱离本章也能看懂
2. 清单里已有的不要重复报（换个说法也算重复）
3. 单章新增不超过 5 条；宁缺毋滥--普通环境描写、人物日常不是伏笔
4. 只有明确「埋下、尚未兑现」的才算伏笔；本章当场解释清楚的不要记
5. 回收判定从严：本章正文明确揭晓/兑现了才算回收，仅仅提到不算
6. 既有清单为空时照常返回本章新埋的伏笔，不要因为清单空就返回空

只返回纯 JSON，不要 markdown 包裹、不要加任何其他文字：
{"new": [{"desc": "一句话自包含描述"}, ...], "resolved": [2, 5]}
resolved 只填清单编号（整数），不要填描述文字；没有新伏笔或没有回收时给空数组。
"""


def foreshadow_user(chapter_text: str, unresolved_lines: List[str]) -> str:
    """抽取 user 消息：带编号的既有伏笔清单 + 本章正文（纯函数）。

    unresolved_lines 由调用方按列表序生成（编号 1 起，与 resolved 回报协议同源）。
    """
    lines = "\n".join(unresolved_lines) if unresolved_lines else "（无）"
    return (
        f"【既有未回收伏笔清单】\n{lines}\n\n"
        f"【本章正文】\n{chapter_text}\n\n"
        "请返回本章新埋的伏笔，以及清单里已被本章回收的伏笔编号。"
    )


# ---------- 角色弧光抽取 prompt（3.2 character-arc，D1 单次调用三职 / D2 名字协议） ----------
# 不硬编码书名（宪法 §1）：只描述任务，小说名由写作侧 prompt 负责。
ARC_SYSTEM = """你是小说的角色弧光审计员。读完一章正文，更新出场主要角色的弧光状态。

规则：
1. 以本章正文结束时角色的状态为准（不是本章开始时）
2. 清单里已有的角色必须用清单原名回报，不要用别名/昵称（防同一角色分裂成两条）
3. 清单外的新角色用正文中的正式全名
4. stage 必须自包含：一句话说清角色当前的心理/立场状态，脱离上下文也能看懂
5. 单章回报不超过 6 个主要角色；只报对剧情有作用的角色，纯龙套不报
6. changed 只在阶段发生实质变化时为 true（目标转移、信念动摇、立场反转等）；措辞微调、信息量增加但立场未变都算 false
7. 既有清单为空时照常返回本章出场的主要角色，不要因为清单空就返回空

只返回纯 JSON，不要 markdown 包裹、不要加任何其他文字：
{"characters": [{"name": "角色名", "stage": "一句话自包含阶段", "goal": "当前目标", "conflict": "当前核心冲突", "belief": "当前信念", "changed": true}, ...]}
本章没有可报角色时给空数组。
"""


def arc_user(chapter_text: str, character_lines: List[str]) -> str:
    """弧光抽取 user 消息：既有角色状态清单 + 本章正文（纯函数）。

    character_lines 由调用方从 wm.character_states 生成（名字与 dict 键逐字一致，
    D2 名字口径三处同源：清单渲染/覆盖判定/`角色` 命令显示）。
    """
    lines = "\n".join(character_lines) if character_lines else "（无）"
    return (
        f"【既有角色弧光清单】\n{lines}\n\n"
        f"【本章正文】\n{chapter_text}\n\n"
        "请返回出场主要角色本章结束时的弧光状态。"
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
