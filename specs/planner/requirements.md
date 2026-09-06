# 阶段 3.3：章节规划师（planner）- 需求

> 需求来源：阶段 3.3 规划条目（长线记忆第三步，director 的回归形态）。
> 最高约束：`.specify/memory/constitution.md`。
> 现状证据与详细设计见同目录 `design.md`；任务分解见 `tasks.md`。
> 前置依赖：3.1 `foreshadow`、3.2 `character-arc` 已实现（本 feature 消费其
> working memory 产出）；0.8 已保留 outline 构思传递链（polisher/reviewer
> 消费面已存在，本 feature 是「一次生成、处处消费」的闭环收口）。
> 条目编号用 P 系列（A/B/T/F/W/C 已被 quality-gate/style-loop/throughput/
> foreshadow/character-arc 占用）。

## 1. 背景与问题

阶段 3.3 规划原文：「汇合 3.1 伏笔、3.2 弧光与长度目标，产出章节节拍（先于
writer）；writer 按节拍写，reviewer 拿节拍当验收基准。构思（0.8 已保留传递）
从 writer 前移到 planner，一次生成、处处消费的数据流闭环。」

现状缺口：

1. **构思是 writer 的副产品**：writer 边构思边写（=== 分隔），构思质量被
   「一次生成正文」的注意力稀释——伏笔该收没收、弧光该推没推，往往写完
   才发现，返工成本整章。
2. **章纲注入是平的**：2.2 的 plan（每章.md 要点）直注 writer prompt，
   没有与未回收伏笔、角色当前弧光阶段汇合——writer 同时看三份材料自行
   调和，调和结果不可见、不可验收。
3. **验收基准弱**：reviewer 拿 writer 自报的构思当基准（自己出题自己改），
   无独立规划层。

本 feature 补上**规划角色**：写作前先由 planner 把章纲 + 伏笔 + 弧光 +
长度目标汇合成章节节拍（场景序列/伏笔操作/弧光推进/结尾钩子），writer
按节拍执行，reviewer 拿节拍当独立验收基准。

## 2. 术语

- **节拍（beats）**：本章的场景级执行规划——场景序列（地点/时间/事件/
  情绪/字数）、伏笔操作（收哪些旧伏笔 + 埋什么新伏笔）、角色弧光推进
  （谁从什么阶段到什么阶段）、结尾钩子。
- **构思前移**：`state.outline` 字段的填充者从 writer 换成 planner（同一
  字段、同一消费面：polisher 意图基准 / reviewer 验收基准 / run record）。
- **EARS**：`当 <条件> 时，系统应 <行为>` 的验收条目格式。

## 3. 验收标准（EARS）

### 3.1 规划回路

- **P1** 当 `NOVEL_PLANNER=1` 且用户发起单章写作（`run` 路径）时，系统应
  先执行 planner 步骤产出本章节拍，再进 writer；planner 是状态机真角色
  （agents map 成员），不是旁挂调用。
- **P2** 当 planner 产出节拍时，节拍应存入 `state.outline`（构思前移）；
  writer 按节拍写且不再被要求自行输出构思；polisher 以节拍为意图基准、
  reviewer 以节拍为验收基准（既有 outline 消费面零新增逻辑）。
- **P3** 当 planner 调用失败/空回时，系统应降级为现状行为（writer 自行
  构思 + 章纲直注 writer），`state.log` 留警告，不阻断写作主流程。
- **P4** 当 `NOVEL_PLANNER=0`（默认）时，系统行为应与本 feature 前完全
  一致（零变化；既有测试零修改，文案适配除外，见 Z3）。
- **P5** 当构造 planner 输入时，应汇合：任务 + 章纲（如有，`state.plan`）+
  工作记忆快照（未回收伏笔 + 角色弧光，含既有 cap 护栏）+ RAG 检索
  （设定/人物/前文，同 writer 口径）+ 目标字数 + 写作指令 + 铁律。
- **P6** 当 planner 步骤执行时，run record 的 steps 应含该步骤
  （input/output state 含节拍全文），replay 可见当时按什么节拍写的。

### 3.2 消费与降级

- **P7** 当 writer 构造 prompt 时，行为应由「outline 是否已填」决定而非
  planner 开关：已填（planner 成功）→ 注入节拍块、不请求构思、章纲不再
  直注（节拍已消化）；未填（planner 关/失败）→ 现状（请求构思 + 章纲直注）。
- **P8** 当 writer 输出仍含 === 构思（模型习惯残余）且 outline 已被
  planner 填充时，writer 不应覆盖 planner 节拍（节拍是唯一真源）。
- **P9** 当 refine 路径执行时，planner 不参与（精修是表达层打磨，无结构
  决策需求；现状不变）。rewrite 接 planner 见 §3.4（T8，P1 提前——真车
  证实价值：重写第40章无节拍打回两轮整文修复，写第41章有节拍一次过审）。

### 3.3 配置与预算

- **P10** 配置面：`NOVEL_PLANNER`（默认 0 = 关）、`NOVEL_PLANNER_TEMPERATURE`
  （默认 0.5，写作侧温度链：单代理键 > `NOVEL_TEMPERATURE` 兜底 > 调用点
  默认）；planner 走 writer_llm（创作类，同 writer/polisher 来源）。
- **P11** 当批量连写且 planner 开启时，每章独立规划（章间工作记忆更新后，
  下一章节拍能看到上一章新埋伏笔与弧光推进）；批量预算提示口径应含
  planner 调用（开 9-12 次/章，关 8-11 次/章）。
- **P12** 当 replay/compare 消费旧 run 记录（无 planner 步骤）时，系统应
  正常工作；`状态` 命令应显示 planner 开关状态（可发现性）。

### 3.4 rewrite 路径接 planner（T8，P1 提前）

> 真车证据（2026-09-05）：重写第40章（无节拍）打回两轮整文修复；写第41章
> （有节拍）一次过审。重写比新写更需要节拍——writer 盲写而 reviewer 持
> 验收基准，第一次打回是必然。

- **P13** 当 `NOVEL_PLANNER=1` 且用户发起重写（rewrite 路径）时，系统应
  先执行 planner 步骤产出本章节拍，再进 writer；节拍应基于原文结构
  （场景提取 → 重排/增强），不是从零规划。
- **P14** 当 rewrite 路径构造 planner 输入时，应包含原文（source_content）
  作为结构参考；节拍应标注对原文各场景的处理方式（保留/重排/合并/增强/
  删除），并保留原文核心意图与既有伏笔的埋设状态。
- **P15** 当 rewrite 路径的 planner 调用失败/空回时，系统应降级为现状
  行为（writer 拿原文参考自行构思），`state.log` 留警告，不阻断重写
  主流程。
- **P16** 当 `NOVEL_PLANNER=0`（默认）时，rewrite 路径行为应与本 feature
  前完全一致（writer 直接起，原文参考 + 自行构思）。
