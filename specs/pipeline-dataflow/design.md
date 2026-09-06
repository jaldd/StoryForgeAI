# 0.8 流水线数据流补漏（pipeline-dataflow）- 技术设计

> 需求见同目录 `requirements.md`（A1-A21）。本文所有行号基于当前工作区实测（2026-08-28 grep），实现时行号会漂移，以符号名为准。

## 0. 需求映射

| 设计节 | 覆盖的 EARS |
|---|---|
| §2.1 director 退役 | A1、A2、A3 |
| §2.2 构思解析与传递 | A4、A5、A6、A7、A8、A19 |
| §2.3 reviewer 前情注入 | A9、A10、A11 |
| §2.4 长度控制归一 | A12、A13、A14、A15 |
| §2.5 剧情摘要收编 | A16、A17 |
| §2.6 P1：工作记忆刷新与对比收编 | A18、A21 |
| §3 失败路径 | A5、A17、A19、A20、A21 |
| §4 兼容性影响 | A3、A6、A20、A1 |

## 1. 现状证据（五大断点）

### 1.1 断点一：空壳 director

| 论断 | 证据 |
|---|---|
| `_director` 是空壳 | `agent.py:211-214`：方法体仅 1 条 log + `state.next_agent = "writer"`，零决策零 LLM 调用 |
| 注册进状态机 | `agent.py:161-166`：`agents` dict 含 `"director": self._director` |
| 默认路由到它 | `state.py:30`：`next_agent: str = "director"`；`run()`（`agent.py:425-438`）构造 `PipelineState(task=task)` 不覆写默认值 |
| 四角色叙述残留 | `agent.py:1` 模块 docstring「director -> writer -> polisher -> reviewer」；`agent.py:126` 类 docstring「四角色状态机编排」；`state.py:19` task 字段注释「Director 收到的写作任务」；`agent.py:450` refine docstring「跳过 director 和 writer」；`agent.py:484` rewrite docstring「跳过 director，直接写」 |

### 1.2 断点二：writer 构思被丢弃

| 论断 | 证据 |
|---|---|
| prompt 要求先构思再正文 | `agent.py:231`（rewrite 分支）与 `agent.py:237`（新写分支）：「请先用一段话说明构思（涉及人物、情绪走向、场景细节），然后用 === 分隔，再写正文。」 |
| 构思被丢弃 | `agent.py:247-251`：`if raw and "===" in raw: state.draft = raw.split("===", 1)[1].strip()`——split 后 `[0]`（构思）无任何变量承接，直接丢失 |
| 行为已被测试固化 | `test_agent.py:276-290` `test_writer_strips_construction_notes`：断言 `state.draft` 不含构思，未断言任何构思去向 |

### 1.3 断点三：reviewer 盲审

| 论断 | 证据 |
|---|---|
| reviewer 不取前文 | `agent.py:338`：`retrieved = self._retrieve(state.task, with_prior=False)`；`_retrieve` 注释（`agent.py:172-173`）明示「reviewer：with_prior=False（只看设定一致性，不管前文风格）」 |
| 工作记忆不注入 reviewer | `_working_context()` 定义于 `agent.py:201-208`，**全代码库唯一调用点是 `_writer`（`agent.py:220`）**；`_reviewer`（`agent.py:322-370`）与 `_polisher`（`agent.py:258-294`）均不调用 |
| 却要审伏笔/时间线 | `prompts.py:139/141`：reviewer 审查维度含「时间线一致性」「伏笔一致性」，而伏笔清单只在 `WorkingMemory.snapshot()`（`memory.py:61-68`）里，reviewer 看不见 |

### 1.4 断点四：长度控制散落且失效

| 论断 | 证据 |
|---|---|
| writer 硬编码字数 | `agent.py:236`：`f"写一段新章节：{state.task}。约200字。"`（仅新写分支；`agent.py:226-233` rewrite 分支无任何长度指令） |
| `target_words` 是死参数 | `prompts.py:119`：`polisher_system(novel_name, retrieved, instruction="", target_words=1500, rules="")`，函数体 `prompts.py:120-129` 对 `target_words` 零引用 |
| 调用点也不传 | `agent.py:262-264`：`polisher_system(self.novel_name, retrieved, self.instruction, rules=self.rules)`——形参从未被实参使用过 |
| 无配置入口 | `config.py`：`Settings` 无任何长度字段（`config.py:64-66` 的编排控制组只有 `max_rounds`/`max_reviews`，且均不经 env 读取） |

### 1.5 断点五：cli 裸调 LLM

| 论断 | 证据 |
|---|---|
| 剧情摘要绕过 agent | `cli.py:136-139`：`summary = agent.llm.chat(PLOT_SUMMARY_SYSTEM, state.final_chapter, max_tokens=1024, temperature=0.3)`，直接持有 `agent.llm` 与 `prompts.PLOT_SUMMARY_SYSTEM`（import 于 `cli.py:33`） |
| 兜底在 cli | `cli.py:140-142`：`except Exception: summary = task` |
| 另一处裸调（对比器） | `cli.py:62-79` `_is_better(llm, ...)`：cli 层内联 system prompt 直调 llm；调用点 `cli.py:194` |
| refine/rewrite 不更新工作记忆 | `cli.py:167-236` `_refine_postprocess` 全函数无 `wm` 引用；调用方 `cli.py:252/288`（总结核为构造处，行号以符号为准）`agent, _ = _build_agent(settings)` 直接丢弃了 wm |

### 1.6 复核勘误（与任务描述的两处出入）

以下两点在 grep 复核后与任务描述原文有出入，按代码现状为准：

1. **「状态机从不路由到 director」不成立**。`state.py:30` 默认 `next_agent="director"` 且 `run()` 不覆写，`_run_loop`（`agent.py:380-387`）按 `agents_map.get(state.next_agent)` 取到 `_director`——即 **run() 每次必经 director**（早期规划的「refine/rewrite 早已绕开它」才是准确表述：refine 在 `agent.py:459` 显式置 `"polisher"`，rewrite 在 `agent.py:494` 显式置 `"writer"`）。影响：删除后 run 的 steps 数 4→3，`test_agent.py:59`（`== 4`）与 `test_agent.py:94`（`== 7`）的断言、`test_state.py:10`（`== "director"`）必须同步修改。
2. **「前情摘要只给 writer/polisher」不成立**。`_working_context()` 唯一调用点是 `_writer`（`agent.py:220`）——polisher 拿到的只是 `_retrieve(with_prior=True)` 的 RAG 前文片段（`agent.py:191-196`），**没有**工作记忆快照。故本 feature 除给 reviewer 注入外，顺带把 polisher 也补上（早期规划只点名 reviewer，polisher 属设计外延，见 D8 的注入范围决策）。

## 2. 改法设计

### 2.1 断点一：director 退役

**diff 要点**（全为删除/改写，无新增逻辑）：

1. `state.py:30`：`next_agent: str = "director"` → `next_agent: str = "writer"`；`state.py:19` 注释「Director 收到的写作任务」→「写作任务」。
2. `agent.py:161-166`：`agents` dict 删去 `"director": self._director` 一行。
3. `agent.py:211-214`：整段删除 `_director` 方法。
4. 叙述修正：`agent.py:1` 模块 docstring 改三角色；`agent.py:126` 类 docstring 同；`agent.py:450/484` refine/rewrite docstring 中「跳过 director」表述改写（如「refine 从 polisher 起」）。
5. 文档清理：`README.md` 及仓库内其他文档 grep `director`，一并修正（见 tasks T11）。

**不受影响项**（复核结论）：`_reject_target = "writer"`（`agent.py:159`）与 director 无关；`refine()`/`rewrite()` 显式覆写 `next_agent`（`agent.py:459/494`），不受默认值变更影响；`_run_loop` 的未知 agent 分支（`agent.py:387-390`）逻辑不变。

### 2.2 断点二：构思解析与传递

**状态字段变更**（`state.py`）：

```python
# 核心五字段之后、「重写输入」之前新增：
outline: str = ""   # writer 的构思说明（=== 分隔前的部分；无分隔符时为空）
```

**新纯函数**（`agent.py` 模块级，先例：`_strip_polisher_meta` `agent.py:101-122`）：

```python
def _split_writer_output(raw: str) -> Tuple[str, str]:
    """writer 输出按首个 === 切分，返回 (构思, 正文)。无分隔符时构思为空、正文为全文。"""
    if not raw:
        return "", ""
    if "===" in raw:
        outline, _, body = raw.partition("===")
        return outline.strip(), body.strip()
    return "", raw.strip()
```

**`_writer` 接线**（替换 `agent.py:247-251`）：

```python
outline, body = _split_writer_output(raw)
state.outline = outline
state.draft = body          # 空 body 走既有占位兜底（agent.py:252-254 不变）
```

**polisher 消费**（`_polisher`，`agent.py:267-270` 的 feedback_hint 旁，同款模式追加到 user 消息尾部）：

```python
outline_hint = ""
if state.outline:
    outline_hint = f"\n\n【writer 构思（润色时保持此意图，不要跑偏）】\n{state.outline}"
```

**reviewer 消费**（`_reviewer`，同样追加到 user 消息）：

```python
outline_hint = ""
if state.outline:
    outline_hint = f"\n\n【writer 构思（验收基准：请审查正文是否实现了该构思）】\n{state.outline}"
```

**进 run record**：零额外代码。`_record` 的 steps 快照用 `asdict(after)`（`agent.py:393-403`），新字段自动进入每步 `output_state` 与 `final_state`。早期规划验收「run 日志含 writer 构思」由此满足；`harness.replay` 展示构思为 P1 可选增强（追加行，见非目标 9）。

**字段命名依据**：早期规划「构思（0.8 已保留传递）从 writer 前移到 planner」——`outline` 与 3.3 planner 的「节拍/大纲」语义直接衔接，未来前移即把 writer 的产出挂到 planner 角色上，字段无需改名。备选名对比见 D1。

### 2.3 断点三：reviewer 前情注入

**改法**：`_reviewer` 的 system 构造处追加 `+ self._working_context()`（与 `_writer` `agent.py:220` 的拼接方式完全一致）：

```python
system = reviewer_system(...) + self._working_context()
```

`_working_context()` 自带空态保护（`agent.py:206-207`：`working_memory is None or current_chapter is None` 时返回 `""`），首章/无记忆零噪音（A10）。

**注入范围论证（为什么是快照而不是 RAG 前文，D3）**：

1. **早期规划明示**（早期规划）：「reviewer 注入 `_working_context()`（伏笔/时间线维度有数据可查）」。
2. **对位性**：reviewer 的痛点维度是「伏笔一致性/时间线一致性」（`prompts.py:139/141`），`WorkingMemory.snapshot()`（`memory.py:61-68`）恰好是结构化四元组（当前进度/最近剧情/角色状态/**未回收伏笔**）——直接对位。
3. **噪声与成本**：`_retrieve(with_prior=True)` 的前文是 top_k=3 的散文片段（`agent.py:191-196`），且与「必须遵守的设定」混在同一段检索结果里；给「挑错者」喂参考性散文反而稀释审查注意力，还把 reviewer 单次调用 token 翻倍。
4. **职责边界**：reviewer 的本职是审稿不是复读前文；连续性判断需要的是状态事实（快照），不是原文重读。

故 `with_prior` 保持 `False`（`agent.py:338` 不动，A11），reviewer 的前情来源 = 工作记忆快照 + 构思（A8）。

**polisher 同样注入快照**（D8 已拍板；早期规划只点名 reviewer，属设计外延）：改法同 reviewer，system 构造处 `+ self._working_context()`。理由：polisher 的铁律「严禁改动剧情/伏笔」（`prompts.py:125`）同样需要伏笔清单支撑；成本为零——同一段快照字符串拼接。

### 2.4 断点四：长度控制归一

**配置层**（`config.py`）：

```python
# --- 编排控制 ---
max_rounds: int = 10
max_reviews: int = 6
target_words: int = 1500   # NOVEL_TARGET_WORDS：单章目标字数（writer 写作 / polisher 扩写共用口径）
```

`get_settings()`（`config.py:141-159`）追加：`target_words=int(os.environ.get("NOVEL_TARGET_WORDS", "1500"))`。注意现有 env 读取全为 str 且无 int 转换先例--非法值（非数字）会 `ValueError` 启动即失败，属配置错误显式暴露，与 fail-fast 一致，不做容错转换（列 D5 备注）。`.env copy.example` 补示例行。**另注意**：`get_settings()` 带 `@lru_cache(maxsize=1)`（`config.py:141`）--测试中 `monkeypatch.setenv` 后必须 `get_settings.cache_clear()` 才能读到新值，用例收尾再 clear 一次防污染其他用例（T6 验证栏已注明；复核发现的坑）。

**注入层**（`agent.py` `__init__`，同 `max_reviews` 模式 `agent.py:153`）：

```python
def __init__(self, ..., target_words: Optional[int] = None, ...):
    self.target_words = self.settings.target_words if target_words is None else target_words
```

**消费层一：writer user prompt**（替换 `agent.py:236`；rewrite 分支 `agent.py:227-233` 末尾同样追加，保证两分支口径一致，A12）：

```python
f"写一段新章节：{state.task}。目标约{self.target_words}字。"
```

**消费层二：polisher system**（`prompts.py:119-129` 死参数接活，A13）——在「任务：」段后插入一行：

```
目标篇幅：约{target_words}字。初稿明显不足时扩写补充细节；已达标则不必硬凑。
```

**调用点**（`agent.py:262-264`）：`polisher_system(..., target_words=self.target_words, rules=self.rules)`。

**进 record**（`_record` 的 config dict，A15）：追加 `"target_words": self.target_words`。

**单一来源声明**：字数口径的唯一真源是 `Settings.target_words`（env 可覆盖、构造可注入），writer/polisher prompt 一律从 `self.target_words` 取值，源码中不得再出现字面量长度指令（「约200字」删除）。reviewer 不注入长度目标（审的是质量不是字数）。

### 2.5 断点五：剧情摘要收编

**新方法**（`NovelAgent`，`agent.py`）：

```python
def summarize_chapter(self, chapter_text: str, max_tokens: int = 1024) -> str:
    """剧情摘要（0.8 从 cli 收编）：1-2 句话关键情节与情绪落点。异常抛给调用方。"""
    return self.llm.chat(
        PLOT_SUMMARY_SYSTEM, chapter_text,
        max_tokens=max_tokens, temperature=0.3,
    )
```

- `PLOT_SUMMARY_SYSTEM` 的 import 从 `cli.py:33` 移到 `agent.py`（prompts 常量归属 agent 层消费，cli 不再 import）。
- `max_tokens=1024` 对齐宪法 §4 短输出阈值（原调用 `cli.py:139` 即 1024，行为不变）。
- **方法内不吞异常**：agent 方法保持薄、可用 FakeLLM 直接断言调用参数；兜底是 UI 层策略，留在 cli（A17）。

**cli 调用侧**（替换 `cli.py:135-143`）：

```python
try:
    summary = agent.summarize_chapter(state.final_chapter)
except Exception:
    summary = task
wm.update_after_write(num, summary or task)
```

### 2.6 P1：refine/rewrite 工作记忆刷新 + 对比器收编

**P1-a 工作记忆刷新**（A18、A21）：

1. 调用方把丢弃的 wm 传进来：`agent, _ = _build_agent(settings)` → `agent, wm = _build_agent(settings)`，`_refine_postprocess` 签名加 `wm` 参数。
2. 新纯函数（`storage.py`，先例：`parse_chapter_task` `storage.py:47-56`）：

```python
def parse_chapter_file(path: Path) -> Tuple[Optional[int], str]:
    """从章节文件名解析 (章号, 标题)。匹配「第05章-标题.md」等 save_chapter 落盘格式；不匹配返回 (None, stem)。"""
```

   存在的必要性：refine/rewrite 的 task 是 `f"精修：{path.name}"`（cli 层拼接），`parse_chapter_task` 的正则（`storage.py:47-56`，按「章**：**」分隔）匹配任务串「写第5章：异乡风起」但不匹配文件名「第05章-异乡风起.md」（按「-」分隔，`save_chapter` `storage.py:95-127` 的落盘格式），两者格式不同源。

3. 刷新点：`_refine_postprocess` 的两个存回分支（passed 存回、better 存回）之后：

```python
num, _ = parse_chapter_file(path)
try:
    summary = agent.summarize_chapter(state.final_chapter)
except Exception:
    summary = None
# D9-b：精修不回退进度；current_chapter 为 None（首章）时裸 >= 会 TypeError，必须补 None 判断
if num is not None and summary and (wm.current_chapter is None or num >= wm.current_chapter):
    wm.update_after_write(num, summary)
    save_working_memory(wm, settings)
```

   `update_after_write`（`memory.py:49-59`）是覆盖式（`current_chapter`/`last_plot_point` 直接赋值），对「精修已写章节后刷新该章摘要」语义成立；但精修旧章（如第 3 章而进度已在第 5 章）会把进度指针回退——见 D9 的语义选择。

**P1-b 对比器收编**：`cli.py:62-79` `_is_better` → `NovelAgent.is_better(self, original, refined) -> bool`（用 `self.llm`，内联 system prompt 迁入方法体或 `prompts.py` 常量，推荐后者保持「prompt 归 prompts」惯例）；调用点 `cli.py:194` 改 `agent.is_better(content, state.final_chapter)`，cli 侧 try/except 兜底保留（`cli.py:193-196` 现状）。EARS 由 A16 总则覆盖（cli 命令处理不再直接引用 `agent.llm`）。

**P1-c replay 展示构思**（可选）：`harness.replay` 在步骤行后追加输出 `s["output_state"].get("outline")` 摘要（`.get` 容错旧记录，A20）。追加行、不改既有行。

## 3. 失败路径

| 场景 | 行为 | 对应 EARS |
|---|---|---|
| writer 输出不含 `===` | `outline=""`，全文进 draft（现状保持） | A5 |
| writer 输出为空 | draft 占位兜底 + log 留痕（`agent.py:252-254` 现状保持），outline 为空 | A19 |
| 正文含多个 `===` | `partition` 只按首个切分，后续 `===` 留在正文（与现状 `split("===", 1)` 语义一致） | A4 |
| 构思异常超长 | 不截断——构思与正文共享 writer 的 `max_tokens=4096` 总预算，模型输出天然受限；注入 polisher/reviewer 时按原文进 prompt | 设计取舍 |
| `working_memory=None` 或首章 | `_working_context()` 返回 `""`，reviewer/polisher prompt 无噪音 | A10 |
| `summarize_chapter` 抛异常 | cli 捕获，摘要回落为 task，落盘不阻断 | A17 |
| `parse_chapter_file` 不匹配 | 返回 `(None, stem)`，跳过工作记忆刷新，存回主流程不受影响 | A21 |
| `NOVEL_TARGET_WORDS` 非法（非数字） | `get_settings()` 抛 `ValueError` 启动失败（fail-fast，见 D5 备注） | 设计取舍 |
| 回放旧记录（含 director step、无 outline 字段） | replay 的步骤行只读 `step_id/agent/round/decision/output_state 的 draft/polished`（`harness.py:38-43`），agent 名只打印不校验，`.get` 容错缺键——正常回放 | A3、A20 |

## 4. 兼容性影响分析

### 4.1 run record 结构变化（对 replay/evaluate/compare 的影响）

**record 键读取方**（`harness.py:25-47` replay 直读）：`run_id`、`task`、`config`、`timestamp`、`steps[*].{step_id, agent, round, decision, output_state.{draft, polished}}`、`final_state.final_chapter`。另 `evaluate`（`harness.py:107-152`）读 `final_state` 的 `next_agent`/`feedback`（`harness.py:168/177`）。

| 变更 | 影响 |
|---|---|
| `PipelineState` 新增 `outline` 字段 | `asdict` 自动进 `steps[*].output_state` 与 `final_state`/`initial_state`。**replay/evaluate 均按需取键，不遍历全字段** → 新键零影响。旧记录缺该键：未来 P1-c 用 `.get("outline")` 容错 |
| `config` 新增 `target_words` | replay 直接 `print(d['config'])`（`harness.py:34`）整字典打印 → 自动展示，零影响 |
| 删 director 后新记录 steps 少一步 | `len(d['steps'])` 动态计算（`harness.py:36`）→ 零影响；旧记录含 `"director"` step 仍正常打印（A3，conftest 的 `sample_run` 即现成回归样本，`conftest.py:96-98`） |

**结论**：本 feature 对 record 的全部变更是「加键」与「少一种 step」，读取方按需取键的模式下均零破坏；`initial_state` 不被 replay 读取（partial-refine design §5.6 已核实的结论，沿用）。

### 4.2 对 run/refine/rewrite 三条路径的影响

| 路径 | 变更 | 风险 |
|---|---|---|
| `run()` | 起点从 director 变 writer；writer 产出 outline 全程传递；config 多 `target_words` | steps 数 4→3（打回一轮 7→6），两处测试断言需同步（§4.3） |
| `refine()` | `next_agent="polisher"`（`agent.py:459`）不变；polisher 起跑时 `state.outline` 为空（无 writer 参与）→ outline_hint 不注入，polisher 行为不变；P1 加工作记忆刷新 | 无破坏；outline 空态设计即为此服务 |
| `rewrite()` | `next_agent="writer"`（`agent.py:494`）不变；rewrite 会**重新构思**（writer 重跑），outline 是新任务的构思，语义自洽 | 无破坏 |
| `partial_refine()` | 不走状态机、不碰 `PipelineState`（`agent.py:506-543`）→ **零改动**（非目标 1） | 无 |

### 4.3 测试影响面（现状必改清单）

| 位置 | 现状断言 | 需改为 |
|---|---|---|
| `test_agent.py:59` | `len(record["steps"]) == 4  # director/writer/polisher/reviewer` | `== 3  # writer/polisher/reviewer` |
| `test_agent.py:94` | `len(record["steps"]) == 7`（打回场景） | `== 6` |
| `test_agent.py:276-290` | 构思被丢弃（`"构思" not in state.draft`） | 保留 draft 断言 + 新增 `state.outline` 非空断言 |
| `test_state.py:10` | `s.next_agent == "director"` | `== "writer"` |
| `test_state.py:15-22` | asdict roundtrip | 自动兼容新字段（`PipelineState(**d)`），可选加 outline 键断言 |

**FakeLLM 关键词分流兼容性**（`conftest.py:27-35`）：分流依据 user 消息中的「审查/润色」关键词。本设计的 outline_hint 追加在 user 消息**尾部**、feedback_hint 之前/之后均不命中分流关键词，且 `_working_context()` 拼在 **system** 侧（FakeLLM 只记录 user，`conftest.py:28`）——既有分流行为不受干扰。

**新增测试的脚本化注意**：用 `fake_llm.script` 精确控制时，writer 的返回值需自备「构思===正文」格式（先例：`test_agent.py:279`）；验证 reviewer 注入用 `fake_llm.calls` 检查 reviewer 那次调用的 user/system 内容（需给 FakeLLM 临时记录 system，或断言 user 侧的 outline_hint）。

## 5. 宪法红线核对

- **§1**：文档与测试示例沿用既有虚构名（「异乡风起」「林晚」，`conftest.py:46`、`test_agent.py:53` 均已存在），无真实书名/人物。
- **§2**：无技术栈变更；`NOVEL_TARGET_WORDS` 是纯数值配置。
- **§4**：`summarize_chapter` 保持 1024；writer/polisher 保持 4096；风险见 §6。
- **§5**：`_split_writer_output`/`parse_chapter_file` 为模块级纯函数（可单测）；`summarize_chapter`/`is_better` 挂 `NovelAgent`（依赖 `self.llm` 注入）；cli 不再 import prompt 常量、不再持有 `agent.llm`；`PipelineState.outline` 与 `WorkingMemory` 名义分离未混。
- **§7**：全部新测试离线（FakeLLM/FakeRag/monkeypatch env）。

## 6. 最大风险：长度目标 vs 推理模型 token 预算（D5 关联）

`target_words=1500`（默认）进 prompt 后，若模型顺从，writer 单次需产出 1500 中文字 ≈ 1500-2200 输出 token（glm 分词器中文约 1-1.5 token/字）；glm-5.2 是推理模型（宪法 §4），`max_tokens=4096` **含内部推理预算**——推理消耗数百至千余 token 后，正文预算贴边。早期规划的端到端验收「可配出 2000+ 字章节」更紧（2000+ 字 ≈ 2500-3000 token 正文 + 推理）。

**缓解与边界**：
1. 本 feature **不动 4096**（宪法 §4 规定值，且调大属运行时调参、不涉换栈，留给实测后按需调整——记录在案但不预置）。
2. 单测只断言「长度目标进 prompt」（A12/A13），**不断言实际产出字数**（模型行为，宪法 §7 严禁后阶段指标前移的同类逻辑）。
3. 「可配出 2000+ 字」的端到端验收依赖真实模型实测（`.env` 配 `NOVEL_TARGET_WORDS=2200` 跑一次 `write`），在 tasks 的验收方式中注明为人工验收项，不进 pytest。
4. 若实测频繁 `finish_reason=length` 截断：症状是正文被腰斩（非空回），`llm.py` 的重试逻辑（对空回/异常重试）救不了截断——届时调大 `max_tokens` 或下调 `NOVEL_TARGET_WORDS`，均为配置层动作。

## 7. 开放决策清单（D1-D9）

| # | 决策 | 选项 | 推荐 | 理由 |
|---|---|---|---|---|
| D1 | 构思字段命名 | a) `outline` b) `concept` c) `premise` | **a** | 与阶段 3.3 规划「构思前移到 planner 产节拍」语义衔接，未来前移零改名；`concept` 过泛、`premise` 偏前提设定 |
| D2 | 构思解析实现位置 | a) `agent.py` 模块级纯函数 `_split_writer_output` b) 内联在 `_writer` c) 挂 `state.py` 作 dataclass 方法 | **a** | 同 `_strip_polisher_meta` 先例（`agent.py:101`）；纯函数直测，不引入状态依赖 |
| D3 | reviewer 前情注入量 | a) 仅 `_working_context()` 快照 b) 快照 + RAG 前文（`with_prior=True`） c) 全量正文 | **a** | 早期规划明示；快照与伏笔/时间线维度直接对位；b 的散文片段稀释审查注意力且 token 翻倍（§2.3 论证） |
| D4 | 长度配置项名与默认值 | a) `Settings.target_words=1500` + env `NOVEL_TARGET_WORDS` b) `chapter_words` + `NOVEL_CHAPTER_WORDS` | **a** | 接活 `polisher_system` 既有死参数名（`prompts.py:119`），一词贯通配置/参数/prompt；1500 承接死参数默认，行为零跳变 |
| D5 | `NOVEL_TARGET_WORDS` 非法值处理 | a) `int()` 直转，启动 fail-fast b) 容错回落 1500 并告警 | **a** | 配置错误显式暴露优于静默降级；现有 `get_settings` 无容错先例，保持一致（备注：本项风险见 §6） |
| D6 | 摘要方法命名与异常策略 | a) `summarize_chapter(text, max_tokens=1024)`，不吞异常，兜底留 cli b) 方法内吞异常返回空串 | **a** | agent 方法薄、可测（FakeLLM 断言 system/参数）；UI 兜底策略属 cli 职责（现状 `cli.py:140-142` 行为保持，A17） |
| D7 | 构思注入 prompt 的位置（polisher/reviewer 侧） | a) user 消息尾部（feedback_hint 同款） b) system prompt 拼接 | **a** | 构思是每次运行的动态数据，user 侧语义自然；且 FakeLLM 的 `calls` 只记录 user（`conftest.py:28`），测试断言最直接 |
| D8 | polisher 是否也注入工作记忆快照 | a) 注入（同 reviewer） b) 不注入（严格按早期规划字面，只改 reviewer） | **a**（已拍板） | polisher 铁律「严禁改动剧情/伏笔」（`prompts.py:125`）同样需要伏笔清单支撑；成本为零（同一段快照字符串）。但早期规划未点名 polisher，属设计外延，2026-08-28 拍板：注入 |
| D9 | P1 精修旧章的进度指针语义 | a) `update_after_write` 直接覆盖（精修第 3 章会把 `current_chapter` 从 5 回退到 3） b) 仅 `current_chapter is None or num >= current_chapter` 时更新 c) 只刷 `last_plot_point` 不动 `current_chapter` | **b**（已拍板） | a 会误导 writer 的「当前进度」显示；c 需要绕过 `update_after_write` 的封装，破坏 memory 接口；b 一行判断即可，语义为「精修不回退进度，但刷新最新章摘要」 |

> 以上推荐为实现缺省取向。**2026-08-28 复核拍板：D1-D9 全部按推荐项执行**（D8=polisher 注入快照；D9=b，且边界条件须按 §2.6 代码块写全 `current_chapter is None or num >= current_chapter`，因 `current_chapter` 初始为 `None`（`memory.py:44`），裸 `>=` 在首章会 TypeError，属复核发现的硬伤）。实现时如与拍板结果不一致，回改本表。
