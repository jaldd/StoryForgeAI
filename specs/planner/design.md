# 阶段 3.3：章节规划师（planner）- 设计

> 对应需求：同目录 `requirements.md`（P1-P12）。
> 前置：3.1 `foreshadow`、3.2 `character-arc` 已实现（537 passed 基线，
> 2026-09-05 实测）；本 feature 消费其 working memory 快照。
> 行号锚点基于 2026-09-05 代码（volume-align 完成态），实现时以函数名为准。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| P1/P6 规划回路与留痕 | §3.1 `_planner` 真角色 + run() 起点 |
| P2/P7/P8 构思前移与消费 | §3.2 outline 复用 + writer 分支 |
| P3 降级 | §3.3 空回回落（经 P7 条件自然衔接） |
| P4/P12 兼容与可发现性 | §3.5 开关默认关 + 状态命令 |
| P5 输入汇合 | §3.1 prompt 构造 |
| P9 范围外 | §4 已知局限 |
| P10/P11 配置与预算 | §2 配置面 + §3.4 预算文案 |
| P13-P16 rewrite 接 planner（T8） | §3.6 起点分支 + prompt 变体（writer 零改动） |

## 1. 总体设计

流水线拓扑加一个**前置起点分支**，writer 之后的链路零改动：

```
run(task, plan)
  └─ PipelineState(task, plan)
       next_agent = "planner"（NOVEL_PLANNER=1）| "writer"（默认，现状）
            │
       ┌────▼─────────────────────────────┐
       │ _planner（新角色）                  │
       │  输入：task + plan + working_context │
       │        + _retrieve(task) + 字数     │
       │  输出：节拍 markdown -> state.outline│
       └────┬──────────────┬───────────────┘
            │ 有节拍         │ 空回（P3 降级）
            ▼               ▼
       writer（节拍模式）  writer（现状模式：自行构思 + 章纲直注）
            └───────┬───────┘
                    ▼
       polisher -> checker -> reviewer -> fixer（零改动）
       （polisher/reviewer 经既有 outline_hint 消费节拍）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `state.outline`（0.8 构思传递链） | 填充者从 writer 换成 planner；polisher/reviewer 既有 hint 消费面零改动 |
| `_working_context()`（伏笔/弧光快照注入） | planner 同款注入（汇合点） |
| `_retrieve(task)`（RAG 检索） | planner 同款全量口径（设定/人物/前文） |
| `_temp(kind)` 温度链 | 新 kind `planner`，归写作侧（吃 NOVEL_TEMPERATURE 兜底） |
| agents map + `_run_loop` steps 留痕 | planner 进 map 即自动留痕（P6 零成本） |
| `writer_llm`（0.7 写作侧来源） | planner 走它（创作类调用） |
| 2.2 `state.plan` 章纲注入 | planner 消费章纲产节拍；writer 侧注入条件收窄（D7） |

## 2. 配置面（新增 2 个 env）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_PLANNER` | 规划角色开关 | `0` | int，`1` = run 路径先规划再写（D4 opt-in） |
| `NOVEL_PLANNER_TEMPERATURE` | 规划调用温度 | `0.5` | float，走 `_temp("planner", 0.5)`，写作侧链 |

## 3. 详细设计

### 3.1 planner 角色（P1/P5/P6）

`agent.py`：

- agents map 增 `"planner": self._planner`（refine_agents 不含它，P9 天然成立；
  rewrite 起点恒 "writer"，planner 不触发）。
- `run()` 构造 state 后：`if self.settings.planner_enabled:
  state.next_agent = "planner"`。
- `_temp` 写作侧 tuple 增 `"planner"`：`("writer", "polisher", "fixer",
  "planner")`。

```python
def _planner(self, state: PipelineState) -> None:
    """规划师：汇合章纲/伏笔/弧光/长度目标，产出本章节拍（先于 writer）。"""
    print("  📋 规划节拍中（约20秒）...")
    retrieved = self._retrieve(state.task)
    system = planner_system(
        self.novel_name, retrieved, self.instruction, self.rules,
    ) + self._working_context()
    try:                                    # Z4：chat 包 try/except（§3.3）
        raw = self.writer_llm.chat(
            system,
            planner_user(state.task, state.plan, self.target_words),
            max_tokens=2048,                # Z1：宪法 §4 推理预算
            temperature=self._temp("planner", 0.5),
        )
    except Exception as e:                  # 异常视同空回降级，不中断 run
        raw = ""
        state.log.append(f"[planner] ⚠️ 节拍规划调用失败：{e}")
    beats = _strip_code_fence(raw or "").strip()
    if beats:
        state.outline = beats
        state.log.append(f"[planner] 节拍完成，{len(beats)} 字")
    else:
        state.log.append("[planner] ⚠️ 节拍规划未返回内容，回落 writer 自行构思")
    state.next_agent = "writer"
```

- **节拍格式（D3）**：自由 markdown，prompt 要求必含四要素（场景序列含
  字数分配 / 伏笔操作（收旧+埋新）/ 角色弧光推进 / 结尾钩子），软约束。
  无 JSON 解析面——空回即降级，无「半份节拍」状态。
- **prompt（prompts.py 新增）**：

```python
PLANNER_SYSTEM = f"""你是小说《{novel_name}》的章节规划师（planner）。
职责：写作前把章纲要点、未回收伏笔、角色当前弧光阶段、目标字数汇合成
本章节拍表——writer 按它写，reviewer 拿它当验收基准。
要求：具体、可执行、不写空话；场景与事件不得违背设定与铁律。
{_rules_block(rules)}{_instruction_block(instruction)}{retrieved}"""

def planner_user(task, plan, target_words) -> str:
    # 任务 + 章纲（如有）+ 四要素清单 + 「只输出节拍表，不要写正文」
```

- exemplar / recent_human 不进 planner（节拍不学文风，学的是结构）。

### 3.2 构思前移与 writer 分支（P2/P7/P8）

- **outline 复用（D2）**：节拍存 `state.outline`，字段注释更新为
  「planner 节拍（planner 开且成功）或 writer 构思（其余情况）」。
  polisher/reviewer 的既有 `outline_hint` 消费面零逻辑改动。
- **writer 分支条件（D6）**：由 `state.outline` 是否已填决定，与开关解耦：

```python
# _writer 内
plan_block = ""
if state.plan and not state.outline:      # D7：节拍已消化章纲，不双注入
    plan_block = ...
beats_block = ""
if state.outline:
    beats_block = (f"\n\n【本章节拍（planner 规划，按此展开写作）】\n{state.outline}")
# user_msg 构思请求行二选一：
#   outline 已填 -> 「请直接写正文，不要再写构思说明。」
#   outline 空   -> 现状「请先用一段话说明构思……=== 分隔……」（含 rewrite 分支同款）
...
outline, body = _split_writer_output(raw or "")
if not state.outline:                      # P8：planner 节拍是唯一真源
    state.outline = outline
state.draft = body
```

- planner 失败（outline 空）→ writer 自然走现状分支（请求构思 + 章纲直注），
  **降级零额外代码**（P3 由 P7 的统一条件承接）。
- polisher/reviewer 的 hint 文案中性化（Z3）：「writer 构思」→
  「本章构思/节拍」（两处字符串，行为零变化）。

### 3.3 降级与边界（P3/P9）

- planner 空回/异常：`_planner` 内空回走 log 警告；**调用异常**（网络等）
  由 `_run_loop` 既有行为兜底吗？——否：`_run_loop` 无 try/except，异常会
  中断整次 run。**planner 的 chat 调用包 try/except**，异常视同空回降级
  （规划是增强，失败不应阻断写作；同「检索失败不阻断」纪律）。
- refine（无 writer）：不接 planner（P9，精修无结构决策）。
- rewrite（有 source_content）：接 planner（T8，§3.6）。
- 首章（working memory 空）：`_working_context()` 返回空串，planner 纯靠
  task + 检索产节拍，无害。

### 3.4 预算文案（P11）

`_do_write_batch` 的固定文案改动态：

```python
calls = "9-12" if settings.planner_enabled else "8-11"
f"（每章约 {calls} 次 LLM 调用，注意 token 预算）"
```

默认关 → 既有断言（8-11）零变更。

### 3.5 可发现性（P12）

- `_do_status` 增一行：`planner：开（节拍规划）/ 关`。
- `.env copy.example` 增「章节规划师（planner）」注释段：开关、行为
  （先规划再写/节拍进 run record/reviewer 验收基准）、降级说明、
  与章纲的关系（章纲是原料、节拍是成品）、token 成本提示。

### 3.6 rewrite 路径接 planner（T8，P13-P16）

真车证据：重写第40章（无节拍）打回两轮整文修复；写第41章（有节拍）一次
过审。重写比新写更需要节拍——writer 盲写而 reviewer 持验收基准，第一次
打回是必然。

**改动面（三处，writer 侧零改动）**：

1. `rewrite()` 起点分支（agent.py）：

```python
state = PipelineState(task=task)
state.source_content = content
if self.settings.planner_enabled:
    state.next_agent = "planner"  # T8：重写先规划（节拍基于原文结构）
else:
    state.next_agent = "writer"   # 现状（P16）
```

2. `_planner` 透传 source_content（agent.py）：

```python
planner_user(state.task, state.plan, self.target_words, state.source_content)
```

3. `planner_user` 增可选参数 `source_content=""`（prompts.py）：非空时注入
   【原文（重写参考）】块 + 重写模式指令（基于原文结构产节拍：提取原文
   场景序列 → 逐场景标注处理方式（保留/重排/合并/增强/删除）→ 保留核心
   意图与既有伏笔，不从零规划）；为空时输出与本 feature 前逐字节一致
   （P16，run 路径零波及）。四要素清单两模式共用。

**writer 侧零改动（D11）**：`_writer` 的 rewrite 分支（source_content 非空）
已按「outline 是否已填」二选一（P7 统一条件）：planner 成功 → beats_block
注入 +「直接写正文」；planner 关/失败 → 原文参考 + 自行构思（现状）。
代码路径共用，T8 不动 writer。

**降级（P15）**：`_planner` 既有 try/except + 空回 log 警告天然覆盖（Z4
同款），rewrite 无新增降级代码——planner 失败后 outline 为空，writer 的
rewrite 分支自然走现状。

**steps 留痕**：rewrite 的 record steps[0] 为 planner（开关开时），replay
可见当时按什么节拍重写（`_run_loop` 既有机制，零成本）。

**预算**：rewrite + planner = +1 次大输入调用（原文全文进 planner 输入，
与 writer 的 rewrite 输入同量级）；对照真车两轮整文修复（约 4-6 次额外
调用），+1 划算。

## 4. 已知局限与不动清单

**已知局限**（真车数据说话后再议，不在本 feature 修）：

- ~~rewrite 不接 planner~~（已实现，T8/§3.6，2026-09-05 真车证实价值后提前）。
- **节拍质量无机器验收**：reviewer 软判定「正文是否实现节拍」；结构化
  schema + harness 断言节拍覆盖率留 P1（T9）。
- **每章 +1 次大输入调用**：planner 输入含全套检索 + 工作记忆（同 writer
  口径），token 成本约 +15%；价值假设（节拍提升质量、减少整章返工）需
  真车 A/B 验证（T10），验证后再议默认开。
- **节拍与 writer 执行偏差**：writer 可能偏离节拍（LLM 自由度），reviewer
  是唯一防线；打回 fixer 修的是正文不是节拍。
- **planner 可能未完全消化章纲**：D7 下 writer 不再看到原始章纲（节拍已
  消化），planner 漏掉某条要点时 writer 无兜底，只能靠 reviewer 事后发现；
  T10 A/B 校准时关注节拍对章纲的覆盖率。

**不动清单**（防漂移）：

- writer 之后的流水线拓扑（polisher->checker->reviewer->fixer）。
- refine/rewrite 路径与 `_refine_postprocess`。
- 伏笔/弧光抽取回路（planner 只读快照，不写 working memory）。
- `state.plan` 章纲解析链（`_load_chapter_plan`/`parse_chapter_plan`）。
- working memory 结构与落盘链路。
- `save_chapter`/RAG 入库/批量编排的结局判定。

## 5. 实现注意（坑位）

- **writer 的 rewrite 分支也要适配**：`source_content` 非空时 user_msg 的
  构思请求行同样按 outline 二选一（rewrite 不跑 planner，outline 恒空，
  行为不变——但代码路径共用，条件写对即可）。
- **`_split_writer_output` 残余 ===**：planner on 时模型仍可能输出 ===，
  === 前文字被丢弃（现状同款语义：那本就不该有），outline 不被覆盖（P8）。
- **steps 留痕体积**：planner 步骤的 output_state 含节拍全文（几百字），
  record 体积可控；input_state 的 outline 为空、output_state 非空，replay
  可精确看到节拍诞生点。
- **温度链归类**：`planner` 进写作侧 tuple 后吃 `NOVEL_TEMPERATURE` 兜底
  （用户全局调温时规划跟着调，符合直觉）。
- **planner 不走 streaming**：节拍是结构化 markdown 非正文，无需逐 token
  输出（有意识的决定，非遗漏）；`on_delta` 不传。
- **文案中性化的测试影响**：grep 既有断言是否依赖「writer 构思」字样
  （polisher/reviewer hint），有则同步更新（文案适配，行为零变化）。

## 6. 测试策略（全程不联网）

- **test_agent.py**：agents map 含 planner；`run()` 起点按开关（on ->
  planner / off -> writer）；`_planner` 填 outline + log + next_agent；
  空回降级（outline 空 + 警告 log + next_agent=writer）；chat 异常降级
  （try/except 承接）；writer 分支（outline 已填 -> prompt 含节拍块且无
  构思请求、plan_block 不注入；outline 空 -> 现状 prompt）；P8（writer
  输出 === 不覆盖 planner 节拍）；温度链（planner_temperature >
  NOVEL_TEMPERATURE > 0.5）；max_tokens=2048；planner prompt 含
  working_context 与章纲；rewrite 路径 outline 恒空。
- **test_config.py**：两 env 默认值与覆盖；`NOVEL_PLANNER=0` 解析 False。
- **test_cli_write.py**：集成（planner on 全链路：steps[0] 是 planner、
  final_state.outline = 节拍、reviewer 收到节拍基准）；planner off 现状
  （steps 无 planner）；批量预算文案（on 9-12 / off 8-11）；`状态` 命令
  开关行。
- **T8 rewrite（test_agent.py）**：rewrite + planner on → steps[0] 是
  planner、planner_user 收到 source_content、节拍进 outline、writer 的
  rewrite user_msg 含节拍块且无构思请求；rewrite + planner off → 现状
  （next_agent=writer、无 planner 步骤、user_msg 含原文参考 + 构思请求）；
  rewrite + planner 空回 → 降级 log + writer 现状分支；refine 不受影响
  （refine_agents 无 planner）；planner_user 无 source_content 时输出与
  现状逐字节一致（P16）。
- **回归**：`cli/` 下 `python -m pytest tests/ -q`，**537 passed / 0 failed /
  1 deselected**（2026-09-05 基线）+ 新增约 20 条，零新增失败。

## 7. 决策表

### 7.1 继承决策（早期规划/用户已拍板）

| # | 决策 | 理由 |
|---|---|---|
| R1 | planner = director 的回归形态（真决策角色，非转发器） | 阶段 3.3 规划；0.8 删空壳 director 的回归闭环 |
| R2 | 构思从 writer 前移到 planner，一次生成、处处消费 | 阶段 3.3 规划原文；0.8 已建好 outline 传递链，本 feature 换填充者 |

### 7.2 设计决策（本 design 拍板）

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | planner 形态 | a) run() 前旁挂调用；b) 状态机真角色 | **b** | steps 留痕天然进 record（P6 零成本）；与既有角色同构；降级经 next_agent 自然衔接 |
| D2 | 节拍载体 | a) 新增 state.beats；b) 复用 state.outline | **b** | 「构思前移」字面实现；polisher/reviewer 消费面零改动；备选被否：双字段注入点翻倍、语义分裂 |
| D3 | 节拍格式 | a) 结构化 JSON；b) 自由 markdown | **b** | 创作产物表达力优先；无解析失败面（空回即降级）；消费者是 LLM 非机器。结构化留 P1（harness 断言需求出现再议） |
| D4 | 开关默认 | a) 默认开（同 foreshadow/arc）；b) opt-in 默认关 | **b** | 改变流水线形状 + 每章 +1 大输入调用；价值假设需真车 A/B（compare 可比）；volume-align Z1 同款哲学，一行回退 |
| D5 | planner 走哪个 LLM | a) 主 llm（判定类）；b) writer_llm（创作类） | **b** | 节拍直接喂 writer，属写作侧 token 大头（0.7 路由收益面）；温度链归写作侧 |
| D6 | writer 行为切换条件 | a) 按 planner 开关；b) 按 outline 是否已填 | **b** | planner 失败降级零额外分支；rewrite（outline 恒空）自然现状；条件统一「有节拍 = 按节拍写」 |
| D7 | 章纲注入 writer 条件 | a) 恒注入；b) outline 空时注入 | **b** | planner 成功时节拍已消化章纲，双注入冗余且可能冲突；失败/关闭时章纲直注（现状） |
| D8 | planner 温度默认 | 0.2 / 0.3 / 0.5 / 0.8 | **0.5** | 规划是生成类但求稳定，介于 polisher(0.6) 与 summarizer(0.3) 之间 |
| D9 | rewrite 节拍模式 | a) 从零规划（同 run）；b) 基于原文结构（场景提取→重排/增强） | **b** | 重写的价值在原文参考；从零规划丢弃原文信息，与 writer「参考原文自由重写、保留核心意图」语义冲突；真车打回两轮的根因正是无结构基准 |
| D10 | source_content 注入位置 | a) planner_system 加参数；b) planner_user 加参数 | **b** | 模式差异是任务级（同角色两种任务形态）非角色级；system 签名不动，调用面零波及；run 路径（source 恒空）输出逐字节不变 |
| D11 | writer 适配 | a) rewrite 分支加节拍逻辑；b) 零改动 | **b** | P7 已按「outline 是否已填」统一分支，rewrite 分支天然含 beats_block/draft_request；再改反而破坏统一条件 |

### 7.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | max_tokens=2048 | 宪法 §4 推理预算：节拍几百字但思考计入；同 foreshadow/arc 先例 |
| Z2 | 预算文案动态（off 8-11 / on 9-12） | 默认关 → 既有断言零变更；开时口径诚实 |
| Z3 | polisher/reviewer hint 文案中性化（「writer 构思」→「本章构思/节拍」） | 消费方文案应准确描述来源；行为零变化，断言依赖旧字样则同步更新 |
| Z4 | planner chat 调用包 try/except，异常视同空回降级 | 规划是增强不是门禁，失败不阻断写作（同「检索失败不阻断」纪律）。**实现位置与 foreshadow/arc 不同**：它们在 run 结束后由 CLI 层（`_write_one`）catch；planner 在 `_run_loop` 状态机内运行（run 中），异常会直接中断整个 run，故必须自包 |
