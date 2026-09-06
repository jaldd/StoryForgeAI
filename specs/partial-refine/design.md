# 技术设计：局部精修（partial-refine）

> Feature: `partial-refine`
> 对应 `requirements.md`。本文是**开工前设计稿**，未实现。
> 遵循 `.specify/memory/constitution.md`；结论沿用早期规划条目 0.4。

---

## 1. 目标回顾

新增 `改 <文件>` 命令：段落编号列表 -> 选段 -> 选区级润色（跳过 reviewer）-> 区间整块回填（其余逐字节不变）-> diff + y/n 确认 -> 存回 + 重新入索引。产出可复用的「选区+上下文 -> 改写 -> 回填」管线，供阶段 1.6 规划复用。

---

## 2. 现状与证据（先读代码后下的结论）

### 2.1 整章流水线的调用链（token 按整章付）

| # | 论断 | 证据 |
|---|------|------|
| 1 | `精修` 读整个文件、整章送入流水线 | `cli/novel_agent/cli.py:239`（`content = path.read_text(...)`）→ `cli.py:247`（`agent.refine(content, task)`）；`agent.py:386`（`state.draft = content`） |
| 2 | polisher 全文调用一次 | `agent.py:240-245`（`self.llm.chat(system, f"以下是初稿，请润色：...{draft_safe}", max_tokens=4096, ...)`） |
| 3 | reviewer 再全文调用一次 | `agent.py:277-282`（`chat(..., f"请审查以下稿件：...{state.polished}", max_tokens=2048)`） |
| 4 | 强制定稿时第三次全文调用（对比好坏） | `cli.py:174`（`_is_better(agent.llm, content, state.final_chapter)`）；`cli.py:53-69`（两段全文截断 2000 字对比） |
| 5 | 存回后还跑一次全文评测 | `cli.py:212-216`（`evaluate(record["run_id"], ...)`）；`harness.py:125-130`（全文送评委） |
| 6 | 字数保护只看长度不看内容 | `agent.py:256-261`（`len(state.polished) < len(state.draft) * 0.5` 即保留初稿，不看改了什么） |
| 7 | 整章覆盖存回（好段陪着返工） | `cli.py:164` / `cli.py:178`（`path.write_text(state.final_chapter, ...)`） |
| 8 | 精修模式下 reviewer 打回即整章重润 | `agent.py:390-399`（`refine_agents = {polisher, reviewer}`，打回目标 polisher） |

**结论**：只想改一小段时，现状至少付 2 次全文调用（润色+审稿），最坏 4 次（+好坏对比+评测）；且每次整章覆盖存回都有把好段润坏的风险（#6/#7）。阶段 0.4 规划的痛点成立。

### 2.2 可复用的既有资产

| 资产 | 证据 | 复用方式 |
|------|------|----------|
| `---` 是场景分隔符的约定 | `agent.py:235`（`draft_safe = state.draft.replace("\n---\n", "\n【场景分隔】\n")`，注释「--- 是场景分隔符，不能截断」） | 段落切分把独立 `---` 行识别为不编号的分隔块 |
| 章节头格式与识别正则 | `storage.py:118-126`（存盘写 `第{num}章 {title}\n\n` 头）；`storage.py:31-32`（`_LEADING_TITLE_RE`） | 段落切分识别文件头章节标题块（不编号） |
| polisher 输出清洗 | `agent.py:77-98`（`_strip_polisher_meta`：截「## 润色说明」、去 meta 标题） | 局部润色输出做同样清洗 |
| polisher system prompt | `prompts.py:55-65`（`polisher_system(novel_name, retrieved, instruction, target_words)`） | 局部润色 system = `polisher_system(...)` + 附加「只改选区」指令（见 §6.2，零复制，0.2 重构自动受益） |
| RAG 检索（设定注入） | `agent.py:138-168`（`_retrieve`） | `partial_refine` 内复用，为选区润色提供设定约束 |
| 存回后重索引 | `rag.py:214-241`（`add_document`：先 `delete(where={"source": src})` 再 upsert，块数变化不留孤儿） | 回填存回后调用，与精修一致（`cli.py:166-170`） |
| 路径解析 | `rag.py:207-212`（`_resolve_source`：相对路径按 `NOVEL_DIR` 解析）；`cli.py:234`（`_do_refine` 已这样用） | `改` 命令沿用（含 `cli.py:230` 的 `" ".join(args)` 容忍路径含空格） |
| diff 展示 | `cli.py:204-210`（`difflib.unified_diff`，`n=1`） | 确认前 diff 复用同一工具，输入改为「选区原文 vs 改后文本」 |
| REPL 命令分发 | `cli.py:421-461`（`parts = line.split()`; `cmd = parts[0]`；`精修`/`重写` 在 `cli.py:444-447`） | 新增 `elif cmd == "改":` 分支；注意 `cli.py:432` 的 `startswith("写")` 拦截不冲突（「改」≠「写」开头） |

### 2.3 测试契约现状（影响测试策略）

- 无 `test_cli.py`：交互层目前无测试先例，本 feature 需要建立（monkeypatch `input`）。
- `FakeLLM`（`tests/conftest.py:16-35`）按用户消息关键词分流（含「润色」→ 润色稿）；可传 `script` 精确控制。
- `FakeRag`（`conftest.py:38-45`）只有 `retrieve`/`search_knowledge`，**没有** `add_document`--本 feature 的 cli 测试需为其补 stub。
- `harness.py` 全函数接收 `out` 参数便于捕获输出（`harness.py:9` 注释）；本 feature 的命令处理沿用 `print`（与 `_do_refine` 一致），测试用 `capsys`。
- `list_runs` 只 glob `run_*.json`（`storage.py:89`）--现有 `refine_`/`rewrite_` 前缀的 run 本就不在列表中，`partial_` 同样不列，**与现状一致，不修**（见 §9 开放问题 2）。

---

## 3. 总体架构与数据流

不新增进程/服务，在现有分层内加一条「旁路」：整章流水线（agent 状态机）不动，局部精修走「纯函数（partial.py）+ 单次 LLM 调用（agent.partial_refine）+ cli 交互」。

```
用户输入：改 <文件路径>
   ↓
cli.py  _do_partial(args, settings)
   ├─ 1. 解析路径（rag._resolve_source）→ 读文件字节 → decode
   ├─ 2. partial.split_paragraphs(text)          ── 纯函数，无 IO
   │      → [Block]（title / sep / para，para 带编号）
   ├─ 3. 打印段落列表（编号 + 预览 + 字数）
   ├─ 4. input 选段 → partial.parse_selection     ── 纯函数，校验+归一化为区间列表
   ├─ 5. agent.partial_refine(blocks, spans, task)
   │      ├─ _retrieve(task)                       （设定注入，同 polisher）
   │      ├─ 每 span 一次 llm.chat：
   │      │    system = polisher_system(...) + PARTIAL_REFINE_SUFFIX
   │      │    user   = prompts.partial_refine_user(前文块, 选区文本, 后文块)
   │      │    max_tokens=4096, temperature=0.6
   │      └─ 输出清洗（_strip_polisher_meta + 去代码围栏）→ List[改写文本]
   ├─ 6. partial.apply_replacements(text, spans, new_texts) ── 纯函数，逐字节保真回填
   ├─ 7. 打印 diff（选区原文 -> 改后，多区间按区间分段）+ 长度异常警告（可选）
   ├─ 8. input 确认 y/n
   │      y → write_bytes 存回 → rag.add_document(file_path) → (P1) save_run 留痕
   │      n/其他/Ctrl-C → 放弃，文件不动
   └─ 9. help / docstring / README 同步
```

### 3.1 命令交互完整时序

```
用户                          _do_partial / partial.py           agent.partial_refine      LLMClient
 │ 改 第05章-x.md                  │                                  │                      │
 │────────────────────────────>│ require_novel_dir 校验               │                      │
 │                              │ _build_agent（同精修）               │                      │
 │                              │ 读 bytes → decode → split_paragraphs │                      │
 │                              │── 打印「N 个段落，M 段可编号」──────>│                      │
 │                              │── 打印编号列表（1: 预览…字数）──────>│                      │
 │                              │<─ input：选段（3 / 3-5 / 3,7）      │                      │
 │ 3-5                          │ parse_selection 校验                │                      │
 │────────────────────────────>│   非法 → 打印原因，重新 input        │                      │
 │                              │── 打印选区统计（2 段，412 字）──────>│                      │
 │                              │── partial_refine(blocks, spans) ─>│ _retrieve(task)       │
 │                              │                                    │ system+user ───────>│ chat(4096)
 │                              │                                    │<──── 改写文本 ──────│
 │                              │<── [改写文本] ─────────────────────│                      │
 │                              │ apply_replacements → new_content    │                      │
 │                              │── 打印 diff（选区原文 → 改后）──────>│                      │
 │                              │   （长度突变 → 先打 ⚠️ 警告）        │                      │
 │                              │<─ input：确认存回？(y/n)            │                      │
 │ y                            │ write_bytes + rag.add_document      │                      │
 │────────────────────────────>│ (P1) save_run(partial_记录)          │                      │
 │                              │── 打印「✅ 已存回 + 已索引」────────>│                      │
```

---

## 4. 段落模型（partial.py 核心数据结构）

```python
@dataclass
class Block:
    no: Optional[int]   # 段落编号，从 1 递增；标题块/分隔块为 None
    kind: str           # "title" | "sep" | "para" | "preamble"（文件开头悬挂空行，含 BOM，不编号）
    text: str           # 原始文本（keepends，含段尾空行，保 \r\n）
    body: str           # 内容部分（不含尾部空行）
```

**切分算法**（`split_paragraphs(text) -> List[Block]`）：

1. `text.splitlines(keepends=True)` 保留行尾字节。
2. 聚合：连续「strip 后非空」的行聚为一块；块后的空行**归入该块尾部**（回填拼接后空行结构不变）；文件开头的悬挂空行（含 BOM）聚为一个 preamble 匿名块（不编号）。
3. 分类与编号：
   - 第一个内容块（跳过 preamble）若**单行**且匹配章节头模式（复用 `storage.py:31-32` 的 `_LEADING_TITLE_RE` 思路：`^\s*(?:#+\s*)?第\s*<数字/中文数字>\s*章`）-> `kind="title"`，不编号；
   - 块内容 strip 后等于 `---` → `kind="sep"`，不编号；
   - 其余 → `kind="para"`，按出现顺序从 1 编号。

**回填算法**（`apply_replacements(text, blocks, spans, new_texts) -> str`，签名与 §6/T4 统一）：

- `spans` 是编号区间列表（升序、互不重叠，由 `parse_selection` 保证）。
- 每个区间覆盖的**全部块**（含区间内部的空行结构）整块替换为：`new_text.rstrip("\n") + 区间末块原尾部空行`（若有）。
- 区间外的所有块原样拼接（含 `\r\n`、BOM、文件尾字节）。
- 输出 = 全量新文本；写回用 `path.write_bytes(new.encode("utf-8"))`。

**选区解析**（`parse_selection(spec, max_no) -> List[Tuple[int, int]]`）：

- 语法：`<no>` | `<a>-<b>` | 逗号组合（`3-5,7`）；项间允许空格。
- 边界口径（实现拍板，回填）：全角逗号 `，` 等半角字符集外的输入按**非法字符拒绝重输**（错误提示写明只支持数字/连字符/逗号/空格，重输成本极低，不静默转写）；连续分隔符（`3,,5`、`3 5`）**宽容合并**为一个逗号；仅分隔符无编号（如 `,`）报错。
- 校验：`1 <= no <= max_no`；`a <= b`；非法字符拒绝。返回升序去重合并后的区间列表（如 `3,4,5` 合并为 `[3,5]`）。

**上下文构造**（`build_context_pair(blocks, span) -> (before, after)`）：

- 取选区首段**物理前**最近的 1 个块、末段**物理后**最近的 1 个块（无论 kind：`---`、章节头也可以是上下文，保持文本流原貌）。
- 文件首段无 before、末段无 after 时返回空串。

---

## 5. 关键设计决策

### 5.1 「逐字节不变」的工程保证

- **读**：`path.read_bytes().decode("utf-8")`，不用 `read_text`（universal newline 会把 `\r\n` 归一成 `\n`，破坏字节保真；`Path.read_text` 的 `newline` 参数 3.13 才有，项目要求 3.11+）。
- **写**：`path.write_bytes(new.encode("utf-8"))`（`write_text` 默认会把 `\n` 翻译成 `os.linesep`，Windows 上引入 `\r\n` 差异）。
- **切分**：`splitlines(keepends=True)` 保留原始行尾。
- BOM（`\ufeff`）：decode（非 `utf-8-sig`）保留在首块头部，回填原样保留。
- 验收 A9 用 `read_bytes()` 对比选区外前后缀实现（见 §8 测试策略）。

### 5.2 局部润色的 prompt 设计

- **system** = `polisher_system(novel_name, retrieved, instruction)` 原样输出 + `PARTIAL_REFINE_SUFFIX`（新增常量，要点：只润色片段、情节不动只改表达、只返回改写后的片段本身、不加标题/说明/代码围栏、上下文仅供理解不要改写或返回）。**不复制** polisher 的铁律文案--0.2（铁律外迁）重构时此处零成本跟随。
- **user** = `partial_refine_user(before, selection, after)`（prompts.py 新纯函数）：三段式标记——`【上文（勿改写，勿返回）】` / `【待润色片段（只返回这段的改写结果）】` / `【下文（勿改写，勿返回）】`。
- **调用参数**：`max_tokens=4096, temperature=0.6`，与 polisher 现状一致（`agent.py:240-245`）；宪法 §4 合规。
- **检索**：`task = f"局部精修：{path.name}"`，`_retrieve(task)` 注入设定（`with_prior=True` 默认，选区润色同样受益于前文参考；top_k=3 与现状一致）。
- **不注入** exemplar（polisher 现状也不注入，保持一致）。

### 5.3 多区间 = 每区间一次 LLM 调用

早期规划的「单次调用」理解为**选区级而非整章级**（相对整章流水线 5-6 次调用）。对不连续选段（`3,7`）：

- 每个连续区间独立调用一次（各自的 before/after 上下文清晰，prompt 无歧义）；
- 所有区间改写完**统一**回填、diff **按区间分段展示**（每个区间独立 diff，避免不相邻改动的上下文互相干扰）、**一次** y/n 确认、**一次**存回。
- 理由：合并一次调用会让两个选区的上下文边界模糊（区间 3 的「后文」是 4，不是 6），LLM 容易把中间未选段落也改了；每区间一次在结构上强制了「只动选区」。
- 备选（合并单次）记入开放决策，若拍板合并则 prompt 需加区间标签（A/B）并拆解返回。

### 5.4 防线：LLM 返回与选区不匹配

结构性安全：回填只替换区间内字节，**即使 LLM 返回了整章重写，损害也被限制在选区位置**，选区外不可能被破坏。在此之上加三层软防护：

1. **清洗**：`_strip_polisher_meta`（复用）+ 剥 ``` 围栏 + strip。
2. **警告**：`len(new) > 3 * len(old)` 或 `< len(old) / 3` 时打印 ⚠️（返回了整章/内容坍缩的信号），不拦截。
3. **人审**：diff 确认是最终门禁（A12），且 diff 输入是「选区原文 vs 改后」全量对照，异常一目了然。

与早期规划门禁总原则一致：机器拿不准时交给人，不 fail-closed（REPL 有人）。

### 5.5 交互取消的异常语义

- `_do_partial` **全程**包裹 `try/except (KeyboardInterrupt, EOFError)` -> 视为取消（打印提示后返回），**不**传播到 REPL 主循环（`cli.py:417-468` 的 try 只兜 `input(">>> ")` 层，命令内部 Ctrl-C 若不捕获会终止整个 REPL，见 `cli.py:424-426`）。
- 覆盖三处：选段 input、LLM 生成中途（用户最常想打断的环节）、确认 input；取消时文件必然未动（落盘只发生在确认 y 之后）。
- 这是对现有命令行为的一个**增量改进**，仅作用于新命令，不动 `_do_refine`（范围纪律）。

### 5.6 run 留痕（P1）

- `run_id` 前缀 `partial_`；记录 `mode="partial-refine"`、文件路径、选区区间、每区间原文/改后文本、确认结果、回填后全文（放 `final_state.final_chapter`，`replay` 现成可读，`harness.py:36-46`）。record 必须含 `replay` 直读的 6 键：`run_id`/`task`/`timestamp`/`config`/`steps`/`final_state`（`harness.replay` 无缺键容错，缺任一直接 KeyError）；`initial_state` **不被 replay 读取**（复核勘误：规格早稿曾误列为必需键），作为与既有 record 格式对齐的完备键包含，无害。
- `steps` 留空数组（无状态机步；replay 打印「共 0 步」+ 最终章节，可接受）。
- 留痕发生在**用户确认 y 之后**（取消不留痕，与「未发生」语义一致）。

---

## 6. 模块改动清单（精确到函数）

| 文件 | 改动 |
|------|------|
| **新增** `cli/novel_agent/partial.py` | `Block`（dataclass）；`split_paragraphs(text) -> List[Block]`；`parse_selection(spec, max_no) -> List[Tuple[int,int]]`；`build_context_pair(blocks, span) -> Tuple[str, str]`；`apply_replacements(text, blocks, spans, new_texts) -> str`；`preview_line(block, width=40) -> str`。全部纯函数，无 IO、无 LLM |
| `cli/novel_agent/prompts.py` | 新常量 `PARTIAL_REFINE_SUFFIX`（片段润色附加指令）；新函数 `partial_refine_user(before, selection, after) -> str` |
| `cli/novel_agent/agent.py` | `NovelAgent` 新方法 `partial_refine(self, blocks, spans, task, run_id=None) -> List[Optional[str]]`（空回为 `None` 项，与 T6 一致）：逐 span 调 `llm.chat`，内部复用 `self._retrieve(task)`、`polisher_system(...)`、`_strip_polisher_meta`。**不**走 `_run_loop` 状态机 |
| `cli/novel_agent/cli.py` | 新函数 `_do_partial(args, settings)`（读文件/列表/选段/调 agent/回填/diff/确认/存回/`rag.add_document`/P1 留痕）；`main()` 循环加 `elif cmd == "改": _do_partial(args, settings)`；`_print_help()`（`cli.py:392-403`）与模块 docstring 命令表（`cli.py:1-12`）加说明 |
| `cli/novel_agent/rag.py` | **不改**（`add_document` 复用；`_resolve_source` 沿用现有跨模块调用先例 `cli.py:234`） |
| `cli/novel_agent/storage.py` | **不改**（P1 留痕直接用现有 `save_run`，record dict 由 cli 构造） |
| `cli/tests/conftest.py` | `FakeRag` 补 `add_document(self, file_path, progress=None) -> int`（记录调用并返回 0，供 cli 测试断言） |
| `cli/tests/` 新增 `test_partial.py` | 见 §8 |
| `cli/tests/test_agent.py` | 补 `partial_refine` 用例（prompt 内容断言、清洗、空回） |
| `cli/tests/` 新增 `test_cli_partial.py` | 命令交互测试（monkeypatch `input`） |
| `cli/README.md` | 命令表加 `改 <文件路径>` 一行 |

---

## 7. 边界与失败路径

| 场景 | 系统行为 | 对应验收 |
|------|----------|----------|
| 未带参数 | 打印用法：`改 <文件路径>（相对 NOVEL_DIR 或绝对路径）` | - |
| `NOVEL_DIR` 未配置 | ❌ 提示（复用 `require_novel_dir`，同 `cli.py:224-228`） | - |
| 文件不存在 | ❌ 找不到文件，退出命令 | A2 |
| 文件为空 | ⚠️ 文件为空，跳过（同 `cli.py:240-242`） | A2 |
| 无可编号段落（仅标题/`---`） | 提示「无可选段落」，退出 | A3 |
| 选段非法（0/超界/倒置/非数字） | 打印具体原因，重新 input；空回车/`q` 取消 | A5/A6 |
| LLM 空回（`LLMClient` 内部已重试 5 次，`llm.py:68` 返回 `""`） | ❌ 「模型未返回内容，未改动」，退出，文件不动 | A14 |
| LLM 返回整章/超长（>3×）或坍缩（<⅓） | ⚠️ 长度异常警告 + 正常进入 diff 确认 | A15 |
| LLM 返回带说明/标题/围栏 | 清洗后回填（`_strip_polisher_meta` + 剥围栏） | A8 |
| 确认输入 `n`/其他非 `y` | 放弃，原文件字节不变，不重索引 | A12 |
| 任一环节 Ctrl-C / Ctrl-D（含生成中途） | 视为取消，不写文件，REPL 存活 | A13 |
| `rag.add_document` 抛错 | ⚠️ 警告，文件已存回不回滚（同 `cli.py:169-170` 精修现状） | A16 |
| 选区极大（如整章全选） | 不设硬上限（用户自由）；预览列表与 diff 自然变长。软提示阈值记入开放决策 | - |
| 文件仅一行无空行 | 整个文件是 1 个 para 块，正常可选可改 | - |

**明确不做**：选段期间的文件外部并发修改防护（REPL 单线程）；选区长度硬限制；diff 分页。

---

## 8. 测试策略

原则（宪法 §5）：纯函数不 mock 直测；LLM 一律 FakeLLM；交互层 monkeypatch `input` + `capsys`；全程不联网。

### 8.1 `test_partial.py`（纯函数，无 mock）

| 用例 | 断言要点 |
|------|----------|
| split 基本切分 | 空行分块；连续空行归前段尾部 |
| split 识别 `---` | sep 块不占编号；编号连续正确 |
| split 识别章节头 | 首行 `第5章 标题`（含 markdown `#` 变体、中文数字）为 title 块不占编号 |
| split 保真 | `\r\n`、BOM、文件尾无换行、开头悬挂空行均原样保留（`read_bytes` 级） |
| parse_selection | `3`→`[[3,3]]`；`3-5`；`3,7`；`3-5,7`；`3,4,5` 合并 `[3,5]`；`0`/`99`/`5-3`/`abc` 抛错（错误消息含原因） |
| build_context_pair | 前后取物理相邻块（含 sep/title 也算）；首段无 before；末段无 after |
| apply_replacements | 改 3-5 后：选区外前缀/后缀 `read_bytes` 级不变；多区间各自替换；区间末尾空行保留；`---` 与 title 块不动 |

### 8.2 `test_agent.py` 增补（FakeLLM）

| 用例 | 断言要点 |
|------|----------|
| partial_refine 单区间 | `fake_llm.calls` 里 user 消息**含**选区与前后上下文、**不含**选区外正文；返回清洗后文本；`max_tokens=4096`（FakeLLM 记录 kwargs 或读 script 次数=区间数） |
| partial_refine 多区间 | `3,7` → 两次 chat 调用，两次返回按序对应 |
| partial_refine 清洗 | script 返回「```…``` 围栏 + ## 润色说明」→ 清洗后只剩片段 |
| partial_refine 空回 | script 返回 `""` → 结果标记失败（None/异常），cli 层不落盘 |

### 8.3 `test_cli_partial.py`（交互层）

- monkeypatch `builtins.input` 按序返回（选段 -> 确认）；`tmp_path` 造小说目录与章节文件（含章节头、`---`、多段落、`\r\n` 行尾样本各一）；`_build_agent` 不接受注入参数，测试需 `monkeypatch.setattr(cli, "_build_agent", ...)` 替换为返回 FakeLLM/FakeRag 的构造函数（FakeRag 补 `add_document` 后可断言被调用）。
- 用例：y 全流程（文件改、选区外字节不变、add_document 调用）；n 取消（`read_bytes` 前后一致、无 add 调用）；非法选段 → 重新提示 → 取消；Ctrl-C 模拟（input 抛 KeyboardInterrupt）→ 取消。

### 8.4 端到端验收（人工，真实 LLM）

对阶段 0.4 规划三条验收逐项核对：改 3-5 段后其余段落逐字节不变；`---` 与章节头保留；差异展示只含选区。

---

## 9. 开放问题（实现中发现的相邻问题，不实施）

1. **整章 `精修` 的 `_is_better` 也是全文调用**（`cli.py:53-69`）：强制定稿分支的对比与 `evaluate` 的全文评测都不在局部通道内，整章命令的 token 问题依旧。属早期规划阶段 1（门禁统一 1.4）范畴。
2. **`list_runs` 只列 `run_*.json`**（`storage.py:89`）：`refine_`/`rewrite_`（及本 feature 的 `partial_`）run 均不出现在 `状态` 命令里。现状行为，若要修属存储层小改，本 feature 不动。
3. **`cli.py` 跨模块访问 `rag._resolve_source` 私有方法**（`cli.py:234` 先例，`改` 命令沿用）：理想做法是 rag 暴露公共 API。待 0.5/0.6 系列重构时统一处理。
4. **`add_document` 的 `progress=print` 默认参数**（`rag.py:214`）：cli 调用不传时向终端打印「✅ 已索引…」，局部精修沿用此行为（与精修一致），不做静默化。
5. **段落切分不区分一个/多个空行**，也不理解 markdown 列表/引用块（整块当一个 para）。若未来需要更细结构（如 1.5 动态文风注入），届时扩展 `split_paragraphs`，接口已按块模型预留。
6. **`改` 之后不跑 `evaluate`**：与精修行为的有意差异（token 预算；评分对象是全章而非选区）。REPL 中人可自行 `eval`。

---

## 10. 异议（对阶段 0.4 规划结论的复核）

**无异议。** 逐条复核结论均可直接沿用：「跳过 reviewer，人就是门禁」「按段落区间整块回填」「选区级 token」「复用管线供 1.6」均成立且与本设计一致。唯一需要解释口径的是「单次调用」对不连续多区间的含义（见 §5.3，已按「每区间一次」设计并列入开放决策，不改变早期规划的 token 预算意图）。

---

## 11. 开放决策（需人拍板，实现前确认）

| # | 决策点 | 本设计采用 | 备选 |
|---|--------|-----------|------|
| D1 | 命令名 | `改 <文件>`（早期规划原文） | `局部精修` / `改段` |
| D2 | 选段语法 | `3` / `3-5` / `3,7` / `3-5,7`（组合支持） | 仅早期规划示例三式，不组合 |
| D3 | 不连续多区间调用次数 | 每区间一次 LLM 调用，统一确认存回 | 合并为一次调用（prompt 加区间标签） |
| D4 | 上下文窗口 | 物理相邻块各 1 块（`---`/章节头可作上下文） | 仅取编号段作上下文，跳过 sep/title |
| D5 | 选区大小软上限 | 不设限（人自由，diff 兜底） | 超 N 字警告/拒绝 |
| D6 | LLM 返回长度突变 | ⚠️ 警告不拦截（阈值 3×/⅓） | 自动拒绝并要求重试 |
| D7 | run 留痕 | 做（P1，`partial_` 前缀，replay 可读） | 不做 |
| D8 | 确认键位 | `y`/`n`（Ctrl-C=取消）；`r` 重新生成放 P2 | 直接做 `r` |
| D9 | 存回后是否跑 `evaluate` | 不跑（token 预算，与精修的有意差异） | 与精修保持一致跑 |
| D10 | 段落列表展示 | 全量列出，预览 40 字，不分页 | 分页/仅前后若干段 |

复核补充决策（2026-08-28 评审拍板）：

- **R1**：`_do_partial` 全程可 Ctrl-C / Ctrl-D 取消（含 LLM 生成中途），见 §5.5；测试补「生成中途打断」用例。
- **R2**：多区间 diff 按区间分段展示（各选区独立 diff），见 §5.3 / A10。
- 另：A15 长度警告建议加 `len(old) >= 50` 前置（选区过短时 3×/⅓ 阈值必触发，纯噪音）。
