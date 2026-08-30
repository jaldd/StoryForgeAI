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

__all__ = ["load_quality_rules", "split_sentences", "run_checks", "load_baseline", "ai_flavor_score"]

_SENTENCE_DELIM = r"。！？!?；;\n"
# 直引号 " ' 也算对话标记：正文章节常用直引号（弯/CJK 引号之外的真实分布）
_QUOTE_CHARS = "「」『』“”‘’\"'"
_QUOTE_TRUNC = 50

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
