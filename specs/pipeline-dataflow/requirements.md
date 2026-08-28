# 0.8 流水线数据流补漏（pipeline-dataflow）— 需求

> 需求来源：`specs/ROADMAP.md` 0.8 条目（L93-108）。
> 最高约束：`.specify/memory/constitution.md`。
> 现状证据与详细设计见同目录 `design.md`；任务分解见 `tasks.md`。
> 复核状态：2026-08-28 已完成代码级复核（file:line 证据全部核实，两处勘误成立），D1-D9 已拍板（全按推荐项，D9 含首章 `None` 边界），**可开工**。

## 1. 背景与问题

流水线四个角色中，director 是空壳（只转发任务零决策）；writer 产出的构思被 `===` split 后丢弃，polisher 盲润、reviewer 无验收基准、replay 看不到当时意图；reviewer 不注入工作记忆却要审伏笔/时间线一致性（审它看不见的东西）；长度控制三处打架（writer 写死「约200字」、`polisher_system` 的 `target_words=1500` 是死参数、无统一口径）；cli 层裸调 LLM 生成剧情摘要绕过 agent 抽象。

本 feature 修补以上五个数据流断点，使「一次生成、处处消费」的数据流闭环成立，为阶段 1（质量闭环）与阶段 3.3（planner 回归）打地基。

## 2. 术语

- **流水线**：`agent._run_loop` 按 `state.next_agent` 驱动的 writer → polisher → reviewer 状态机。
- **构思（outline）**：writer 在正文前输出的创作意图说明（人物、情绪走向、场景细节），以 `===` 与正文分隔。
- **run record**：`storage.save_run` 落盘的运行 JSON，键被 `harness.replay` 直读。
- **EARS**：`当 <条件> 时，系统应 <行为>` 的验收条目格式。

## 3. 验收标准（EARS）

### 3.1 director 退役

- **A1** 当 `agent.run(task)` 执行完整流水线时，系统应从 writer 直接启动（`PipelineState.next_agent` 默认值为 `writer`），run record 的 `steps` 中不出现 agent 名为 `"director"` 的步骤。
- **A2** 当在 `cli/novel_agent/` 源码中检索 `director` 时，系统应零命中（方法、`agents` 注册、默认值、docstring、注释全部清除）。
- **A3** 当 `harness.replay` 回放 0.7 及之前生成的含 `"director"` 步骤的旧 run 记录时，系统应正常输出该步骤与最终章节，不抛异常。

### 3.2 writer 构思保留与传递

- **A4** 当 writer 的模型返回含 `===` 分隔符的输出时，系统应将分隔符前的构思存入 `PipelineState` 新字段（命名见 D1，推荐 `outline`），分隔符后的正文存入 `state.draft`。
- **A5** 当 writer 的模型返回不含 `===` 的输出或输出为空时，系统应保持现状：全文（或占位兜底）进 `state.draft`，构思字段为空串。
- **A6** 当 run record 生成时，系统应使构思字段自动出现在 `steps[*].output_state` 与 `final_state` 中（经 `asdict` 展开，`_record` 无需改动结构）。
- **A7** 当 `state.outline` 非空且 polisher 执行时，polisher 发给模型的 prompt 应包含该构思（作为润色不跑偏意图的依据）。
- **A8** 当 `state.outline` 非空且 reviewer 执行时，reviewer 发给模型的 prompt 应包含该构思（作为「正文是否实现构思」的验收基准）；构思为空时不应注入空块。

### 3.3 reviewer 前情注入

- **A9** 当 `working_memory` 已注入且 `current_chapter` 非 `None` 时，reviewer 与 polisher 的 system prompt 应包含 `_working_context()` 快照（当前进度/最近剧情/角色状态/未回收伏笔；polisher 侧为 D8 拍板的设计外延，支撑其「严禁改动伏笔」铁律）。
- **A10** 当 `working_memory` 为 `None` 或 `current_chapter` 为 `None`（首章）时，reviewer/polisher 的 prompt 不应包含空快照噪音。
- **A11** 当 reviewer 执行 RAG 检索时，系统应保持 `with_prior=False`（不注入前文正文片段；reviewer 的前情来源仅为工作记忆快照 + 构思，理由见 design D3）。

### 3.4 长度控制归一

- **A12** 当 `Settings.target_words` 已配置时，writer 的 user prompt（含新写与 rewrite 两个分支）应包含该目标字数（如「目标约1500字」），且不再出现硬编码「约200字」。
- **A13** 当 `polisher_system` 构建 prompt 时，`target_words` 参数应出现在 prompt 文本中（激活现死参数，作为扩写导向）。
- **A14** 当未显式配置长度时，系统应使用默认值 1500（与现死参数默认一致，见 D4）。
- **A15** 当 NovelAgent 构造时，系统应允许 `target_words` 参数注入覆盖 settings（同 `max_reviews` 模式），且 run record 的 `config` 应包含 `target_words`。

### 3.5 cli 层 LLM 调用收编

- **A16** 当 `_do_write` 生成剧情摘要时，cli 应调用 `NovelAgent` 的摘要方法（命名见 D6，推荐 `summarize_chapter`），不应直接引用 `agent.llm` 或 `prompts.PLOT_SUMMARY_SYSTEM`。
- **A17** 当摘要方法抛异常时，cli 的兜底行为应保持现状（摘要回落为 task，不阻断落盘）。
- **A18**（P1）当 refine/rewrite 成功存回章节后，系统应同步刷新工作记忆（重新生成该章摘要并持久化）。

### 3.6 失败路径与兜底

- **A19** 当 writer 输出为空或解析后正文为空时，系统应保持现有兜底（draft 占位 + log 留痕）。
- **A20** 当 `harness.replay` 回放不含构思字段的旧 run 记录时，系统应正常工作（replay 不读该键）。
- **A21** 当 refine/rewrite 中章节号解析失败（文件名不匹配章节模式）时，系统应跳过工作记忆刷新、不阻断存回主流程。

## 4. 非目标（明确不做）

1. **不改 `partial_refine`**：`partial.py` 及其调用路径零改动；构思字段只服务状态机流水线。
2. **不动 0.7 的模型配置**：模型名、base_url、API key、温度等一概不动（宪法 §2）。
3. **不做阶段 1 的质量门禁/审核维度化**：reviewer 仍返回单一 `{"pass", "reason", "issues"}`，不做分维度打分、不做机械检查、不做修复式打回。
4. **不做阶段 3.3 的 planner 角色**：director 删除后编排入口留白，构思仍由 writer 顺带产出；planner 回归是长线记忆阶段的事。
5. **不修存量 3 个失败测试**：`test_strip_polisher_meta`、`test_runtime_dir_override`、`test_defaults` 是与本 feature 无关的既有失败，不纳入修复范围。
6. **不引入新依赖**、不做流式输出、不做多模型 fallback。
7. **不改 writer/polisher 的 `max_tokens=4096`**（宪法 §4 规定值）。长度目标提升带来的截断风险在 design §6 记录与验证，本 feature 不调整该值。
8. **不做事后字数校验/长度不达标重试**：那是阶段 1 质量门禁的事；本 feature 只保证长度目标真正进 prompt。
9. **不改 `harness.replay` 的既有输出行格式**：兼容性新增（如展示构思）只能是追加行，不改既有行的字段与语义。
10. **不改 RAG 检索策略**（top_k、doc_type 分流、索引时机）。

## 5. 宪法对齐表

| 宪法条款 | 约束要点 | 本 feature 的对齐方式 |
|---|---|---|
| §1 项目身份 | 代码仓库零具体小说名 | 文档与新增测试示例沿用仓库既有虚构名（「异乡风起」「林晚」，与 `conftest.py:46` 一致），不引入真实书名/人物 |
| §2 技术栈 | LLM/embedding/向量库锁定 | 长度控制仅新增数值配置项，不涉及任何模型更换；摘要收编只是调用位置移动 |
| §3 存储与路径 | 小说数据在仓库外 `NOVEL_DIR` | 无新增存储路径；构思进 run record（既有 `.agent/runs/`）；`NOVEL_TARGET_WORDS` 走 `.env`（同现有 env 命名规范） |
| §4 glm-5.2 推理预算 | 短输出 ≥1024、长输出 4096 | `summarize_chapter` 保持 `max_tokens=1024`；writer/polisher 保持 4096；长度目标 vs 推理预算的挤压风险见 design §6 |
| §5 模块边界 | 依赖注入、agent 不 import cli、纯函数优先、`PipelineState` 与 `WorkingMemory` 不可混名 | 摘要/对比方法挂 `NovelAgent`；构思解析为 `agent.py` 模块级纯函数（同 `_strip_polisher_meta` 先例）；cli 不再触碰 `llm` 与 prompt 常量；新增的是 `PipelineState.outline`，不动 `WorkingMemory` |
| §6 开发流程 | spec-kit 三件套 | 本目录即三件套 |
| §7 验收纪律 | 单测绿、不破基线、严禁后阶段指标前移 | 全部测试用 `FakeLLM`/`FakeRag`/`monkeypatch`，不联网；端到端「实际产出 2000+ 字」是模型行为，不在单测断言（见非目标 8） |
