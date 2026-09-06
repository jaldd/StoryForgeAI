# 阶段 1 后半：文风闭环（style-loop）- 设计

> 对应需求：同目录 `requirements.md`（B1-B20）。
> 前置：`specs/quality-gate/design.md` 已实现（T1-T11）--本文引用其决策编号（D1-D12/Z1-Z10）与模块（checker/partial/state 留痕模式）。
> 行号引用基于 2026-08-30 代码（quality-gate 完成态）。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| B1-B8 学人味（滚动注入） | §3.1 滚动窗口加载 + writer prompt 追加分节 |
| B9-B17 去 AI（人味重写 pass） | §3.2 deai_refine + §3.3 调用时序 |
| B18-B20 兼容与预算 | §3.5 双降级 + §3.4 预算归属 |

## 1. 总体设计

流水线拓扑**零改动**（writer -> polisher -> checker -> reviewer + fixer 打回环，quality-gate 终态）。本 feature 是两个**旁挂**能力：

```
（1.5 滚动注入，防）                          （1.6 de-AI pass，治）
_build_agent ──滚动最近N章──> writer prompt     流水线 done
                                              │ 纯代码 ai_flavor_score（零评委）
                                              ▼ 超 deai.threshold
                                          deai_refine（复用 fixer 管线，换人味 prompt）
                                              │ 复检分下降 -> 接受 / 否则回退
                                              ▼
                                          evaluate -> 门禁 -> 存盘（既有，不动）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `checker.run_checks`（结构化 issue + quote） | de-AI 的问题句定位输入 |
| `checker.ai_flavor_score` / `load_baseline` | de-AI 的触发判定与复检标尺 |
| `agent._fixer` 的段落定位/spans/标记协议解析/字数保护/`apply_replacements` | deai_refine 的回填管线（抽共用，见 §3.2） |
| `prompts._exemplar_files` 同款目录遍历 | 滚动窗口的文件枚举 |
| quality-gate 的 `human_text_subpath` 配置 | 滚动注入指向同一目录（不新增目录配置） |

## 2. 配置面（新增 2 个 env + 1 个规则键，其余不动）

| 变量/键 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_STYLE_RECENT_N` | 滚动注入取最近 N 章人工正文 | `3` | int，`0` = 禁用注入 |
| `NOVEL_STYLE_SLICE_CHARS` | 每章注入截断（取前 N 字） | `1000` | int，`0` = 不截断 |
| `质量规则.json` 新增 `"deai"` 键 | de-AI pass 开关与触发阈值 | 无键 = 不启用 | `{"enabled": true, "threshold": 60}` |

设计口径：目录复用 `NOVEL_HUMAN_TEXT`（quality-gate 已建，AI 味基准同一语料库--统计与注入同源，改目录两边同时生效，符合「人工正文是唯一真源」）；滚动参数是**写作侧**行为，归 env 而非规则 JSON（对齐 exemplar 相关配置先例）。

## 3. 详细设计

### 3.1 滚动注入（1.5，B1-B8）

**加载函数**（`prompts.py` 模块级，纯函数，与 `load_exemplar` 同居）：

```python
def load_recent_human(
    dir_path: str | Path,
    n: int = 3,
    slice_chars: int = 1000,
    progress=print,
) -> str:
    """滚动文风注入语料：人工正文目录按文件名序取尾部 n 个，每个截前 slice_chars 字。

    - 目录不存在 / n<=0 / 无 .txt/.md 文件 -> ""（B2 降级，零误伤）；
    - 每章超 slice_chars 截断并 progress 留一行（B4，不静默）；
    - 输出形如多段拼接（章与章间 \n\n 分隔），不带分节标题（分节在 writer_system 模板）。
    """
```

- **章序约定（Z1）**：`sorted(iterdir())` 字典序即注入序，取**尾部** n 个（最近优先）。save_chapter 的「第NN章-标题.md」命名零填充数字天然字典序=章序；命名不规范时窗口可能取错--接受（确定性优先，目录归用户管）。
- **截断取前**（每章头 slice_chars 字）：开篇最见笔性（定调、节奏、视角），且实现最简（无中段抽取的任意性）。

**注入点**（B5：仅 writer）：

- `writer_system(novel_name, retrieved, exemplar, instruction, rules, recent_human="")` 增第 6 参（默认空串，既有调用零改动）：

```
【风格范例】
{exemplar}

【近期人工正文】（学笔性与节奏，不是情节指令，不要模仿其中情节）
{recent_human}
```

分节标题自带防混淆语义（B8）；空串时整块不占位（对齐 `_rules_block` 的空不占位先例）。

- `NovelAgent.__init__` 增 `recent_human: str = ""`，`_writer` 传参（polisher/reviewer 的 system 构造零改动，B5）。rewrite 走 `_writer` 天然生效；refine 无 writer 不注入（Z5）。
- `cli._build_agent`：exemplar 加载之后调 `load_recent_human(settings.human_text_full, settings.style_recent_n, settings.style_slice_chars)`（仅当 `human_text_subpath` 已配置）。

**状态命令**（B6，`_do_status`）：人工语料行下追加一行：

```
滚动注入：最近 3 章 · 每章 1000 字（未找到文件 -> 「滚动注入：人工语料为空，本次不注入」）
```

### 3.2 de-AI pass（1.6，B9-B17）

**架构拍板（D1）：旁挂方法，不做第六角色。** pass 的触发依赖 AI 味分（需 rules+baseline 上下文）且发生在流水线 done 之后，不是状态机一环；挂 `NovelAgent.deai_refine`（LLM 边界内只做重写+回填），触发判定与接受判定在 cli 层（与 evaluate/门禁同层，质量判定归一处）。

**管线复用（D2）：与 `_fixer` 抽共用子过程。** `_fixer` 的「定位 -> spans 合并 -> 单次调用 -> 标记协议解析 -> 逐段回填 + 字数保护」整段逻辑对 deai 复用，差异仅两处：

| | fixer（quality-gate） | deai_refine（本 feature） |
|---|---|---|
| prompt | `fixer_system`（按意见修复） | `deai_system`（人味重写，见下） |
| 不可定位 issue | 整文降级（D12） | **丢弃**该 issue（B10 只传问题句是硬约束；全部不可定位 -> 跳过 pass，B17） |

实现形态：把 `_fixer` 的「定位+spans+调用+回填」抽为私有方法 `_fix_spans(text, issues, system, user_builder) -> tuple[str, int]`（返回新文本与实际改写段数），`_fixer` 与 `deai_refine` 共用（fixer 保留整文降级分支，deai_refine 预先过滤不可定位 issue）。`_parse_fixer_output`、`fixer_user` 的 spans_data 结构直接复用。

**de-AI prompt**（`prompts.py` 新增，纯构造函数）：

```python
def deai_system(novel_name: str, rules: str = "") -> str:
    """人味重写师：只改表达不动情节，目标是压 AI 味。"""
    # 铁律：1. 情节/人称/称呼/伏笔/段落结构一个字不动语义
    #      2. 只改问题段，其余原样（标记协议同 D11）
    # 风格指令：短句为主、克制留白、不解释因果、具体物象优先、去副词堆叠
    # 输出协议：复用【第N段·修复后】标记（与 fixer 同协议，解析器零新增）

def deai_user(spans_data: list) -> str:
    """与 fixer_user 同构（before/text/after/issues），文案改为「人味重写」。"""
```

不注入 exemplar/人工正文进 deai prompt（D3）：意见已指明机械问题（哪个词、哪句超长），重写依据 = 模型对自然中文的先验 + 风格指令四条；再塞语料徒增 token（宪法 §4）。SKILL.md 的文风维度描述收编进风格指令。

**触发与接受判定**（cli 层，`_do_write` 内）：

```python
# 流水线 done 之后、save_run 之前（D4 时序，见 §3.3）
rules = load_quality_rules(settings)
deai_cfg = (rules or {}).get("deai") or {}
if deai_cfg.get("enabled") and state.final_chapter:
    baseline = load_baseline(settings)
    before = ai_flavor_score(state.final_chapter, rules, baseline)["score"]
    if before > deai_cfg.get("threshold", 60):
        issues = [i for i in run_checks(state.final_chapter, rules)
                  if i.get("quote") and i["quote"] in state.final_chapter]  # 只取可定位（B10/B17）
        if issues:
            new_text, n_spans = agent.deai_refine(state.final_chapter, issues)
            after = ai_flavor_score(new_text, rules, baseline)["score"]
            accepted = after < before                        # D5：严格小于才接受（早期规划原话）
            if accepted:
                state.final_chapter = new_text
            state.deai = {"before": before, "after": after,
                          "spans": n_spans, "accepted": accepted}   # B14 留痕
        else:
            state.deai = {"before": before, "skipped": "无可定位问题句"}
    # 未超阈值：不留痕不空跑（B17）
```

- **D5 比较口径**：`after < before` 严格小于。持平/上升一律回退保留原稿（防越改越糟；blacklist 组件使分不降时大概率 LLM 把词写回来了，回退正确）。
- **Z4：接受后不重跑 checker**。复检用的 `ai_flavor_score` 含 blacklist 组件--分没降就不接受，天然兜住「改完又把黑名单词写回来」；重跑 checker 是多余状态机耦合。
- **预算（B19/D6）**：每章至多**一轮** pass，不循环、不占 `review_count`（那是打回预算；pass 是存盘前终处理，无打回语义）。触发判定与复检均纯代码零 LLM；pass 本体恰一次 `writer_llm` 调用（合并 spans，A11 同款纪律）。

### 3.3 调用时序（D4：pass 在 save_run 与 evaluate 之前）

`_do_write` 终态序：

```
流水线 done
  -> de-AI 判定+pass（§3.2，纯代码触发 + 恰一轮 LLM）
  -> save_run（record 的 final_state 已含 deai 留痕键与改后稿）
  -> evaluate（评委恰好一次，评的就是 de-AI 后的终稿）
  -> 门禁判定（eval_gate，不动）
  -> 存盘（向量库/摘要照常）
```

理由：评委一次都不多烧（token 预算，宪法 §4）；record 落盘即终态（deai 键 + final_chapter 同源，无二次 save_run）；弃稿路径数据不丢（save_run 仍在 evaluate 前，A31 口径延续）。

**留痕形状（B14）**：`PipelineState` 增 `deai: Dict[str, Any] = field(default_factory=dict)`（A4 同款模式），`asdict` 自动进 steps/final_state；replay 消费未知键零崩溃（A37 精神，replay 不特意展示，json 查得到）。`config` 增 `style_recent_n` 布尔？不增（滚动注入属输入语料非行为开关，record 已有 quality_rules 布尔足够，避免 config 膨胀）。

### 3.4 手动命令（B15/D7）：`去AI <文件路径>`

```
去AI <文件路径>   对已存章节手动跑人味重写（改前改后分数对比，确认后存回）
```

流程（对齐 `精修` 的交互骨架，但**不落 run record**--D8：它不是流水线 run，人是标尺当场拍板，留痕=文件本身+REPL 输出）：

读文件 -> `run_checks` 定位 -> `agent.deai_refine` -> 前后 `ai_flavor_score` 对比展示（分不降也如实展示，**人不被阈值绑架**，Z3）-> y/n 确认 -> 存回 + `rag.add_document` 更新索引（同 refine 尾处理）。

- 不设阈值门槛（自动 pass 要阈值防滥烧；手动是人发起，直接跑）。
- 无可定位问题句时打印提示退出（不空烧）。

### 3.5 双降级（B18/B20）

- `NOVEL_STYLE_RECENT_N=0`（或默认未配目录）-> `load_recent_human` 返回 ""，writer prompt 与现状逐字节一致。
- `质量规则.json` 无 `deai` 键（或 enabled falsy）-> `_do_write` 的 de-AI 分支整体短路，零行为变更。
- 旧 run record（无 `deai` 键）-> replay/compare/run_tests 全部 `.get` 容错（quality-gate A37 同款纪律）。

### 3.6 run_tests（B16 情节保真的落点）

- 机械保真代理 = 既有断言天然覆盖：run_tests 的称呼红线/意图断言作用于 `final_chapter`（de-AI 后的稿）--意图词丢失会被「意图：含'X'」抓住，称呼红线同理。
- 逐字节不变（区间外）与字数保护是回填机制的属性，归 `test_agent` 单测（FakeLLM 场景直断言）。
- 新增一条：`final_state.deai` 存在且 `accepted` 时，断言 `deai.after < deai.before`（留痕自洽性，防 record 造假）。

## 4. 不动清单（防漂移）

- `_fixer` 的对外行为与整文降级语义（共用抽取是内部重构，fixer 调用点零改动）。
- exemplar 精选清单（0.5b）与样文路由（exemplar-routing）。
- `改` 命令交互（partial.py 对外行为零改动）。
- evaluate/门禁/回测（harness 与 `_gate_ok`/`_gate_confirm` 全部不动）。
- checker 五项检查与 AI 味三组件公式（只消费不修改）。
- `EVALUATOR_RUBRIC`、LLM 配置面、温度/max_tokens 既有值（deai 调用走 `writer_llm` + 4096 档 + temperature 0.5，对齐 fixer 的 Z3）。
- RAG 索引策略（滚动注入直接读文件，不入库不检索）。
- `py/`、Java 侧。

## 5. env 变量表（新增两个，其余不动）

见 §2。`.env copy.example` 追加「文风闭环（1.5/1.6）」注释段：两个 env（含义/默认/0=禁用）+ `质量规则.json` 的 `deai` 键说明（含「无键 = 不启用」）。

## 6. 实现注意（坑位）

- **`load_recent_human` 的「尾部」**：`sorted()[-n:]`；n 大于文件数时全取。返回前逐文件截断（不是拼接后截断，保证每章都有头部内容而非第一章吃满预算）。
- **空文件/不可读文件**：`read_text` 失败 progress 提示后跳过（`load_exemplar` 同款纪律），窗口照常推进。
- **`_fix_spans` 抽取的回归风险**：`_fixer` 抽共用后必须保持既有 fixer 测试全绿（A8-A15 用例是护栏）；deai_refine 的过滤逻辑（丢不可定位）只作用于 deai 路径。
- **`state.deai` 与 steps 快照**：`_run_loop` 的 `asdict(state)` 在 pass 之前已结束（pass 在流水线外），故 deai 键只出现在 final_state，不进 steps--符合语义（pass 不是一步角色）。
- **`_do_write` 里 pass 异常**：deai_refine 抛异常（LLM 故障）时 catch 打印、保留原稿继续走（pass 是优化器，失败不阻断主流程；对齐「评测跳过」的既有容错口径）。
- **测试缝**：cli 层测试 monkeypatch `cli.ai_flavor_score`（固定 before/after 分）+ `cli.run_checks`（构造 issues）+ `cli.load_baseline`（None），与既有 `_gate_confirm`/`evaluate` 缝同模式。
- **manual 命令与 `_build_agent`**：`去AI` 不需要 exemplar/滚动语料，但 `_build_agent` 现加载它们--直接复用无妨（构造副作用只是读文件）；RuntimeError 捕获同既有四个命令（A23 模式）。

## 7. 测试策略（全程不联网）

- **test_prompts.py**：`load_recent_human` 纯函数五态（尾部 N、每章截断、n=0 空串、目录不存在空串、不可读文件跳过）；`writer_system` 含 recent_human 分节标题与「不是情节指令」文案；`deai_system` 文案断言（风格指令四条 + 标记协议说明）。
- **test_agent.py**：`deai_refine`（FakeLLM 按标记协议返回重写段；区间外逐字节不变；未返回段回落原文；字数保护触发保留原段；输入全为不可定位 issue 时由 cli 层保证不进 agent，单测断言 deai_refine 对空 issues 返回原文零调用）；`_fixer` 抽取后既有用例全绿（回归护栏）。
- **test_cli_write.py**：`_do_write` 的 de-AI 链五路（超阈值+分降->接受、final_chapter 为改后稿+state.deai 留痕；超阈值+分不降->回退保留原稿；未超阈值->零调用零留痕；未配置 deai 键->零行为；无可定位句->skipped 留痕）；`去AI` 命令冒烟（monkeypatch 固定分 + confirm y/n 两路、存回与索引更新）。
- **test_harness.py**：run_tests 对含 deai 键的 record 断言 `after < before`（accepted 时）；旧 record（无键）不受影响。
- **test_config.py**：两个新 env 解析（默认值/覆盖/0 值）。
- **回归命令**：`cli/` 下 `python -m pytest tests/ -q`；基线 3 存量失败（同 quality-gate 验收口径），零新增。

## 8. 决策表

### 8.1 继承决策（早期规划已拍板）

| # | 决策 | 理由 |
|---|---|---|
| R1 | 阶段 1 拆两个 feature，本为后半 | 开放问题 3（2026-08-29 关闭） |
| R2 | 滚动窗口 + 固定精选，不用语义检索 | 阶段 1.5 规划：主题相似≠文风相似 |
| R3 | 只传问题句不传整章 | 阶段 1.6 规划 + 宪法 §4 token 预算 |
| R4 | AI 味分下降才接受 | 阶段 1.6 规划原文 |

### 8.2 设计决策（本 design 拍板）

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | de-AI 架构 | a) 流水线第六角色；b) 旁挂方法 | **b** | 触发依赖 AI 味分上下文且在 done 之后；不做状态机一环 |
| D2 | 管线复用 | a) deai_refine 自写一套；b) 与 _fixer 抽共用子过程 | **b** | 定位/回填/字数保护逻辑全同，两套实现必漂移 |
| D3 | deai prompt 不注入语料 | a) 注入 exemplar 片段 | **不注入** | 意见已机械定位问题；再塞语料徒增 token |
| D4 | pass 时序 | a) evaluate 后（改完稿评委分已旧）；b) save_run 与 evaluate 前 | **b** | 评委一次不多烧且评终稿；record 落盘即终态 |
| D5 | 接受口径 | a) after < before；b) 降 N 分以上 | **a** | 早期规划原话「必须下降」；幅度阈值无数据支撑（T12 同理） |
| D6 | 预算归属 | a) 占 review_count；b) 独立每章一轮 | **b** | pass 无打回语义；一轮封顶防空转 |
| D7 | 手动命令落 record | a) 轻量 record；b) 不落 | **b** | 非流水线 run；人是标尺当场拍板，文件即产物 |
| D8 | 不可定位 issue 处理 | a) 整文降级（fixer 同款）；b) 丢弃 | **b** | B10 只传问题句是硬约束；de-AI 是优化器可挑食（fixer 服务打回语义必须全消费，两角色差异点） |

### 8.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | 滚动「章序」= 文件名字典序，取尾部 n 个 | save_chapter 零填充命名天然序；确定性优先，目录卫生归用户 |
| Z2 | deai.threshold 无数据先不设全局默认，配置缺失即不启用 | 对齐 quality-gate「先上线后校准」节奏（A29/T12 同哲学） |
| Z3 | 手动命令不设阈值门槛 | 人发起人是标尺；自动路径要阈值防滥烧，两口径分家 |
| Z4 | 接受后不重跑 checker | 复检的 blacklist 组件已兜住词回写；再加状态机耦合是过度设计 |
| Z5 | 滚动注入只经 `_writer`，refine 天然不注入 | refine 无 writer；注入目标是「写新文风」不是「润旧稿」 |
| Z6 | config 不增 style 相关布尔 | 滚动注入是输入语料非行为开关，record 已有 quality_rules 布尔够用 |
