# 0.8 流水线数据流补漏（pipeline-dataflow）- 任务分解

> 依赖阅读：`requirements.md`（A1-A21）、`design.md`（含 D1-D9 开放决策）。
> 测试基线：`cd cli && PYTHONPATH=.deps python -m pytest`。
> 存量 3 个失败（`test_strip_polisher_meta`/`test_runtime_dir_override`/`test_defaults`）不属本范围，验收口径为「不新增失败」。

## P0（数据流闭环本体）

- [ ] **T1 删除 director（状态机与字段）** —— A1、A2
  - 改动：`state.py:30` 默认值 `"director"` -> `"writer"`、`state.py:19` 注释去 Director 表述；`agent.py:161-166` agents dict 删 `"director"` 项；`agent.py:211-214` 删 `_director` 方法。
  - 同步改断言：`test_state.py:10` 改 `== "writer"`；`test_agent.py:59` 改 `== 3`、`test_agent.py:94` 改 `== 6`（注释同步去掉 director）。
  - 验证：`python -m pytest tests/test_state.py tests/test_agent.py -k "happy_path or review_reject or max_reviews or default"`；另 `grep -rn director cli/novel_agent/` 零命中（`_director`/注册/默认值全清）。
  - 回归：`conftest.py:85-112` 的 `sample_run`（含 director step 旧格式）**保留不改**，用 `replay(sample_run)` 验证 A3（旧记录可回放，harness 不校验 agent 名）。

- [ ] **T2 PipelineState 新增构思字段** —— A4、A6
  - 改动：`state.py` 核心字段区新增 `outline: str = ""`（命名按 D1 拍板，缺省推荐 `outline`）。
  - 验证：`test_state.py` 的 asdict roundtrip 测试自动兼容（`PipelineState(**d)`），追加断言 `d["outline"] == ""`；`agent.run()` 后 `record["final_state"]["outline"]` 键存在（A6，asdict 自动进 record，replay 不读该键故 A20 由 T9 一并覆盖）。

- [ ] **T3 构思解析纯函数 + `_writer` 接线** —— A4、A5、A19
  - 改动：`agent.py` 模块级新增 `_split_writer_output(raw) -> Tuple[str, str]`（先例 `_strip_polisher_meta`）；`agent.py:247-251` 改为 `outline, body = _split_writer_output(raw)`，`state.outline = outline`、`state.draft = body`，空兜底（`agent.py:252-254`）不动。
  - 验证：纯函数直测四例（含 `===` / 不含 / 空串 / 正文内再出现 `===` 只按首个切）；改 `test_agent.py:276-290` `test_writer_strips_construction_notes`：保留 draft 断言 + 新增 `state.outline` 非空且含「构思」、`record["steps"]` 中 writer 步的 `output_state["outline"]` 有值。

- [ ] **T4 polisher 消费构思** —— A7
  - 改动：`_polisher`（`agent.py:258-294`）按 D7（user 尾部）追加 `outline_hint`（feedback_hint 同款模式）；D8 已拍板注入：在此处一并 `+ self._working_context()`（空态保护自带，A10）。
  - 验证：`fake_llm.script` 给「构思===正文」格式，断言 `fake_llm.calls` 中 polisher 那次调用的 user 消息含 `state.outline` 内容；outline 为空时（`agent.refine()` 场景）不注入空块（calls 中无「构思」字样的 hint 块）；快照注入与空态断言同 T5 口径（system 侧，D8）。

- [ ] **T5 reviewer 消费构思 + 前情注入** —— A8、A9、A10、A11
  - 改动：`_reviewer`（`agent.py:322-370`）system 构造追加 `+ self._working_context()`（D3 推荐：仅快照，`agent.py:338` 的 `with_prior=False` 不动）；user 消息追加 `outline_hint`（验收基准措辞）。
  - 验证：
    - `WorkingMemory(current_chapter=5, last_plot_point=..., unresolved_foreshadowing=[...])` 注入后跑 run，断言 reviewer 调用的 prompt 含快照四元组关键词（当前进度/未回收伏笔）--FakeLLM 只记 user（`conftest.py:28`），需临时给 FakeLLM 补记 system 或经子类断言；
    - `WorkingMemory()`（current_chapter=None）时 prompt 不含「当前写作状态」噪音；
    - `working_memory=None` 时流程照常（`agent.py:206-207` 既有保护）。

- [ ] **T6 长度配置链路** —— A12、A14、A15
  - 改动：`config.py` 编排控制组新增 `target_words: int = 1500`；`get_settings()` 追加 `int(os.environ.get("NOVEL_TARGET_WORDS", "1500"))`（D4/D5）；`agent.py __init__` 加 `target_words: Optional[int] = None` 回落 settings（同 `max_reviews` 模式 `agent.py:153`）；`agent.py:236` 「约200字」改 `f"目标约{self.target_words}字"`，rewrite 分支（`agent.py:227-233`）同样追加；`.env copy.example` 补 `NOVEL_TARGET_WORDS` 示例行。
  - 验证：`monkeypatch.setenv("NOVEL_TARGET_WORDS", "2200")` 后先 `get_settings.cache_clear()` 再重算 settings（`get_settings()` 带 `@lru_cache(maxsize=1)`（`config.py:141`），不 clear 会读到缓存旧值导致断言假红/假绿；用例收尾再 clear 一次防污染其他用例），断言 writer 调用的 user 消息含「目标约2200字」且不含「约200字」（两分支各一测）；`agent.run()` 后 `record["config"]["target_words"]` 存在（A15）；构造参数 `NovelAgent(..., target_words=800)` 覆盖生效。

- [ ] **T7 polisher_system 死参数接活** —— A13
  - 改动：`prompts.py:119-129` 函数体使用 `target_words`（目标篇幅行，措辞见 design §2.4）；`agent.py:262-264` 调用点传 `target_words=self.target_words`。
  - 验证：直测 `polisher_system("x", "", target_words=1800)` 返回串含「1800」；默认不传参时含「1500」。

- [ ] **T8 剧情摘要收编** —— A16、A17
  - 改动：`agent.py` 新增 `summarize_chapter(self, chapter_text, max_tokens=1024)`（D6，不吞异常）；`PLOT_SUMMARY_SYSTEM` import 从 `cli.py:33` 移至 `agent.py`；`cli.py:135-143` 改调 `agent.summarize_chapter(state.final_chapter)`，try/except 兜底留 cli。
  - 验证：FakeLLM + `agent.summarize_chapter("正文")` 断言 system 消息等于 `PLOT_SUMMARY_SYSTEM`、max_tokens=1024；cli 层 monkeypatch `summarize_chapter` 抛异常，断言摘要回落为 task 且流程不中断（A17）。

- [ ] **T9 回放兼容回归** —— A3、A20
  - 改动：无（纯回归验证；P1-c 如做 replay 展示构思才动 `harness.py`，且用 `.get("outline")` 容错）。
  - 验证：`replay(sample_run, tmp_settings, out=capturer)`（sample_run 含 director step、无 outline 字段）正常输出全部步骤与最终章节；`evaluate` 读 `final_state.next_agent/feedback`（`harness.py:168/177`）不受影响（跑一个新 record 过 evaluate 冒烟）。

- [ ] **T10 文档与叙述清理 + 全量回归** —— A2
  - 改动：`agent.py:1/126/450/484` docstring 四角色->三角色表述；`README.md` 等仓库文档 grep `director` 逐处修正（只改表述，不改早期规划、不动其他 specs/）。
  - 验证：`grep -rn -i "director" cli/ README.md` 复核仅剩历史 run JSON 样例与 git 历史中的合法残留；`cd cli && PYTHONPATH=.deps python -m pytest` 全量跑，对照存量 3 失败之外零新增失败。

## P1（收编外延与记忆刷新）

- [ ] **T11 refine/rewrite 后工作记忆刷新** —— A18、A21
  - 改动：`cli.py` 调用方 `agent, _ = _build_agent(settings)` 改为保留 wm 并传入 `_refine_postprocess`（签名加 wm）；`storage.py` 新增纯函数 `parse_chapter_file(path) -> Tuple[Optional[int], str]`（匹配 `save_chapter` 落盘格式「第05章-标题.md」，先例 `parse_chapter_task` `storage.py:47-56`）；`_refine_postprocess` 两个存回分支后按 D9 语义调 `agent.summarize_chapter` + `wm.update_after_write` + `save_working_memory`。
  - 验证：直测 `parse_chapter_file`（标准名 / 无章号名 / 带路径）；集成测（tmp_settings + monkeypatch cli 输入）跑 refine 后断言 `working_memory.json` 内容刷新（`last_plot_point` 变为 FakeLLM 摘要、`current_chapter` 按 D9-b 断言（精修最新章或首章时刷新、精修旧章时不回退，边界条件见 design §2.6））；文件名不匹配时跳过刷新不断流（A21）。

- [ ] **T12 对比器收编 `_is_better` -> `NovelAgent.is_better`** —— A16 总则
  - 改动：`cli.py:62-79` 迁为 `agent.py` 方法（system prompt 文案随迁，建议落 `prompts.py` 常量）；调用点 `cli.py:194` 改 `agent.is_better(content, state.final_chapter)`，cli 侧 try/except 兜底保留。
  - 验证：FakeLLM 返回 `{"better": true}` / 散文含 true / 异常三态，断言 `is_better` 返回与现状一致；cli 不再 `import` 内联 prompt。

- [ ] **T13（可选）replay 展示构思** —— A6 的展示面
  - 改动：`harness.replay` 步骤输出追加 `构思：{outline 前 N 字}` 行（`.get` 容错旧记录，只增行不改既有行）。
  - 验证：新 record 回放显示构思行；`sample_run` 旧 record 回放不报错、不显示空构思行。

## 验收对照表

| EARS | 任务 | 类型 |
|---|---|---|
| A1 | T1 | pytest |
| A2 | T1、T10 | grep + pytest |
| A3 | T9 | pytest |
| A4 | T2、T3 | pytest |
| A5 | T3 | pytest |
| A6 | T2、T3 | pytest（T13 可选展示） |
| A7 | T4 | pytest |
| A8 | T5 | pytest |
| A9 | T4、T5 | pytest |
| A10 | T4、T5 | pytest |
| A11 | T5 | pytest（保持性断言） |
| A12 | T6 | pytest |
| A13 | T7 | pytest |
| A14 | T6、T7 | pytest |
| A15 | T6 | pytest |
| A16 | T8（P0 摘要）、T12（P1 对比） | pytest |
| A17 | T8 | pytest |
| A18 | T11 | pytest |
| A19 | T3 | pytest |
| A20 | T9、T13 | pytest |
| A21 | T11 | pytest |

## 人工验收项（不进 pytest，端到端）

- 早期规划「同一任务可配出 2000+ 字章节」：`.env` 配 `NOVEL_TARGET_WORDS=2200`，真实模型跑一次 `write`，观察正文长度与是否出现截断腰斩（风险与边界见 design §6）。
- 早期规划「reviewer 的伏笔维度能引用前文」：连续写第 2 章后回看 run record 中 reviewer 的意见是否引用了工作记忆中的伏笔/进度信息。
