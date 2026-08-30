# 阶段 2：吞吐（throughput）- 设计

> 对应需求：同目录 `requirements.md`（T1-T29）。
> 前置：`specs/quality-gate/design.md`（D1-D12/Z1-Z10）与 `specs/style-loop/design.md`
>（D1-D8/Z1-Z6）已实现--本文消费其门禁（`_gate_ok`/`_gate_confirm`）、
> de-AI pass（`_deai_pass`）与思考块清洗（`_strip_think_blocks`）。
> 行号锚点基于 2026-08-30 代码（style-loop 完成态，397 passed 基线）。
> 编号：需求 T 系列；设计决策 D 系列（本 feature 独立，不撞 quality-gate 的 D）；
> 自主补充 Z 系列。
> 修订（2026-08-30）：批量任务来源改为章纲驱动（用户 `NOVEL_DIR/每章.md`
> 工作流，D6/D8/D11 重写），序数后缀降为回落。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| T1-T5 流式核心（接口/思考过滤/重试语义） | §3.1 chat 的 on_delta 路径 + §3.2 ThinkFilter |
| T6-T9 流式边界（角色范围/打断/后处理） | §3.3 agent 接线 + §3.4 打断语义 |
| T10/T26/T29 兼容 | §3.7 降级与回归 |
| T11/T16 章纲解析 | §4.1 parse_chapter_plan |
| T12/T15 规划注入（含单章增强） | §4.2 state.plan -> writer |
| T13/T14/T25 任务构造优先级与回落 | §4.1 决策表 |
| T17/T27 单章复用 | §4.3 _write_one 拆层 |
| T18-T20/T22 批量编排与中断 | §4.4 _do_write_batch |
| T21 连续性 | §4.3（复用既有路径，零新逻辑） |
| T23/T24 边界与预算 | §4.1 + §4.4 |
| T28 可发现性 | §2 配置面 + tasks W7 |

## 1. 总体设计

两个能力互相独立、可单独降级；共享的只有「写作一条龙由 `_write_one` 承载」：

```
（2.1 流式，改通信层）                 （2.2 批量，章纲驱动编排层）

cli._do_write(task, plan)               cli 主循环 startswith("写")
  └─ agent.run(task, plan) ─┐             ├─ 解析区间/单章/章纲（§4.1）
     _writer ──────────────┤             │    写第5-10章 ── 查每章.md
     _polisher ───────────┤             │        -> [(章号,标题,规划要点)...]
                           ▼             │    写第5-10章：模板 -> 章纲回落序数
                    writer_llm.chat(     │    写第5章 ── 章纲取标题+规划
                      ..., on_delta=cb)  │        -> _do_write_batch
                      └─ stream=True     │             └─ for 章号 in 区间:
                         逐 chunk:        │                 _write_one(任务_i, 规划_i)
                         delta -> ThinkFilter             ├─ 默认: 章间 _gate_confirm(y/n)
                         -> print(end="", flush)          └─ --auto: 门禁弃/失败 -> 中断
                         收完 -> 清洗 -> return str      └─ 未命中 -> _do_write（现状）
                                                        state.plan -> writer【本章规划】
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `_do_write` 主体（cli.py:266-358） | 改名为 `_write_one` 返回结局枚举，单章/批量共用（T17/T27） |
| `_gate_confirm`（cli.py:182） | 批量章间确认 + --auto 低分中断前的交互缝（T18） |
| `_gate_ok` + 门禁链 | --auto 的 fail-closed 判据（T19）：现成的「应答弃即弃」就是中断信号 |
| `_strip_think_blocks`（llm.py:105） | 流式收尾的数据侧清洗（打印侧另做增量过滤，§3.2） |
| chat 重试骨架（llm.py:189-227） | 流式路径完整继承（退避/temp 锁定/空回翻倍），§3.4 |
| `parse_chapter_task`（storage.py:48） | 章纲解析的同居先例；构造出的任务串沿用其解析（save_chapter 零适配） |
| 构思传递链路（0.8：state.outline -> polisher/reviewer/record） | `state.plan` 走同款链路形状：PipelineState 字段 + asdict 自然进 record |
| wm.update_after_write + rag.add_document | 批量章间连续性（既有路径零新逻辑，T21） |

## 2. 配置面（新增 3 个 env，其余不动）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_STREAM` | writer/polisher 流式输出开关 | `1` | int，`0` = 关（回到非流式现状） |
| `NOVEL_BATCH_MAX` | 批量连写单命令最大章数 | `10` | int，跨度超限报错（token 护栏，T23/T24） |
| `NOVEL_CHAPTER_PLAN` | 每章规划文件（章纲）相对路径 | `每章.md` | 相对 novel_dir；**留空 = 禁用章纲**（T14 回落；文件不存在同禁用，静默不报错--对齐 `写作铁律.md` 缺失回落空串的既有纪律） |

设计口径：三个都是行为/路径配置，归 env（对齐 `NOVEL_RULES`/`NOVEL_TARGET_WORDS`
先例，config.py「小说内相对路径」与「编排控制」段各归其位）。`--auto` 是命令行
尾缀 token 不是配置（一次性行为，与常驻配置语义不同）。

## 3. 详细设计（2.1 流式输出）

### 3.1 chat 接口：on_delta 回调注入（D1）

```python
def chat(self, system, user, *, max_tokens=1024, temperature=0.9,
         max_retries=5, on_delta: Optional[Callable[[str], None]] = None) -> str
```

- **`on_delta` 非空即流式**：请求体加 `stream=True`，网关返回 chunk 迭代器；
  每个可打印增量调用一次 `on_delta(text)`；收完组装全文，返回值仍是
  清洗后的完整 `str`（T1：返回语义与非流式一致）。
- **备选与拍板**：a) `stream=True` 返回生成器；b) 回调注入。拍 **b**--
  返回类型不变则全部调用点与 FakeLLM 零改动；生成器迫使消费方改循环，
  blast radius 不可控。事实核对（修订）：tests/ 的 FakeLLM 定义共 7 处
  （conftest + test_agent×3 + test_routing + test_cli_write + test_harness），
  全为 `(system, user, **kw)` 签名；agent.py 的 chat 调用点共 8 处
  （379/409/486/647/709/732/744/928），本 feature 只在 _writer/_polisher
  两处传 on_delta，其余 6 处零改动。
- **chat 不 print 增量**：打印是调用方（agent）经回调决定的事，
  llm 层只负责「把增量交出去」（宪法 §5：llm 是边界，不掺 UI 决策）。
- chunk 解析容错：`chunk.choices` 为空跳过；`delta.content` 为 None 跳过；
  `delta.reasoning_content` 只累积不外发（T3，Z2）。

### 3.2 ThinkFilter：思考块增量过滤（D2）

llm.py 新增小类（纯逻辑，可离线单测）：

```python
class _ThinkFilter:
    """流式增量思考块过滤：feed(delta) -> 当前可安全打印的前缀，flush() -> 尾部。"""
```

- 逻辑：内部累积 buffer；feed 后返回「确定安全」的文本量--
  1. 若 buffer 中出现完整思考块对（同 `_THINK_OPEN..._THINK_CLOSE` 正则），
     剥掉后剩余部分可打印；
  2. 若出现未闭合的 `_THINK_OPEN`：该位置之前可打印，之后全部扣住（思考中不漏）；
  3. 尾部持有最后 `len(tag)-1` 字符不发（防 `</th`+`ink>` 跨 chunk 被截断误放行）；
     flush 时按「未闭合前缀」规则结算（剩余若是思考则丢弃，不是正文）。
- **双层兜底（T2）**：打印侧由 ThinkFilter 保证实时流干净；数据侧收完后再过
  既有 `_strip_think_blocks`--极端 case（标签跨重试边界等）打印侧偶有迟发
  可接受，**返回值必须与现状逐字节同源**（下游 ===/quote 定位靠它，T9）。
- 正则与标签常量复用模块级 `_THINK_OPEN/_THINK_CLOSE/_THINK_BLOCK_RE`，不复制。

### 3.3 重试语义（D3）+ agent 接线（D4）

**重试骨架共用**：流式与非流式走同一个 `for attempt in range(1, max_retries+1)`
外层循环，三种既有容错对流式的适配：

| 既有容错 | 非流式现状 | 流式适配 |
|---|---|---|
| 空回翻倍（llm.py:199-213） | content 空 + finish=length + reasoning 有 -> 翻倍重试 | 收完全部 chunk 后累积正文为空 + 末 chunk finish_reason=length + reasoning 累积非空 -> 翻倍整请求重试（T4） |
| temp 400 锁定（llm.py:219-222） | 异常串含 400+temperature -> 锁定重试 | 同判（流式请求在首 chunk 前抛的 400 与非流式同路；锁定态 `_temp_locked` 是 client 级，天然对流式后续调用生效）（T5） |
| 指数退避（llm.py:225-227） | attempt 间隔 2^attempt | 流式中途异常：丢弃已收增量、打印 ⚠️、整请求重来（T5） |

**agent 接线（D4）**：

- `NovelAgent.__init__`（agent.py:250）增 `stream: bool = False` 参数；
- 新增方法 `_print_delta(text)`: `print(text, end="", flush=True)`；
- `_writer`（agent.py:356）/`_polisher`（agent.py:395）的 `writer_llm.chat(...)`
  追加 `on_delta=self._print_delta if self.stream else None`--**键恒在、值随
  stream 取回调或 None**（单一表达式，分支两套调用反而易漂移；FakeLLM 的
  `**kw` 两种形态都吞得下）（T6：仅此两处，
  reviewer/fixer/评委/摘要/路由调用点零改动）；
- 角色头提示改文案：`✍️  写作中（流式）...` / `🔧 润色中（流式）...`（stream
  为真时），流式正文前先 `print()` 换行、结束后补 `print()`（T8）；
- `cli._build_agent`（cli.py:134）从 `settings.stream` 注入（T26）；
- **测试直构 agent 默认 stream=False**：既有 test_agent 用例零改动（回归保护）；
  stream=False 的断言口径是「on_delta 键在、值为 None」（与上一条接线形态一致）。

### 3.4 Ctrl-C 打断语义（D5）

- `KeyboardInterrupt` 不是 `Exception` 子类--现状下写作期间的 Ctrl-C 会穿透
  `_do_write` 的 `except Exception`（cli.py:281）直捣 REPL 主循环退出。
- 改法（修订：覆盖面从 agent.run 扩到 `_write_one` 整体）：`_write_one` 最外层
  包 `except KeyboardInterrupt`：打印 `\n⚠️ 已打断，本章未保存`，return
  中断结局（不存盘/不更新 wm/不落 record--与「创作失败」同语义，record 留给
  完成态，见非目标 2）。只包 agent.run 会漏掉打断落在 evaluate/save_chapter
  等后续阶段的穿透（用户评审指出）；整体包则语义统一：打断 = 本命令作废。
- 既有 `_confirm_unparseable`（agent.py:451）与 `_gate_confirm` 内 input 的
  Ctrl-C -> "n" 语义不动（它们先于外层捕获消化，答 n 走「弃」分支而非中断
  批量--保守方向一致）；批量循环再包一层（§4.4，T22）。

### 3.5 流式请求构造细节（Z1/Z2）

- 请求体复用现有 `req` dict 构造（extra 透传、temp 锁定压温、max_tokens
  生效值起步），仅追加 `stream=True` 后 `create(**req, stream=True)`；
- **Z2**：`reasoning_content` 在 delta 上时只累积（供空回翻倍判定用
  「思考有输出」），不进正文不打印（部分网关思考走该字段，部分混 content，
  两条路都有兜底）；
- **Z1**：等待提示在流式下改为 `⏳ 等待模型响应（流式）...`（首个 delta 到达
  后由 on_delta 的打印自然接管屏幕）；重试时打印 `⚠️ 流式中断/空回，第 N 次重试...`。

## 4. 详细设计（2.2 批量连写，章纲驱动）

### 4.1 命令解析与章纲（D6/D7/D8/D11）

storage.py 新增三个纯函数（与 `parse_chapter_task` 同居，同风格）：

```python
_RANGE_RE = re.compile(r"第\s*(\d+)\s*[-–~至]\s*(\d+)\s*章(?:\s*[：:]\s*(.+))?")

def parse_chapter_range(task: str) -> Optional[Tuple[int, int, Optional[str]]]:
    """"写第5-10章" -> (5, 10, None)；"写第5-10章：异乡风起" -> (5, 10, "异乡风起")；不匹配 -> None。"""

def parse_chapter_plan(text: str) -> Dict[int, Dict[str, Any]]:
    """章纲 markdown -> {章号: {"title": 标题, "notes": [(列名, 值), ...]}}。

    - 扫描全部 markdown 表格块（分卷多表格合并成一个映射，T16）；
    - 列头兼容「标题/暂定标题」；首列非章号的表格（无「章」+「标题」列头）跳过；
    - 分隔行（---）跳过；章号非整数行跳过；
    - notes = 标题列之后的各列 (列名, 值) 对，列名原样保留
      （核心事件/天气/矛盾种子……未来加列零改动）。
    """

def cn_numeral(n: int) -> str:
    """1 -> 一 … 99 -> 九十九（标题模板回落的后缀用，纯函数）。"""
```

**任务构造优先级（D11，一张表说清）**：

| 命令形态 | 标题来源 | 规划要点注入 | 说明 |
|---|---|---|---|
| `写第5-10章`（无标题） | 章纲逐章标题 | 章纲逐章注入 | 主路径；缺章 -> 报错列缺失章号，零调用（T14） |
| `写第5-10章：异乡风起`（带模板） | 模板 + 中文序数后缀（（一）（二）…） | 章纲存在该章则照常注入 | 显式标题只赢标题（T13）；无章纲 = 纯模板回落 |
| `写第5章`（单章无标题） | 章纲标题 | 章纲注入 | T15；无章纲且无标题 -> 报错提示补标题 |
| `写第5章：标题`（现状形态） | 命令标题 | 章纲存在该章则注入 | 现状命令的增量增强（T12/T25）；无章纲 = 现状零变化 |

- **`--auto` 剥离**：任务串尾部独立 token `--auto` 剥出为标志，解析前先剥；
- **分发（D7）**：cli 主循环 `startswith("写")` 分支（cli.py:1015）顺序：
  1. 剥 `--auto` 尾缀；
  2. 试 `parse_chapter_range`（含单章区间 5-5）-> 命中进 `_do_write_batch`
     （单章区间退化为一次 `_write_one`，T25）；
  3. 试单章无标题形态（`写第N章`）-> 章纲解析出任务与规划后进 `_do_write`
     （等价于用户敲了 `写第N章：{章纲标题}`，T15）；
  4. 其余 -> `_do_write`（现状零改动）。
- **章纲加载**：`config.Settings` 增 `plan_full` 路径属性（同 `rules_full`
  先例）；cli 层 `_load_chapter_plan(settings)` 读文件 + `parse_chapter_plan`
  （文件不存在/未配置返回 `{}`，静默降级，§2）；章纲解析一次、批量全程复用
  （不是每章重读文件）。

### 4.2 规划注入（D12）：state.plan -> writer

- `PipelineState`（state.py）增 `plan: str = ""` 字段（asdict 自然进 record，
  replay 可见当时按什么规划写的，T12 后半句）；
- `agent.run(task, run_id=None, temperature=0.9, plan: str = "")` 增参：
  `state = PipelineState(task=task, plan=plan)`；
- `_writer`（agent.py:356）user_msg 构造追加：

```
【本章规划】（按此展开本章，是写作依据；天气与矛盾种子是本章的既定设定）
{state.plan}
```

（空串整块不占位，对齐 `_rules_block` 先例；新章与 source_content 两个分支
都注入。）

- **渲染**：cli 层把 `notes` 渲染为 `核心事件：……\n天气：……\n矛盾种子：……`
  （列名 + 值逐行），plan 块即此文本。
- **D12 拍板：只注入 writer**（非目标 6）。polisher 消费 writer 的 outline
  （0.8 链路），reviewer 的验收基准是 outline 而非 plan（P0 不动）；
  把 plan 喂 reviewer 作验收基准留 P1 存档。

### 4.3 单章路径拆层（D9）：_write_one

`_do_write`（cli.py:266-358）主体改名为 `_write_one(task, settings, plan: str = "") -> str`
返回结局枚举：

| 返回值 | 含义 | 批量侧动作 |
|---|---|---|
| `"saved"` | 章节已存盘 | 默认模式 -> 章间确认；--auto -> 继续下一章 |
| `"rejected"` | 门禁弃 / 审稿人工弃（未存盘） | 默认模式 -> 章间确认（人现场拍板）；**--auto -> 中断批量**（T19） |
| `"failed"` | `agent.run` 抛异常 / 装配失败 | 两模式均中断批量（T20） |
| `"interrupted"` | Ctrl-C（§3.4） | 两模式均停止批量（T22） |

- `_do_write` 变薄壳：调 `_write_one`，其余零变化（对外行为同现状
  + plan 透传）；
- **章间重建 agent（T17）**：批量循环每章调 `_write_one` -> 内部
  `_build_agent` 重跑（工作记忆重读、RAG 检索含上一章、样文路由按新任务重路由、
  滚动人工正文窗口推进）。这是复用而非浪费：章间状态依赖本来就要求重建；
- **连续性零新逻辑（T21）**：wm.update_after_write + save_working_memory +
  rag.add_document 都在 `_write_one` 既有路径里（cli.py:327-338），批量
  不碰它，「章间自动更新工作记忆 + 入库」由复用自然达成。

### 4.4 批量编排（D10）：_do_write_batch

```python
def _do_write_batch(task: str, settings: Settings, auto: bool) -> None:
    start, end, base = parse_chapter_range(task)
    # 校验：start > end / 跨度 > settings.batch_max -> 报错 return（零 LLM 调用，T23）
    plan_map = _load_chapter_plan(settings)
    plans = {}
    if base is None:                       # 无标题：主路径，章纲供标题
        missing = [n for n in range(start, end+1) if n not in plan_map]
        if missing:
            print(f"❌ 每章规划缺章：{missing}（补齐 每章.md 或命令带标题模板）")
            return                                          # T14
    for num in range(start, end + 1):
        if base is None:
            title, plans[num] = plan_map[num]["title"], _render_notes(plan_map[num])
        else:
            title = f"{base}（{cn_numeral(num - start + 1)}）"   # T13 回落
            if num in plan_map:
                plans[num] = _render_notes(plan_map[num])
    print(f"📦 批量连写：第{start}-{end}章，共 {n} 章"
          f"（每章约 6-9 次 LLM 调用，注意 token 预算）")           # T24
    for i, num in enumerate(range(start, end + 1), 1):
        print(f"\n━━━ [批量 {i}/{n}] 第{num}章：{title} ━━━")
        outcome = _write_one(f"写第{num}章：{title}", settings, plan=plans.get(num, ""))
        if outcome in ("failed", "interrupted"):
            break                                          # T20/T22
        if outcome == "rejected" and auto:
            print(f"⛔ 第{num}章未过门禁，--auto 模式中断批量"
                  f"（已完成 {i-1} 章）")                  # T19 fail-closed
            break
        if i < n and not auto:
            if _gate_confirm(f"\n继续写第{num+1}章？(y/n)：").strip().lower() != "y":
                print("已停止批量，已完成章节保留。")       # T18
                break
```

- **`--auto` 低分章去向（D10 拍板：中断）**：门禁总原则「无人可交时才
  fail-closed」的 REPL 推论--`--auto` 是用户明确表态「免打扰」，机器拿不准
  （门禁不过）时没有人在环上可交，必须停。备选「隔离到待审清单」被否：
  隔离章若不入库则断连续性（后续章失前文），入库则污染检索基准（坏章被
  当正文参考），两难无数据可解，存档为 P1（tasks W9）；
- **章间确认用 `_gate_confirm`**（EOF/Ctrl-C -> n 保守停，与门禁同保守方向）；
- **每章 record 独立**：`_write_one` 内 save_run 照常（record 的 initial/
  final_state 含 plan 字段），批量不聚合成大 record（replay/compare 对每章
  零适配，非目标 8）。

### 4.5 边界与退化（T23/T25）

- `start > end`（如 5-3）：报错 `区间无效：起始章号大于结束章号`；
- `end - start + 1 > settings.batch_max`：报错并提示拆分命令；
- 章号非正整数/无标题且无章纲：按 §4.1 优先级表各自报错或回落，不新增错误面；
- 单章区间（5-5）：退化为一次 `_write_one`（走 §4.1 表第 1/2 行规则）。

## 5. 不动清单（防漂移）

- `chat` 非流式路径的行为逐字节（`on_delta=None` 时连请求体都不多 `stream` 键）。
- `_do_write` 对外行为（拆层是内部重构，薄壳零变化；plan 透传是唯一增量）。
- 门禁链 `_gate_ok`/`_gate_confirm`/`_deai_pass`/evaluate 时序（批量只消费结局）。
- `parse_chapter_task`/`parse_chapter_file`/`save_chapter`（构造出的任务串
  `写第N章：标题` 沿用既有解析与 `第05章-标题.md` 落盘格式，零适配）。
- reviewer/fixer/评委/摘要/路由的调用点（不开流式；plan 不进其 prompt）。
- 温度/max_tokens/extra 透传机制（流式参数只多一个 `stream`，走同一 `req` dict）。
- `WorkingMemory`/`RAGStore` 内部实现；`每章.md` 文件本身（只读）。
- `py/`、Java 侧。

## 6. 实现注意（坑位）

- **ThinkFilter 的跨 chunk 标签**：测试必须覆盖 `</th` + `ink>` 被切在两个
  delta 的形态（buffer 尾部 hold-back 是为此存在）；以及纯思考流（只有思考
  块直到流结束）-> 打印侧全程无输出、返回值为空串。
- **流式空回判定**：`finish_reason` 在**末 chunk** 才有（中间 chunk 是 None）--
  判定必须用循环里最后一次非 None 的值，不能用「任意 chunk」。
- **真车网关形态未验证（Z1 风险）**：FakeStream 测的是我们的解析假设；
  ark 网关实际的 chunk 结构（delta 字段名、reasoning 位置、空 choices chunk、
  末块 usage 形态）须 W2 后真车冒烟确认，不兼容点（如 chunk 无 choices 属性）
  在 `_chat_stream` 的 getattr 容错里逐个收口。
- **FakeStreamIterable**：test_llm 的假网关要提供 `chat.completions.create(
  stream=True, **req)` 返回 chunk 迭代器（`delta.content`/`delta.reasoning_content`/
  末 chunk `finish_reason` 三件套），与既有 FakeLLM（非流式）并存。
- **`KeyboardInterrupt` 传播路径**：`_write_one` 的 try 结构是
  `except KeyboardInterrupt` 在 `except Exception` **之外**并列（Python 中
  顺序无关但语义独立），且批量循环自身也包一层（章间确认的 input 已被
  `_gate_confirm` 内部消化）。
- **`_run_loop` 里的 input**（`_confirm_unparseable`）：批量模式下它仍会问
  人（审稿不可解析）--这是特性不是 bug：批量默认模式本来就是人在环；
  `--auto` 下用户在场可答；答 n -> rejected -> 中断，与 T19 一致。
- **`parse_chapter_range` 与 `parse_chapter_task` 的互斥性**：单章命令
  `写第5章：标题` 不匹配区间正则（无第二数字）--依赖分发顺序「先区间后单章」，
  主循环分支注释要写明。
- **章纲表格的脏数据**：实际 `每章.md` 列头有 `标题`/`暂定标题` 两态、
  分卷多表格、表格外还有散文说明--解析器只收「首列整数 + 第二列标题」的行，
  其余全部跳过不报错（对齐 `_load_rules` 缺失静默降级纪律）；同一章号
  出现多次取后者（修订覆盖草稿）。
- **规划要点很长**（实际章纲单格可达数百字）：这是写作指令的核心输入，
  全量注入不做截断（与 exemplar 的预算截断不同性质--它是「写什么」不是
  「像什么」）；token 预算靠 `NOVEL_BATCH_MAX` 控批量不控单章。
- **`cn_numeral` 的零**：区间后缀从 1 起无零场景，但函数对 0/负数返回空串
  或抛错要定义（拍板：抛 ValueError，纯函数 fail-fast）。

## 7. 测试策略（全程不联网）

- **test_llm.py**：ThinkFilter 纯逻辑（完整对剥离/未闭合前缀扣住/跨 chunk
  标签 hold-back/纯思考流/无思考块直通）；`on_delta` 流式路径（FakeStream
  返回多 chunk：正常流、含思考块流、空流+length+reasoning -> 翻倍重试、
  中途抛异常 -> 退避重试、末 chunk 才有 finish_reason）；`on_delta=None`
  时请求体无 `stream` 键（现状回归）；temp 400 锁定后流式请求 temperature=1。
- **test_agent.py**：`stream=True` 时 `_writer`/`_polisher` 把 on_delta 传给
  FakeLLM（**kw 捕获断言）；`stream=False`（默认）时调用点无 on_delta 键
  （既有用例天然回归）；后处理（=== 分离/_strip_polisher_meta/字数保护）
  在 FakeLLM 模拟「增量分片返回拼接」下结果与非流式一致；`run(task, plan=...)`
  时 state.plan 进 record、`_writer` 的 user_msg 含【本章规划】块（空 plan
  不占位）。
- **storage 侧测试**：`parse_chapter_range` 命中（带/不带标题）/不命中/
  分隔符变体（`-`/`-`/`~`/`至`）；`parse_chapter_plan` 构造 markdown 断言
  （多表格合并、列头变体、分隔行跳过、脏行跳过、同章号后者覆盖）；
  `cn_numeral` 1-99 抽查 + 越界抛错。
- **test_cli_write.py**：`_write_one` 四种结局（saved/rejected/failed/
  interrupted--interrupted 用 monkeypatch agent.run 抛 KeyboardInterrupt）；
  `_do_write_batch` 无标题主路径（章纲供标题+规划、缺章报错零调用）、
  带模板回落路径（序数后缀 + 章纲照注入）、默认模式章间确认（y 连写/n 停止、
  已完成章保留）、--auto 中断路径（rejected -> break 后续章零调用）、
  failed/interrupted 中断、非法区间（起>止/超 batch_max）报错零调用、
  预算提示打印、单章无标题命令走章纲（`写第5章` -> 任务串与规划注入正确）、
  单章区间退化、`写第5章：标题` 不进批量（分发断言）。
- **test_config.py**：`NOVEL_STREAM`/`NOVEL_BATCH_MAX`/`NOVEL_CHAPTER_PLAN`
  默认值与覆盖解析。
- **回归命令**：`cli/` 下 `python -m pytest tests/ -q`，基线
  397 passed / 0 failed / 1 deselected（style-loop 完成态实测），零新增。

## 8. 决策表

### 8.1 继承决策（ROADMAP 已拍板）

| # | 决策 | 理由 |
|---|---|---|
| R1 | 流式输出 + 批量连写为一个 feature（throughput） | ROADMAP 阶段 2 整体定义 |
| R2 | 批量默认每章过目确认 | ROADMAP 2.2 原文（防跑偏累积，人在环 = 1.4 门禁天然兜底） |
| R3 | `--auto` 必须先定义低分章去向 | ROADMAP 1.4 推论（L147 前置设计题） |
| R4 | 章间自动更新工作记忆 + 入库 | ROADMAP 2.2 原文 |

### 8.2 设计决策（本 design 拍板）

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 流式接口形态 | a) 返回生成器；b) on_delta 回调 | **b** | 返回类型不变，全部调用点与 FakeLLM 零改动；增量如何呈现归调用方 |
| D2 | 思考块流式适配 | a) 收完再剥（不实时打印思考外的所有）；b) 增量过滤 | **b** | 思考模型思考段可达分钟级，不过滤则屏幕被思考淹没，违背「及时发现跑偏」的目的；数据侧仍收完再剥兜底 |
| D3 | 流式重试 | a) 中途异常返回部分文本；b) 整请求重来 | **b** | 部分文本对下游（===/quote 定位）是毒药；网关语义无「续传」，重来是唯一正确解 |
| D4 | 流式启用范围 | a) 全角色；b) 仅 writer/polisher | **b** | reviewer 短 JSON 流式无收益；评审/摘要稳定性优先（用户坑位提示） |
| D5 | Ctrl-C 打断 | a) 穿透退出 REPL；b) 中止本章回提示符 | **b** | 特性目的就是「中途发现跑偏直接打断」；退出 REPL 是反 UX |
| D6 | 批量任务来源 | a) 标题模板+序数后缀；b) 每章规划文件（章纲）驱动 | **b** | 用户既定工作流「先规划后写作」，`每章.md` 已含每章标题+核心事件+天气+矛盾种子；标题与写作方向一次解决（修订：原拍 a，2026-08-30 用户输入后改 b） |
| D7 | 解析落点 | a) cli.py 内联；b) storage.py 纯函数 | **b** | 纯函数可单测；与 parse_chapter_task 同居同风格（宪法 §5） |
| D8 | 单章路径复用 | a) 批量自写循环体；b) _do_write 拆 _write_one | **b** | 两套单章流程必漂移；批量只做编排（T17/T27 的结构保证） |
| D9 | --auto 低分章去向 | a) 中断批量；b) 隔离待审清单后继续 | **a** | 隔离的两难（不入库断连续 / 入库污染基准）无数据可解；门禁总原则：无人可交才 fail-closed，--auto 即无人 |
| D10 | 批量上限 | a) 不设限；b) NOVEL_BATCH_MAX 默认 10 | **b** | token 护栏（横切约束 L22）；手滑输错 50 章不至破产 |
| D11 | 标题优先级 | a) 章纲赢；b) 命令显式标题赢 | **b** | 用户当场敲的标题是更强意图；但显式标题不豁免规划注入（规划管内容，标题只管名字） |
| D12 | 规划注入范围 | a) writer+reviewer；b) 仅 writer | **b** | P0 最小面：writer 按规划产出，构思（outline）沿 0.8 链路喂下游；规划喂 reviewer 作验收基准留 P1 数据说话 |

### 8.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | `NOVEL_STREAM` 默认 1（开） | 特性目的即 UX；已核全部 FakeLLM 为 `(system, user, **kw)`，默认开零破坏。**已知风险（用户评审点名）：火山 ark coding 网关对 `stream=True` 的实际行为（reasoning_content 增量形态、流式 finish_reason 位置、空回翻倍路径）从未真车验证，默认开 = W2/W3 落地后所有写作即刻走流式。缓解：W2 完成后立刻 NOVEL_STREAM=1 真车冒烟一章（用户执行），不兼容则 `NOVEL_STREAM=0` 一行配置回退现状（兜底在，风险有界） |
| Z2 | `delta.reasoning_content` 只累积不外发 | 空回翻倍判定需要它；正文/打印侧都不掺（与 Z1 的思考块双路兜底互补） |
| Z3 | 区间分隔符认 `-`/`-`/`~`/`至` | 中文输入法全角形态是实际高频输入 |
| Z4 | 批量章间重建 agent 而非复用实例 | 章间状态依赖（wm/RAG/路由/滚动窗口）要求重建，是复用语义本身 |
| Z5 | 中断章不落 run record | record 是完成态留痕，半章无消费方；replay/compare 零适配 |
| Z6 | `cn_numeral` 越界抛 ValueError | 纯函数 fail-fast，同 `_env_float` 纪律 |
| Z7 | 章纲同章号重复取后者 | 修订覆盖草稿是文档自然语义 |
| Z8 | 规划要点全量注入不截断 | 它是「写什么」的核心指令，不是「像什么」的语料；单章预算靠既有 4096 档与 max_tokens 纪律兜底 |
