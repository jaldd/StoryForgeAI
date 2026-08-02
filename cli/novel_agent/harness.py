"""Harness：回放 / 对比 / 评测 / 规则测试。

从 py/multiagent_novel.py 迁移，适配新 storage/llm/state：
- replay：读 run JSON，纯重演状态链（不调模型）
- compare：两 run 并排对比
- evaluate：LLM 当评委按 rubric 打分
- run_tests：基于规则的断言（铁律/意图/状态机），不调模型

所有函数接收 settings 与可选 out（输出函数），便于测试捕获输出。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

from .config import Settings, get_settings
from .llm import LLMClient
from .prompts import EVALUATOR_RUBRIC
from .storage import load_run

__all__ = ["replay", "compare", "evaluate", "run_tests"]


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
    out(f"--- 共 {len(d['steps'])} 步 ---")
    for s in d["steps"]:
        o = s["output_state"]
        n_draft = len(o.get("draft") or "")
        n_polished = len(o.get("polished") or "")
        out(
            f"  #{s['step_id']} [{s['agent']}] round={s['round']} "
            f"-> next={s['decision']} | draft={n_draft}字 polished={n_polished}字"
        )
    out("\n=== 最终章节 ===")
    out(d["final_state"].get("final_chapter") or "(空)")
    return d


def _parse_score(result: str) -> Dict[str, Any]:
    """容错解析评委 JSON。"""
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", result, re.S)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"error": "评委未返回可解析 JSON", "raw": result[:200]}


def evaluate(
    run_id: str,
    settings: Optional[Settings] = None,
    llm: Optional[LLMClient] = None,
    out: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """用 LLM 当评委，按 rubric 给 final_chapter 打三维评分。返回评分 dict。"""
    settings = settings or get_settings()
    if llm is None:
        llm = LLMClient(settings=settings)
    chapter = load_run(run_id, settings)["final_state"].get("final_chapter") or ""

    out("    [evaluate·评委打分中...]")
    result = llm.chat(
        EVALUATOR_RUBRIC,
        f"请评分以下稿件：\n\n{chapter}",
        max_tokens=1024,
        temperature=0.2,
    )
    score = _parse_score(result)

    out("=== LLM 评测报告 ===")
    for k in ("连贯性", "人物一致性", "剧情合理性"):
        if k in score:
            out(f"  {k}: {score[k]}/5")
    if "理由" in score:
        out(f"  理由: {score['理由']}")
    return score


def run_tests(
    run_id: str,
    settings: Optional[Settings] = None,
    out: Callable[[str], None] = print,
) -> bool:
    """对一次运行做基于规则的断言（不调模型）。返回是否全部通过。

    三层维度：①铁律(不该出现) ②意图(该出现) ③状态机(流程跑通)。
    """
    d = load_run(run_id, settings)
    final = d["final_state"]
    chapter = final.get("final_chapter") or ""
    feedback = final.get("feedback") or ""
    next_agent = final.get("next_agent") or ""

    cases = [
        # ① 铁律：男主不被取名
        ("人物一致性：不含'许风'", "许风" not in chapter, f"出现次数={chapter.count('许风')}"),
        # ② 意图：天气线落到正文
        ("文风特征：含'风'字", "风" in chapter, f"出现次数={chapter.count('风')}"),
        # ③ 状态机：审稿通过且正常终止
        ("流程正确性：审稿通过且 done",
         ("通过" in feedback) and (next_agent == "done"),
         f"feedback含通过={'通过' in feedback}, next_agent={next_agent}"),
    ]

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
    out(f"{'task':<14}{a['task'][:20]:<28}{b['task'][:20]}")
    out(f"{'字数':<14}{len(cha):<28}{len(chb)}")
    out(f"{'含风次数':<14}{cha.count('风'):<28}{chb.count('风')}")
    out(f"{'含许风':<14}{str('许风' in cha):<28}{str('许风' in chb)}")
    out(f"{'审稿通过':<14}{str('通过' in (ca.get('feedback') or '')):<28}{str('通过' in (cb.get('feedback') or ''))}")
    out("\n--- A 开头 ---\n" + cha[:80])
    out("\n--- B 开头 ---\n" + chb[:80])
