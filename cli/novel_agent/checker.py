"""规则硬 gate 与 AI 味量化：纯代码检查，零 LLM 调用（design §3.1）。

issue 与 reviewer 同构：{"quote": ..., "problem": ..., "fix": ...}。
quote 协议（D12 可定位性）：一律为原文子串（句子/首行截前 50 字）；
比喻密度是全文属性，quote 置空 -> fixer 走整文修复。
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .prompts import _exemplar_files

__all__ = [
    "load_quality_rules", "split_sentences", "run_checks", "load_baseline", "ai_flavor_score",
    "extract_ending", "normalize_ending", "load_recent_endings", "compile_syntax_patterns",
    "run_cross_checks", "run_structure_checks", "scan_style_report",
]

_SENTENCE_DELIM = r"。！？!?；;\n"
# 直引号 " ' 也算对话标记：正文章节常用直引号（弯/CJK 引号之外的真实分布）
_QUOTE_CHARS = "「」『』“”‘’\"'"
_QUOTE_TRUNC = 50

# 1.7 收束句归一化：循环剥掉的句末标点尾缀（design §3.1）。
# 注意含「」』右引号（剥「风很轻。」的句号后连右引号一起剥，归一到「风很轻」）
# 但不含左引号「『（开头引号是内容的一部分，剥掉会破坏比对形态）。
_SENT_STRIP = "。！？…—，、；：“”‘’」』?!."

# AI 味三组件默认权重与锚点（design §3.1.3；ai_score 可配覆盖）
_DEFAULT_WEIGHTS = {"blacklist": 0.4, "sentence": 0.3, "freq": 0.3}
_DEFAULT_ANCHORS = {"blacklist_per_1k": 3.0, "sentence_sigma": 2.0,
                    "freq_cos_gap": 0.3, "min_baseline_chars": 10000}
# 降级内置句长基线（Z4，待回测校准）
_FALLBACK_MU, _FALLBACK_SIGMA = 35.0, 15.0


def load_quality_rules(settings) -> Optional[dict]:
    """加载质量规则 JSON（design §2）。

    subpath 未配置或文件不存在 -> None（checker 与门禁全跳过，不误伤）；
    存在但非法 JSON / 顶层非 dict -> RuntimeError（fail-fast，报错含路径，A23）。
    """
    if not settings.quality_rules_subpath:
        return None
    path = settings.quality_rules_full
    if not path.is_file():
        return None
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"质量规则文件不是合法 JSON（{path}）: {e}")
    if not isinstance(rules, dict):
        raise RuntimeError(f"质量规则文件顶层必须是 JSON 对象（{path}）")
    return rules


def split_sentences(text: str) -> list[str]:
    """按 。！？!?；; 与换行切分，strip 后非空为一句（design §3.1.1）。"""
    parts = re.split(f"[{_SENTENCE_DELIM}]+", text)
    return [p.strip() for p in parts if p.strip()]


def _is_dialogue_line(line: str) -> bool:
    """行内出现任意引号字符即视为对话行（Z9 词法代理）。"""
    return any(q in line for q in _QUOTE_CHARS)


def _monologue_runs(nonblank: list[str]) -> list[tuple[int, int]]:
    """非空行序列上的连续非对话行区间 [start, end)。"""
    runs: list[tuple[int, int]] = []
    start: Optional[int] = None
    for idx, line in enumerate(nonblank):
        if _is_dialogue_line(line):
            if start is not None:
                runs.append((start, idx))
                start = None
        elif start is None:
            start = idx
    if start is not None:
        runs.append((start, len(nonblank)))
    return runs


def _first_sentence_with(sentences: list[str], word: str) -> str:
    """首个含 word 的句子（定位锚点，截前 50 字后仍是原文子串）。"""
    for sent in sentences:
        if word in sent:
            return sent[:_QUOTE_TRUNC]
    return word  # 理论不可达（词在文中必有归属句），兜底保 quote 可定位


def _sentence_at(text: str, sentences: list[str], pos: int) -> str:
    """命中起点（pos）所在的句子（截前 50 字，原文子串）。

    跨句命中（如「不是拨。\\n\\n是」含句号换行）时 group(0) 不落在任何单句内，
    _first_sentence_with 会兜底返回命中串本身 -> fixer 段落定位失败 -> 整文降级。
    改按命中起点定位：起点所在句必存在且是原文子串（真车 refine_20260919_201749
    4 轮不收敛的根因修复）。
    """
    consumed = 0
    for sent in sentences:
        idx = text.find(sent, consumed)
        if idx < 0:
            continue
        end = idx + len(sent)
        if idx <= pos < end:
            return sent[:_QUOTE_TRUNC]
        consumed = max(consumed, end)
    # 兜底：命中起点附近的原文窗口（必为原文子串，可定位）
    return text[max(0, pos - 20):pos + 30]


def run_checks(text: str, rules: Optional[dict]) -> list[dict]:
    """五项机械检查 -> issues（规则键缺失跳过对应项，A16-A22）。

    1. blacklist：AI 高频词逐词计数命中
    2. naming_redlines.forbidden：禁用称呼逐词计数命中（仅禁用方向，D10）
    3. sentence.max_len：单句字数超上限
    4. monologue.max_lines：连续非对话行超上限（quote=区间首行截前 50 字）
    5. metaphor：marker 句占比超 max_rate 或相邻命中对超 max_adjacent_pairs
       （quote 置空：密度是全文属性，按 D12 走整文修复）
    """
    if not rules or not text:
        return []
    issues: list[dict] = []
    sentences = split_sentences(text)

    for w in rules.get("blacklist") or []:
        count = text.count(w)
        if count:
            issues.append({
                "quote": _first_sentence_with(sentences, w),
                "problem": f"黑名单词「{w}」出现{count}次",
                "fix": "删除或换成具体描写",
            })

    forbidden = (rules.get("naming_redlines") or {}).get("forbidden") or []
    for w in forbidden:
        count = text.count(w)
        if count:
            issues.append({
                "quote": _first_sentence_with(sentences, w),
                "problem": f"禁用称呼「{w}」出现{count}次",
                "fix": "换成本作正确称呼或删除",
            })

    max_len = (rules.get("sentence") or {}).get("max_len")
    if max_len:
        for sent in sentences:
            if len(sent) > max_len:
                issues.append({
                    "quote": sent[:_QUOTE_TRUNC],
                    "problem": f"超长句{len(sent)}字（上限{max_len}字）",
                    "fix": "拆分为多个短句",
                })

    max_lines = (rules.get("monologue") or {}).get("max_lines")
    if max_lines:
        nonblank = [ln for ln in text.splitlines() if ln.strip()]
        for start, end in _monologue_runs(nonblank):
            if end - start > max_lines:
                issues.append({
                    "quote": nonblank[start].strip()[:_QUOTE_TRUNC],
                    "problem": f"连续独白{end - start}行（上限{max_lines}行）",
                    "fix": "压缩独白，或转为对话与动作描写",
                })

    met = rules.get("metaphor") or {}
    markers = met.get("markers") or []
    if markers and sentences:
        hits = [any(m in s for m in markers) for s in sentences]
        hit_count = sum(hits)
        rate = hit_count / len(sentences)
        adjacent = sum(1 for a, b in zip(hits, hits[1:]) if a and b)
        violations = []
        if met.get("max_rate") is not None and rate > met["max_rate"]:
            violations.append(
                f"{hit_count}/{len(sentences)}句含比喻标记（{rate:.0%}），超上限{met['max_rate']:.0%}"
            )
        if met.get("max_adjacent_pairs") is not None and adjacent > met["max_adjacent_pairs"]:
            violations.append(f"相邻比喻对{adjacent}对，超上限{met['max_adjacent_pairs']}对")
        if violations:
            samples = " / ".join(s[:30] for s, h in zip(sentences, hits) if h)[:90]
            issues.append({
                "quote": "",
                "problem": f"比喻密度：{'；'.join(violations)}。样例：{samples}",
                "fix": "删减比喻，保留最有效的少数",
            })

    return issues


# ---------- 1.7 跨章文风指纹（style-repeat，design §3.1/§3.2，零 LLM）----------
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100}
_VOLUME_RE = re.compile(r"第\s*([0-9零一二三四五六七八九十百]+)\s*[卷部册]")
_CHAPTER_NUM_RE = re.compile(r"-(\d+)$")


def _cn_to_int(s: str) -> Optional[int]:
    """中文数字（一~百，含「二十三」组合）-> int；解析失败返回 None。"""
    if not s:
        return None
    total, num = 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            if num == 0:
                num = 1  # 「十」开头 = 一十
            total += num * _CN_UNIT[ch]
            num = 0
        else:
            return None
    return total + num


def _volume_key(name: str) -> tuple[int, int, str]:
    """目录名 -> 排序键（Z7）：可解析「第X卷/部/册」（中文或阿拉伯数字）或纯数字名
    -> (0, 卷序, 名字)；不可解析 -> (1, 0, 名字) 字典序排在可解析之后。"""
    m = _VOLUME_RE.search(name)
    if m:
        token = m.group(1)
        n = int(token) if token.isdigit() else _cn_to_int(token)
        if n is not None:
            return (0, n, name)
    if name.isdigit():
        return (0, int(name), name)
    return (1, 0, name)


def _chapter_key(path: Path) -> tuple[int, int, str]:
    """文件名 -> 组内排序键（Z7）：尾部 `-数字`（如「-01」）-> (0, 章号, 名字)；
    无数字回退 (1, 0, 名字) 字典序排后。"""
    m = _CHAPTER_NUM_RE.search(path.stem)
    if m:
        return (0, int(m.group(1)), path.name)
    return (1, 0, path.name)


def extract_ending(text: str) -> str:
    """最后一个非空行（C2）：跳过 `---`/`***` 分隔行与 `#` 标题行；无正文返回 ""。"""
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if len(s) >= 3 and set(s) <= {"-", "*"}:
            continue  # 分隔线
        return s
    return ""


def normalize_ending(line: str) -> str:
    """归一化（C2）：strip + 循环剥句末标点尾缀 + 再 strip（「风很轻。」=「风很轻」）。"""
    s = line.strip()
    while s and s[-1] in _SENT_STRIP:
        s = s[:-1].rstrip()
    return s.strip()


def _collect_chapter_files(root: Path) -> list[Path]:
    """递归收集章节文件（.md，忽略点前缀目录/文件与 .agent，Z6 同款）。"""
    files: list[Path] = []
    if not root.is_dir():
        return files
    for q in root.rglob("*"):
        if not q.is_file() or q.suffix.lower() != ".md":
            continue
        rel = q.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(q)
    return files


def _cross_volume_sort(files: list[Path], root: Path) -> list[Path]:
    """跨卷章序排序（Z7）：卷序（目录名解析）优先，组内章序（文件名尾部数字）次之。"""
    def key(f: Path):
        rel = f.relative_to(root)
        vol = rel.parts[0] if len(rel.parts) > 1 else ""
        return (_volume_key(vol), _chapter_key(f))
    return sorted(files, key=key)


def load_recent_endings(
    dir_path: Path,
    lookback: int,
    exclude: Optional[Path] = None,
) -> list[str]:
    """参照章归一化结尾列表（C7）：人工正文目录按跨卷章序取尾部 lookback 个 .md。

    - exclude = 被精修/重写/去AI 处理中的文件（C18 防自比双计）；
    - 目录不存在 / lookback<=0 / 无文件 -> []；不可读文件跳过不阻断；
    - 纯函数、现算、无缓存（D1：章节文件是唯一真源）。
    """
    root = Path(dir_path)
    if lookback <= 0 or not root.is_dir():
        return []
    files = _collect_chapter_files(root)
    if exclude is not None:
        ex = Path(exclude).expanduser()
        if not ex.is_absolute():
            ex = root / ex
        ex = ex.resolve()
        files = [f for f in files if f.resolve() != ex]
    if not files:
        return []
    endings: list[str] = []
    for f in _cross_volume_sort(files, root)[-lookback:]:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue  # 不可读跳过，不阻断
        endings.append(normalize_ending(extract_ending(text)))
    return endings


def compile_syntax_patterns(rules: dict) -> list[re.Pattern]:
    """syntax_patterns.patterns 预编译（C4）：非法正则或可零宽匹配（pat.search("")
    命中）-> RuntimeError 含 pattern 原文（A23 口径，不静默放行）；键缺失 -> []。"""
    pats = ((rules or {}).get("syntax_patterns") or {}).get("patterns") or []
    compiled: list[re.Pattern] = []
    for src in pats:
        try:
            pat = re.compile(src)
        except re.error as e:
            raise RuntimeError(f"句式模板不是合法正则（{src!r}）: {e}")
        if pat.search(""):
            raise RuntimeError(f"句式模板可零宽匹配，计数会爆炸（{src!r}）")
        compiled.append(pat)
    return compiled


def run_cross_checks(
    text: str,
    recent_endings: Optional[list[str]],
    rules: dict,
) -> list[dict]:
    """两项跨章检查 -> issues（与 run_checks 同构，C1/C3/C5）。

    1. ending：本章归一化结尾在参照窗内（含本章）出现次数 > max_repeat -> issue；
    2. syntax_patterns：某 pattern 本章命中次数 > max_per_chapter -> issue；
    键缺失 / 参照章为空 -> 对应项跳过（零误伤）；两键全缺 -> []（C16）。
    """
    if not rules or not text:
        return []
    issues: list[dict] = []

    end_cfg = rules.get("ending") or {}
    if end_cfg and recent_endings:
        min_chars = end_cfg.get("min_chars", 3)
        max_repeat = end_cfg.get("max_repeat", 2)
        mine = normalize_ending(extract_ending(text))
        if len(mine) >= min_chars:
            n = recent_endings.count(mine) + 1  # 含本章
            if n > max_repeat:
                issues.append({
                    "quote": extract_ending(text)[:_QUOTE_TRUNC],
                    "problem": (f"收束句复读：最近{len(recent_endings)}章该结尾已出现"
                                f"{n - 1}次，含本章共{n}次（上限{max_repeat}）"),
                    "fix": "重写结尾段：换一个动作或画面收束，不要复用近期用过的句子",
                })

    syn_cfg = rules.get("syntax_patterns") or {}
    if syn_cfg:
        max_per = syn_cfg.get("max_per_chapter", 1)
        sentences: Optional[list[str]] = None
        for pat in compile_syntax_patterns(rules):
            matches = list(pat.finditer(text))
            if len(matches) > max_per:
                if sentences is None:
                    sentences = split_sentences(text)
                # 按命中起点定位句（跨句命中时 group(0) 不落在单句内，
                # _first_sentence_with 会返回命中串本身导致 fixer 不可定位）
                issues.append({
                    "quote": _sentence_at(text, sentences, matches[0].start()),
                    "problem": f"句式模板超配额：命中{len(matches)}次（上限{max_per}）",
                    "fix": "删或改写多余命中，保留最有效的一处",
                })
    return issues


# ---------- 结构检查（event-anchor，design §3.1，零 LLM）----------
def _valid_lines(text: str) -> list[str]:
    """有效行（Z1）：非空行剔除 `#` 标题行与 `---`/`***` 分隔行（extract_ending C2 同款跳过集）。"""
    valid: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if len(s) >= 3 and set(s) <= {"-", "*"}:
            continue  # 分隔线
        valid.append(s)
    return valid


def _valid_int(cfg: dict, key: str) -> Optional[int]:
    """阈值类型守卫（Z2）：isinstance(int) 且 >= 0 才参与比较，否则视为未配置（fail-open）。"""
    v = cfg.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def run_structure_checks(text: str, rules: Optional[dict]) -> list[dict]:
    """chapter_structure 三项结构检查 -> issues（与 run_checks 同构，E1-E4）。

    口径（Z1）：有效字符数 = 有效行拼接长度（行已 strip）；对话行数 = 有效行中
    _is_dialogue_line 命中数；密度分母 = 有效行数；状态词总命中数 = 逐词出现
    次数之和（text.count，一词多次计多次）；E3 quote = 文本序最早含任一状态词的句子。
    键缺失/词表空/阈值类型非法 -> 对应项跳过（E4/Z2）；rules 为 None 或 text
    为空 -> []；有效行数为 0 -> 密度项跳过（零除守卫，该文已被 E1 按碎片章拦截）。
    """
    cs = (rules or {}).get("chapter_structure")
    if not isinstance(cs, dict) or not cs or not text:
        return []
    issues: list[dict] = []

    lines = _valid_lines(text)
    n_lines = len(lines)
    chars = len("".join(lines))
    n_dialogue = sum(1 for ln in lines if _is_dialogue_line(ln))

    # 1. 碎片章（E1）：quote 置空 = 全文属性（report-only 通道仅供留痕展示，D9）
    min_chars = _valid_int(cs, "min_chars")
    if min_chars is not None and chars < min_chars:
        issues.append({
            "quote": "",
            "problem": f"碎片章：正文{chars}字（下限{min_chars}字）",
            "fix": "本章缺少完整事件。按章节规划补事件锚，扩写为完整章节；不要只往里加字。请使用重写命令。",
        })

    # 2. 零对话独白章（E2）：体量达标但对话行不足
    d_chars = _valid_int(cs, "dialogue_check_min_chars")
    d_lines = _valid_int(cs, "min_dialogue_lines")
    if (d_chars is not None and d_lines is not None
            and chars >= d_chars and n_dialogue < d_lines):
        issues.append({
            "quote": lines[0][:_QUOTE_TRUNC],
            "problem": f"零对话独白章：{chars}字仅{n_dialogue}行对话",
            "fix": "补回场景与对话：让人物在场、让对话发生；内心独白压缩为不超过3笔的状态登记。",
        })

    # 3. 状态堆叠（E3）：状态词密度超每百行上限
    state_words = [w for w in (cs.get("state_words") or []) if isinstance(w, str) and w]
    density_max = _valid_int(cs, "state_density_max_per_100_lines")
    if state_words and density_max is not None and n_lines > 0:
        hits = sum(text.count(w) for w in state_words)
        density = hits / n_lines * 100
        if density > density_max:
            first = next(
                (s for s in split_sentences(text) if any(w in s for w in state_words)),
                "",
            )
            issues.append({
                "quote": first[:_QUOTE_TRUNC],
                "problem": f"状态堆叠：状态词每百行{density:.0f}次（上限{density_max}次）",
                "fix": "状态登记删至每章3笔以内，删出来的篇幅让给事件。",
            })

    return issues


# ---------- AI 味量化（A25-A27，design §3.1.3）----------
@dataclass(frozen=True)
class Baseline:
    total_chars: int
    sent_mean: float      # 基准平均句长
    sent_std: float
    freq: dict[str, float]  # 字 + bigram 归一化频率向量


def _freq_vector(text: str) -> dict[str, float]:
    """字 + bigram 归一化频率向量（空白不计）。"""
    chars = [c for c in text if not c.isspace()]
    tokens = chars + [a + b for a, b in zip(chars, chars[1:])]
    if not tokens:
        return {}
    return {k: v / len(tokens) for k, v in Counter(tokens).items()}


def _cosine(p: dict[str, float], q: dict[str, float]) -> float:
    if not p or not q:
        return 0.0
    num = sum(p[k] * q[k] for k in p.keys() & q.keys())
    np_ = math.sqrt(sum(v * v for v in p.values()))
    nq = math.sqrt(sum(v * v for v in q.values()))
    return num / (np_ * nq) if np_ and nq else 0.0


def _read_text_files(files: list[Path]) -> list[str]:
    texts = []
    for f in files:
        try:
            texts.append(f.read_text(encoding="utf-8"))
        except OSError:
            continue  # 不可读跳过，不阻断统计
    return texts


def load_baseline(settings) -> Optional[Baseline]:
    """基准语料统计：exemplar 目录全量（Z8，不受注入上限约束）+ 人工正文目录。

    语料完全为空 -> None。min_baseline_chars 阈值判定在 ai_flavor_score（锚点属 ai_score 配置）。
    """
    files: list[Path] = []
    if settings.exemplar_subpath:
        files.extend(_exemplar_files(settings.exemplar_full))
    if settings.human_text_subpath and settings.human_text_full.is_dir():
        files.extend(sorted(
            q for q in settings.human_text_full.iterdir()
            if q.is_file() and q.suffix.lower() in (".txt", ".md")
        ))
    texts = _read_text_files(files)
    full = "\n\n".join(texts)
    if not full.strip():
        return None
    sents = split_sentences(full)
    lengths = [len(s) for s in sents] or [len(full)]
    mean = sum(lengths) / len(lengths)
    std = math.sqrt(sum((n - mean) ** 2 for n in lengths) / len(lengths))
    return Baseline(
        total_chars=len(full),
        sent_mean=mean,
        sent_std=std,
        freq=_freq_vector(full),
    )


def ai_flavor_score(text: str, rules: Optional[dict], baseline: Optional[Baseline]) -> dict:
    """AI 味 0-100（越高越 AI，D6）。纯函数、确定性（A25）。

    - blacklist：命中密度（次/千字）/ A_bl 满格；未配置 -> 组件不可用
    - sentence：|mean(text) - μ| / σ / A_s；μ/σ 取基准，降级用内置默认（Z4）
    - freq：1 - cos(P, Q)；基准不可用（无/不足 min_baseline_chars）-> 组件不可用 + degraded
    - 总分：可用组件按 weights 线性加权、缺失组件权重重归一（D6）
    """
    ai_cfg = (rules or {}).get("ai_score") or {}
    weights = {**_DEFAULT_WEIGHTS, **(ai_cfg.get("weights") or {})}
    anchors = {**_DEFAULT_ANCHORS, **(ai_cfg.get("anchors") or {})}

    degraded = baseline is None or baseline.total_chars < anchors["min_baseline_chars"]
    components: dict[str, float] = {}

    bl = (rules or {}).get("blacklist") or []
    if bl and text:
        density = sum(text.count(w) for w in bl) / (len(text) / 1000)
        components["blacklist"] = min(100.0, density / anchors["blacklist_per_1k"] * 100)

    sents = split_sentences(text)
    if sents:
        mean = sum(len(s) for s in sents) / len(sents)
        mu = baseline.sent_mean if not degraded else _FALLBACK_MU
        sigma = baseline.sent_std if not degraded else _FALLBACK_SIGMA
        components["sentence"] = min(
            100.0, abs(mean - mu) / max(sigma, 1e-9) / anchors["sentence_sigma"] * 100
        )

    if not degraded and text:
        cos = _cosine(baseline.freq, _freq_vector(text))
        components["freq"] = min(100.0, (1 - cos) / anchors["freq_cos_gap"] * 100)

    avail = {k: v for k, v in components.items() if k in weights}
    wsum = sum(weights[k] for k in avail)
    score = sum(weights[k] * v for k, v in avail.items()) / wsum if wsum else 0.0
    return {
        "score": int(round(score)),
        "components": {k: int(round(v)) for k, v in components.items()},
        "degraded": degraded,
    }


# ---------- 1.9 风格体检（style-repeat，design §3.5，纯代码零 LLM）----------
def _state_suspicion(text: str, state_words: list[str]) -> dict:
    """单章嫌疑数据（纯函数，E9）：{"score", "lines", "dialogue", "state_hits"}。

    score = 状态词命中数/有效行数 − 对话行数/有效行数×2（Z1 同款有效行口径）；
    有效行数为 0（空文件/仅标题分隔行）-> score 记 0.0（零除守卫）。
    """
    lines = _valid_lines(text)
    n = len(lines)
    hits = sum(text.count(w) for w in state_words)
    dialogue = sum(1 for ln in lines if _is_dialogue_line(ln))
    score = (hits - dialogue * 2) / n if n else 0.0
    return {"score": round(score, 2), "lines": n, "dialogue": dialogue, "state_hits": hits}


def scan_style_report(dir_path: Path, rules: dict) -> dict:
    """递归扫描 .md/.txt -> 四节报告数据（C13/C14 + event-anchor E9）：收束句复读榜 /
    句式命中榜 / 分卷字数分布 / 状态章嫌疑榜。纯函数、同输入同输出。

    - endings：归一化结尾全局频次，count >= max_repeat+1 才上榜（降序，附文件清单）；
    - patterns：全部 pattern 的总命中数 + 超配额章清单（诊断要全貌，不是拦截）；
    - sizes：按顶层子目录分组（Z3 规避中文数字卷名字典序陷阱）+ 全局行；
    - state_chapters：逐章嫌疑分全量降序（D7 截断在展示层）；state_words 未配置
      -> None，配置后无文件 -> []（D8 分态：配置静默失效必须可发现）；
    - 规则键缺失 -> 对应节为空列表；目录不存在/无文件 -> files_scanned=0。
    """
    root = Path(dir_path)
    cs = (rules or {}).get("chapter_structure")
    cs_cfg = cs if isinstance(cs, dict) else {}
    state_words = [w for w in (cs_cfg.get("state_words") or []) if isinstance(w, str) and w]
    report: dict = {"endings": [], "patterns": [], "sizes": [], "files_scanned": 0,
                    "state_chapters": [] if state_words else None}
    if not root.is_dir():
        return report
    files = sorted(
        q for q in root.rglob("*")
        if q.is_file() and q.suffix.lower() in (".md", ".txt")
        and not any(part.startswith(".") for part in q.relative_to(root).parts)
    )
    if not files:
        return report
    files = _cross_volume_sort(files, root)

    end_cfg = (rules or {}).get("ending") or {}
    syn_cfg = (rules or {}).get("syntax_patterns") or {}
    min_chars = end_cfg.get("min_chars", 3) if end_cfg else 3
    ending_threshold = (end_cfg.get("max_repeat", 2) + 1) if end_cfg else 3
    compiled = compile_syntax_patterns(rules or {})

    ending_files: dict[str, list[str]] = {}
    pattern_hits: dict[str, list[tuple[str, int]]] = {p.pattern: [] for p in compiled}
    pattern_total: dict[str, int] = {p.pattern: 0 for p in compiled}
    sizes: dict[str, list[int]] = {}
    state_rows: list[dict] = []

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue  # 不可读跳过，不阻断
        report["files_scanned"] += 1
        rel = f.relative_to(root).as_posix()
        group = rel.split("/", 1)[0] if "/" in rel else "(根目录)"
        sizes.setdefault(group, []).append(len(text))

        if state_words:
            row = _state_suspicion(text, state_words)
            row["file"] = rel
            state_rows.append(row)
        if end_cfg:
            e = normalize_ending(extract_ending(text))
            if len(e) >= min_chars:
                ending_files.setdefault(e, []).append(rel)
        for pat in compiled:
            n = len(pat.findall(text))
            pattern_total[pat.pattern] += n
            if syn_cfg and n > syn_cfg.get("max_per_chapter", 1):
                pattern_hits[pat.pattern].append((rel, n))

    report["endings"] = [
        {"ending": e, "count": len(fs), "files": fs}
        for e, fs in sorted(
            ending_files.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ) if len(fs) >= ending_threshold
    ]
    report["patterns"] = [
        {"pattern": p, "total": pattern_total[p],
         "over": [{"file": rel, "count": n} for rel, n in pattern_hits[p]]}
        for p in pattern_total
    ]
    if state_words:
        # 全量降序入报告（D7：截断在展示层）；稳定排序，同分保持跨卷章序
        report["state_chapters"] = sorted(state_rows, key=lambda r: -r["score"])
    rows = []
    for group in sorted(sizes):
        ns = sizes[group]
        mean = sum(ns) / len(ns)
        std = math.sqrt(sum((x - mean) ** 2 for x in ns) / len(ns))
        rows.append({"group": group, "n": len(ns), "min": min(ns), "max": max(ns),
                     "mean": round(mean, 1), "cv": round(std / mean, 3) if mean else 0.0})
    if rows:
        all_ns = [x for ns in sizes.values() for x in ns]
        mean = sum(all_ns) / len(all_ns)
        std = math.sqrt(sum((x - mean) ** 2 for x in all_ns) / len(all_ns))
        rows.append({"group": "全局", "n": len(all_ns), "min": min(all_ns), "max": max(all_ns),
                     "mean": round(mean, 1), "cv": round(std / mean, 3) if mean else 0.0})
    report["sizes"] = rows
    return report
