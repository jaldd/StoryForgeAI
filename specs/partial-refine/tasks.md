# 任务分解：局部精修（partial-refine）

> Feature: `partial-refine`
> 对应 `requirements.md` / `design.md`。每项可独立验证（附验证方式）。
> 宪法合规：纯函数不联网（§5）、LLM 调用 `max_tokens=4096`（§4）、无新依赖（§2）。

---

## P0（必须做）

### T1 段落模型与切分（partial.py）
- [x] 新建 `cli/novel_agent/partial.py`：`Block` dataclass（no/kind/text/body）+ `split_paragraphs(text) -> List[Block]`
- [x] 空行切块；空行归前段尾部；开头悬挂空行（含 BOM）聚为 preamble 匿名块；第一个内容块为章节头 -> `title`（不编号，复用 `storage._LEADING_TITLE_RE` 思路）；独立 `---` -> `sep`（不编号）；其余 `para` 从 1 编号
- [x] 输入用 `read_bytes().decode("utf-8")`、切分用 `splitlines(keepends=True)`（保 `\r\n`/BOM/文件尾）
- **验证**：`pytest tests/test_partial.py -k split` -- 含 `\r\n`、BOM、标题、`---`、连续空行、单行文件、开头空行+BOM 的 7 个用例全绿

### T2 选段解析（partial.py）
- [x] `parse_selection(spec, max_no) -> List[Tuple[int, int]]`：`3` / `3-5` / `3,7` / `3-5,7`；相邻编号合并为区间；`0`/超界/`5-3`/非数字抛 ValueError（消息含原因）
- **验证**：`pytest tests/test_partial.py -k parse` -- 合法 5 式返回正确区间、非法 4 式抛错且消息可读

### T3 上下文构造（partial.py）
- [x] `build_context_pair(blocks, span) -> (before, after)`：取物理相邻块（sep/title 亦可），首/末段返回空串
- **验证**：`pytest tests/test_partial.py -k context` -- 前后各一块、`---` 作上下文、文件首末段三用例全绿

### T4 回填（partial.py）
- [x] `apply_replacements(text, blocks, spans, new_texts) -> str`：区间整块替换（区间内空行结构一并替换），区间末块尾部空行保留；区间外字节不动
- **验证**：`pytest tests/test_partial.py -k apply` -- 改 3-5 后选区外前后缀 `read_bytes` 级不变；多区间用例（`3,7`）各自替换；`---`/title 不变

### T5 prompt（prompts.py）
- [x] 新常量 `PARTIAL_REFINE_SUFFIX`（只润色片段/情节不动只改表达/只返回片段本身/勿改写返回上下文）
- [x] 新函数 `partial_refine_user(before, selection, after) -> str`（三段式标记）
- **验证**：`pytest tests/test_agent.py -k partial_prompt` -- suffix 拼接后含 polisher 全部铁律文本；user 函数输出含三个标记段；before/after 为空串时占位不出现

### T6 agent.partial_refine（agent.py）
- [x] `NovelAgent.partial_refine(blocks, spans, task, run_id=None) -> List[str]`：每 span 一次 `llm.chat(polisher_system(...) + PARTIAL_REFINE_SUFFIX, partial_refine_user(...), max_tokens=4096, temperature=0.6)`；输出过 `_strip_polisher_meta` + 剥代码围栏；空回记为失败（返回 `None` 项）
- [x] 检索复用 `self._retrieve(task)`（task 形如 `局部精修：<文件名>`）
- **验证**：`pytest tests/test_agent.py -k partial_refine` -- FakeLLM 下断言：user 含选区+上下文、不含选区外正文；`3,7` 恰好 2 次调用；围栏+润色说明被清洗；空回返回失败标记

### T7 cli 命令（cli.py）
- [x] 新 `_do_partial(args, settings)`：参数校验 -> `require_novel_dir` -> `_build_agent` -> 路径解析（`rag._resolve_source` + `" ".join(args)`）-> 读 bytes -> 切分 -> 打印列表（`preview_line`，编号: 预览40字（字数））-> input 选段（非法重输，空/`q` 取消）-> 选区统计 -> `agent.partial_refine` -> `apply_replacements` -> 长度突变 ⚠️（>3×/⅓，D6）-> diff（`difflib.unified_diff`，选区原文 vs 改后，多区间按区间分段展示 R2）-> input 确认 -> `y`：`write_bytes` + `rag.add_document`；否则放弃
- [x] 选段/确认两处 input 局部捕获 `KeyboardInterrupt`/`EOFError` -> 取消（REPL 不退出）；`_do_partial` 整体再包一层同款捕获，覆盖 LLM 生成中途的 Ctrl-C（R1，取消时文件不动）
- [x] `main()` 加 `elif cmd == "改": _do_partial(args, settings)`（`cli.py:444-447` 旁）；`_print_help()` 与模块 docstring 加命令说明
- **验证**：`pytest tests/test_cli_partial.py` -- monkeypatch input 序列：y 全流程（文件改、选区外字节不变、FakeRag.add_document 被调）；n 取消（字节不变、无 add 调用）；非法选段重输后取消；input 抛 KeyboardInterrupt 视为取消；FakeLLM.chat 抛 KeyboardInterrupt（模拟生成中途）同样取消且文件不动

### T8 P0 端到端验收（人工，真实 LLM）
- [ ] 真实小说目录下对一章执行 `改`：选 3-5 段改写、确认 y
- [ ] 核对 ROADMAP 0.4 三条：其余段落逐字节不变（可用 `git diff` 或前后文件字节对比）；`---` 与章节头保留；差异展示只含选区
- [ ] 改后再写一章，检索能命中该章新内容（重索引生效）
- **验证**：以上三条逐项核对通过，记录在 spec 验收结果

---

## P1（应该做）

### T9 run 留痕
- [x] 确认 y 后构造 record（`run_id="partial_时间戳"`、`mode`、选区区间、各区间原文/改后、`final_state.final_chapter`=回填后全文）调 `storage.save_run`
- **验证**：`pytest tests/test_cli_partial.py -k run_log` -- y 流程后 runs 目录出现 `partial_*.json`，`replay <run_id>` 能打印改写结果（复用 harness.replay，steps=[]）

### T10 帮助与文档
- [x] `cli/README.md` 命令表加 `改 <文件路径>` 行；`help` 输出与 docstring 已在 T7 同步
- **验证**：REPL 输入 `help` 可见新命令；README 表格含新行

---

## P2（可以做）

### T11 确认时重新生成（r 键）
- [ ] 确认提示改为 `y/n/r`：`r` 重新调用 `partial_refine`（同选区）再展示新 diff；`n` 放弃
- **验证**：monkeypatch input 序列（r 一次后 y）-> 最终文件用第二次改写结果；FakeLLM 调用数 = 区间数 × 2

### T12 管线接口固化（供 1.6 复用）
- [ ] 复核 `partial.py` 导出 API（split/parse/context/apply）签名与注释，确保「checker 找问题句 -> 区间 -> 改写 -> 回填」可无 cli 依赖调用
- **验证**：新增一条纯函数级测试模拟 1.6 场景：给定问题句行号区间 -> 构造上下文 -> apply 回填成功

---

## 验收对照（requirements EARS -> tasks）

| 验收 | 覆盖任务 |
|------|----------|
| A1-A3 段落列表 | T1/T7 |
| A4-A6 选段 | T2/T7 |
| A7 润色输入只含选区+上下文 | T5/T6 |
| A8-A10 回填与 diff | T4/T7 |
| A11-A13 确认/取消/异常 | T7 |
| A14-A16 失败路径 | T6/T7 |
| A17 留痕 | T9 |
| ROADMAP 0.4 三条 | T8 |
