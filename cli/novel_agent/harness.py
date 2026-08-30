"""Harness：回放 / 对比 / 评测 / 规则测试。

从 py/multiagent_novel.py 迁移，适配新 storage/llm/state：
- replay：读 run JSON，纯重演状态链（不调模型）
- compare：两 run 并排对比（规则词统计 + AI 味浓度行）
- evaluate：LLM 当评委按 rubric 打分，附 AI 味量化（1.1）
- run_tests：基于规则的断言（称呼红线/意图/维度分/状态机），不调模型
- backtest_gate：历史 runs 回测门禁阈值（1.1 A35，分数缓存增量）

所有函数接收 settings 与可选 out（输出函数），便于测试捕获输出。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

from .checker import ai_flavor_score, load_baseline, load_quality_rules
from .config import Settings, get_settings
from .llm import LLMClient
from .prompts import EVALUATOR_RUBRIC
from .storage import list_runs, load_run

__all__ = ["replay", "compare", "evaluate", "run_tests", "backtest_gate"]

# AI 味组件中文名（design §3.8 输出样例）
_AI_COMP_NAMES = {"blacklist": "黑名单", "sentence": "句长", "freq": "词频"}
# reviewer 八维（A1/A7，run_tests 维度分断言用）
_SCORE_DIMS = ("人物一致性", "文风一致性", "剧情连贯性", "时间线一致性",
               "环境一致性", "伏笔一致性", "比喻密度", "视角越界")


def replay(
    run_id: str,
    settings: Optional[Settings] = None,
    out: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """回放：读取运行 JSON，不调模型，纯重演状态链。返回该 run 记录。"""
    d = load_run(run_id, settings)
    out(f"=== 回放 {d['run_id']} ===")
    out(f"task : {d['task']}")
    out(f"config: {d['config']}")
    out(f"time : {d['timestamp']}")
    # exemplar-routing：本次写章注入了哪些样文（旧记录无该键则不显示）
    route = d.get("exemplar_route")
    if route:
        out(f"样文路由: {'、'.join(route.get('files', []))}（{route.get('reason', '')}）")
    out(f"--- 共 {len(d['steps'])} 步 ---")
    for s in d["steps"]:
        o = s["output_state"]
        n_draft = len(o.get("draft") or "")
        n_polished = len(o.get("polished") or "")
        out(
            f"  #{s['step_id']} [{s['agent']}] round={s['round']} "
            f"-> next={s['decision']} | draft={n_draft}字 polished={n_polished}字"
        )
        # 0.8 T13：writer 步展示构思（前 60 字；.get 容错旧记录无该键）
        outline = o.get("outline") or ""
        if outline:
            head = outline if len(outline) <= 60 else outline[:60] + "…"
            out(f"     构思：{head}")
    out("\n=== 最终章节 ===")
    out(d["final_state"].get("final_chapter") or "(空)")
    return d


def _extract_score_fields(result: str) -> Dict[str, Any]:
    """从截断/不规范文本里正则提取分数与各文本字段（最后兜底）。"""
    score: Dict[str, Any] = {}
    for key in ("连贯性", "人物一致性", "剧情合理性", "标题评分"):
        m = re.search(rf'"{key}"\s*:\s*"?(\d+)', result)
        if m:
            score[key] = int(m.group(1))
    for key in ("理由", "建议标题", "标题理由"):
        m = re.search(rf'"{key}"\s*:\s*"?(.*?)(?:["\n}}]|$)', result, re.S)
        if m:
            score[key] = m.group(1).strip()
    return score


def _parse_score(result: str) -> Dict[str, Any]:
    """容错解析评委 JSON；截断时尝试补 } 或正则提取分数。"""
    # 1) 直接解析
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass
    # 2) 提取第一个 { 到最后一个 } 之间
    m = re.search(r"\{.*\}", result, re.S)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # 3) 截断兜底：有 { 但没结尾 }，逐个补 } 再试
    start = result.find("{")
    if start != -1:
        snippet = result[start:]
        for _ in range(3):
            snippet += "}"
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass
        # 4) 补 } 仍失败：正则提取打分字段
        fields = _extract_score_fields(result)
        if fields:
            return fields
    return {"error": "评委未返回可解析 JSON", "raw": result[:200]}


def _eval_system_prompt(instruction: str) -> str:
    """构造评委 system prompt：非空 instruction 时前置写作规则，避免把故意的设计当 bug 扣分。"""
    if not instruction.strip():
        return EVALUATOR_RUBRIC
    return (
        "【写作规则】（评判时必须遵守这些设定，违反规则的不是bug）\n"
        f"{instruction}\n\n"
        "如果正文中男主不出现名字、女主名字不出现等符合上述规则的，\n不扣分。\n\n"
        f"{EVALUATOR_RUBRIC}"
    )


def evaluate(
    run_id: str,
    settings: Optional[Settings] = None,
    llm: Optional[LLMClient] = None,
    out: Callable[[str], None] = print,
    instruction: str = "",
) -> Dict[str, Any]:
    """用 LLM 当评委，按 rubric 给 final_chapter 打三维评分。

    instruction：写作指令全文，前置进 system prompt 当作"写作规则"，
    避免评委把故意的设计（如男主前4章不取名）当 bug 扣分。
    """
    settings = settings or get_settings()
    if llm is None:
        llm = LLMClient(settings=settings)
    chapter = load_run(run_id, settings)["final_state"].get("final_chapter") or ""

    out("    [evaluate·评委打分中...]")
    result = llm.chat(
        _eval_system_prompt(instruction),
        f"请评分以下稿件：\n\n{chapter}",
        max_tokens=2048,
        temperature=(
            settings.judge_temperature
            if settings.judge_temperature is not None else 0.2
        ),
    )

    if not result or not result.strip():
        out("(评测模型未返回内容)")
        return {"error": "评测模型未返回内容"}

    score = _parse_score(result)
    if "error" in score:
        out(f"评测解析失败，原始返回前500字：\n{result[:500]}")
        return score

    out("=== LLM 评测报告 ===")
    for k in ("连贯性", "人物一致性", "剧情合理性", "标题评分"):
        if k in score:
            out(f"  {k}: {score[k]}/5")
    if "理由" in score:
        out(f"  理由: {score['理由']}")
    suggestion = str(score.get("建议标题", "")).strip()
    if suggestion and suggestion != "保留":
        out(f"  建议标题: {suggestion}（仅建议，不自动改）")
    if "标题理由" in score:
        out(f"  标题理由: {score['标题理由']}")

    # 1.1：AI 味量化（纯代码组件，规则与基准从 settings 加载；A28 双方/每次现算）
    ai = ai_flavor_score(chapter, load_quality_rules(settings), load_baseline(settings))
    comp = " · ".join(
        f"{_AI_COMP_NAMES.get(k, k)} {v}" for k, v in ai["components"].items()
    )
    out(f"  AI 味浓度: {ai['score']}/100（越高越AI）" + (f" 组件：{comp}" if comp else ""))
    if ai["degraded"]:
        out("  （降级：基准语料不足，词频组件未参与）")
    score["AI味浓度"] = ai["score"]
    return score


def run_tests(
    run_id: str,
    settings: Optional[Settings] = None,
    out: Callable[[str], None] = print,
) -> bool:
    """对一次运行做基于规则的断言（不调模型）。返回是否全部通过。

    四层维度：①称呼红线（规则 forbidden，不出现）②意图（规则 intent_words，
    该出现）③维度分（八维齐全且各分 1-5 整数，A7/A37）④状态机（流程跑通）。
    规则未配置 -> ①②退化为无（A36 不误伤）；旧记录无 scores -> ③跳过（A37）。
    """
    if settings is None:
        settings = get_settings()
    d = load_run(run_id, settings)
    final = d["final_state"]
    chapter = final.get("final_chapter") or ""
    feedback = final.get("feedback") or ""
    next_agent = final.get("next_agent") or ""

    rules = load_quality_rules(settings)
    cases = []
    if rules:
        for w in (rules.get("naming_redlines") or {}).get("forbidden") or []:
            cases.append((f"称呼红线：不含'{w}'", w not in chapter,
                          f"出现次数={chapter.count(w)}"))
        for w in rules.get("intent_words") or []:
            cases.append((f"意图：含'{w}'", w in chapter,
                          f"出现次数={chapter.count(w)}"))

    scores = final.get("scores")
    if isinstance(scores, dict) and scores:  # 旧记录无/空 scores -> 跳过（A37）
        missing = [k for k in _SCORE_DIMS if k not in scores]
        bad = {k: v for k, v in scores.items()
               if not (isinstance(v, int) and not isinstance(v, bool)
                      and 1 <= v <= 5)}
        cases.append((
            "维度分：八维齐全且各分 1-5 整数",
            not missing and not bad,
            f"缺失={missing or '无'}，越界或非整数={bad or '无'}",
        ))

    # 1.6 B16：de-AI 留痕自洽性--accepted 的记录必然 after < before（防造假）；
    # 旧记录无 deai 键 / 未接受 -> 跳过（B20）；其余情节保真由①②作用于
    # de-AI 后稿（final_chapter）天然覆盖（design §3.6）。
    deai = final.get("deai")
    if isinstance(deai, dict) and deai.get("accepted"):
        cases.append((
            "去AI留痕：accepted 时 after < before",
            deai.get("after", float("inf")) < deai.get("before", float("-inf")),
            f"before={deai.get('before')}，after={deai.get('after')}",
        ))

    cases.append((
        "流程正确性：审稿通过且 done",
        ("通过" in feedback) and (next_agent == "done"),
        f"feedback含通过={'通过' in feedback}, next_agent={next_agent}",
    ))

    out(f"=== 测试用例 {d['run_id']} ===")
    all_ok = True
    for name, ok, detail in cases:
        out(f"  [{'PASS' if ok else 'FAIL'}] {name} | {detail}")
        all_ok = all_ok and ok
    out(f"结果：{'全部通过 ✅' if all_ok else '存在失败 ❌'}")
    return all_ok


def compare(
    run_id_a: str,
    run_id_b: str,
    settings: Optional[Settings] = None,
    out: Callable[[str], None] = print,
) -> None:
    """同一 task 两种配置的并排对比（读快照 + 规则统计）。"""
    settings = settings or get_settings()
    a, b = load_run(run_id_a, settings), load_run(run_id_b, settings)
    ca, cb = a["final_state"], b["final_state"]
    cha, chb = ca.get("final_chapter") or "", cb.get("final_chapter") or ""

    out("=== A/B 对比 ===")
    out(f"{'维度':<14}{'A(' + run_id_a[:19] + ')':<28}{'B(' + run_id_b[:19] + ')'}")
    out(f"{'temperature':<14}{str(a['config'].get('temperature')):<28}{str(b['config'].get('temperature'))}")
    out(f"{'model':<14}{str(a['config'].get('model')):<28}{str(b['config'].get('model'))}")
    wm_a, wm_b = a["config"].get("writer_model"), b["config"].get("writer_model")
    if wm_a is not None or wm_b is not None:  # 旧记录缺键时跳过该行
        out(f"{'writer_model':<14}{str(wm_a):<28}{str(wm_b)}")
    out(f"{'task':<14}{a['task'][:20]:<28}{b['task'][:20]}")
    out(f"{'字数':<14}{len(cha):<28}{len(chb)}")
    # 1.1 Z1：规则词统计改读规则文件（forbidden / intent_words），未配置跳过
    rules = load_quality_rules(settings)
    if rules:
        for w in (rules.get("naming_redlines") or {}).get("forbidden") or []:
            out(f"{'含' + w:<14}{str(w in cha):<28}{str(w in chb)}")
        for w in rules.get("intent_words") or []:
            out(f"{'含' + w + '次数':<14}{cha.count(w):<28}{chb.count(w)}")
    # 1.1：AI 味浓度行（双方现算，A28；旧记录无该键不受影响）
    baseline = load_baseline(settings)
    out(f"{'AI味浓度':<14}"
        f"{ai_flavor_score(cha, rules, baseline)['score']:<28}"
        f"{ai_flavor_score(chb, rules, baseline)['score']}")
    out(f"{'审稿通过':<14}{str('通过' in (ca.get('feedback') or '')):<28}{str('通过' in (cb.get('feedback') or ''))}")
    out("\n--- A 开头 ---\n" + cha[:80])
    out("\n--- B 开头 ---\n" + chb[:80])


# ---------- 回测门禁（A35，design §3.7）----------
_GATE_BACKTEST_THRESHOLDS = (3.0, 3.5, 4.0)


def _gate_weighted(score: Any, rules: Optional[dict]) -> Optional[float]:
    """按 eval_gate.weights 算加权分（标题评分硬排除，A32）；不可算 -> None。

    与 cli._gate_ok 同公式（Σw·s/Σw），此处要数值不要 bool（回测要分布）。
    """
    if not isinstance(rules, dict) or not isinstance(score, dict):
        return None
    gate = rules.get("eval_gate")
    if not isinstance(gate, dict) or not gate.get("enabled"):
        return None
    weights = {
        k: w for k, w in (gate.get("weights") or {}).items()
        if k != "标题评分" and isinstance(w, (int, float))
    }
    hits = [(w, score[k]) for k, w in weights.items()
            if isinstance(score.get(k), (int, float)) and not isinstance(score[k], bool)]
    wsum = sum(w for w, _ in hits)
    if not hits or wsum <= 0:
        return None
    return sum(w * s for w, s in hits) / wsum


def backtest_gate(
    settings: Optional[Settings] = None,
    out: Callable[[str], None] = print,
    limit: Optional[int] = None,
) -> Optional[dict]:
    """回测门禁（A35）：历史 runs 逐条跑评委，输出加权分分布与候选阈值拦截面。

    - 遍历 runs（limit 控条数），跳过无 final_chapter 的记录；
    - 分数缓存 <runs 目录>/../gate_backtest.json（Z10，按 run_id 增量，命中不重烧评委）；
    - 拦截面无自动 ground truth，清单供人工核对（REPL 里人是标尺）；
    - 未配置 eval_gate -> 提示后返回 None。
    """
    if settings is None:
        settings = get_settings()
    rules = load_quality_rules(settings)
    gate = rules.get("eval_gate") if isinstance(rules, dict) else None
    if not (isinstance(gate, dict) and gate.get("enabled")):
        out("未配置 eval_gate（质量规则缺失或未启用），无法回测。")
        return None

    cache_path = settings.runs_path.parent / "gate_backtest.json"
    cache: Dict[str, Any] = {}
    if cache_path.is_file():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cache = loaded
        except (json.JSONDecodeError, OSError):
            pass  # 缓存坏 -> 当作无缓存重算

    ids = list_runs(settings)
    if limit:
        ids = ids[:limit]

    out("=== 门禁回测（顺序跑评委，命中缓存不重烧）===")
    rows: list[tuple[str, Optional[float]]] = []
    for rid in ids:
        try:
            record = load_run(rid, settings)
        except (OSError, json.JSONDecodeError) as e:
            out(f"  跳过 {rid}（读取失败：{e}）")
            continue
        if not (record.get("final_state") or {}).get("final_chapter"):
            continue  # 无 final_chapter -> 跳过（tasks T10）
        if isinstance(cache.get(rid), dict):
            score, src = cache[rid], "缓存"
        else:
            score = evaluate(rid, settings, out=out)
            if not isinstance(score, dict) or "error" in score:
                out(f"  {rid} 评测失败，跳过")
                continue
            cache[rid] = score
            src = "评委"
        weighted = _gate_weighted(score, rules)
        rows.append((rid, weighted))
        ws = f"{weighted:.2f}" if weighted is not None else "N/A"
        out(f"  {rid}  加权分 {ws}（{src}）")

    # 增量写回缓存（Z10）
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        out(f"（缓存写入失败：{e}）")

    valid = sorted(((w, rid) for rid, w in rows if w is not None))
    out(f"\n--- 加权分分布（低->高，共 {len(valid)}/{len(rows)} 条有效）---")
    for w, rid in valid:
        out(f"  {w:.2f}  {rid}")
    out("--- 候选阈值拦截面（人工核对误伤）---")
    for t in _GATE_BACKTEST_THRESHOLDS:
        blocked = [rid for w, rid in valid if w < t]
        out(f"  threshold {t}: 拦截 {len(blocked)} 条"
            + (" -> " + ", ".join(blocked) if blocked else ""))
    return {rid: w for rid, w in rows}
