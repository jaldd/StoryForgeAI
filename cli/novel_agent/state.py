"""流水线状态：MultiAgent 写作流程的共享状态。

原 py/multiagent_novel.py 的 NovelState 重命名为 PipelineState，
避免和 memory.WorkingMemory（小说当前进度）撞名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

__all__ = ["PipelineState"]


@dataclass
class PipelineState:
    """一次写作任务的状态机数据。各 Agent 共用同一个实例，改属性 + 推进 next_agent。"""

    # -- 核心五字段 --
    task: str = ""            # Director 收到的写作任务
    draft: str = ""           # Writer 写的初稿
    polished: str = ""        # Polisher 润色稿
    feedback: str = ""        # Reviewer 审稿意见
    final_chapter: str = ""   # 最终定稿

    # -- 重写输入 --
    source_content: str = ""   # 重写模式：已有内容（writer 作为参考自由重写）

    # -- 控制字段 --
    round: int = 0                 # 当前轮次，防死循环
    next_agent: str = "director"   # 下一步派给谁
    review_count: int = 0          # 审稿打回次数，防死循环

    # -- 过程日志 --
    log: List[str] = field(default_factory=list)
