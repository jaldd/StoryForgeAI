# 阶段 1 后半：文风闭环（style-loop）- 任务分解

> 对应需求：`requirements.md`（B1-B20）；详细设计：`design.md`（D1-D8/Z1-Z6）。
> 开工前状态：`quality-gate` T1-T11 已完成（本 feature 消费其 checker/ai_flavor_score/回填管线）。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` = 362 passed / 0 failed / 1 deselected，零新增。
> 行号锚点基于 2026-08-30 代码（quality-gate 完成态），实现时以函数名为准。

## P0

- [x] **T1 config.py：滚动注入配置**
  改动：Settings 增 `style_recent_n: int = 3`（env `NOVEL_STYLE_RECENT_N`，0 = 禁用）与
  `style_slice_chars: int = 1000`（env `NOVEL_STYLE_SLICE_CHARS`，0 = 不截断）；env 解析接线。
  验证：test_config.py 新增--两变量默认值、setenv 覆盖、0 值合法解析。
  B1/B3/B18。

- [x] **T2 prompts.py：load_recent_human 纯函数**
  改动：新增 `load_recent_human(dir_path, n=3, slice_char=1000, progress=print) -> str`
  （design §3.1 伪代码全量落地：目录不存在 / n<=0 / 无 .txt/.md -> ""；`sorted()[-n:]` 取尾部；
  逐文件截前 slice_chars 并 progress 留痕；不可读文件跳过不阻断）。`__all__` 增名。
  验证：test_prompts.py 新增五态--尾部 N 选取（4 文件取 3 取最后 3 个）、每章截断（超长文件只保留前 N 字）、
  n=0 与目录不存在均返回 ""、空目录返回 ""、混合 .txt/.md 过滤。B2/B3/B4。

- [x] **T3 prompts.py + agent.py + cli.py：滚动注入接线（writer 专属）**
  改动：`writer_system`（`prompts.py:223`）增第 6 参 `recent_human: str = ""`，模板在【风格范例】后追加
  【近期人工正文】分节（标题含「学笔性与节奏，不是情节指令」防混淆文案，空串整块不占位）；
  `NovelAgent.__init__`（`agent.py:232`）增 `recent_human: str = ""` 属性，`_writer`（`agent.py:333`）
  传参（polisher/reviewer 零改动，B5）；`cli._build_agent`（`cli.py:130`）在 exemplar 加载后调
  `load_recent_human(settings.human_text_full, settings.style_recent_n, settings.style_slice_chars)`
  （仅当 `human_text_subpath` 已配置）；`_do_status` 增「滚动注入」一行（Z7 哲学：目录空 ->
  「人工语料为空，本次不注入」）。
  验证：test_prompts.py--writer_system 含分节标题与防混淆文案、空串不占位；test_cli_write.py--
  monkeypatch 后 `_build_agent` 注入滚动语料（tmp 目录建 3 章断言 writer prompt 含其内容）；
  `_do_status` 输出滚动注入行（配置/未配置两态）。B1/B5/B6/B8/B18。

- [x] **T4 prompts.py：de-AI prompt 构造函数**
  改动：新增 `deai_system(novel_name, rules="")`（人味重写师：铁律=情节/人称/称呼/伏笔/段落结构
  语义不动只改表达；风格指令四条=短句为主/克制留白/不解释因果/具体物象优先去副词堆叠；输出协议复用
  【第N段·修复后】标记，D11 同协议）与 `deai_user(spans_data)`（与 `fixer_user` 同构，
  文案改「人味重写」）。不注入 exemplar（D3）。
  验证：test_prompts.py--deai_system 含风格指令关键词与标记协议说明；deai_user 结构同 fixer_user
  （多段 + before/after + issues）。B10/B11。

- [x] **T5 agent.py + state.py：_fix_spans 抽共用 + deai_refine**
  改动：`state.py` 增 `deai: Dict[str, Any] = field(default_factory=dict)`（B14 留痕，asdict 自动
  落盘）；`agent.py` 把 `_fixer`（`agent.py:534`）的「定位 -> spans 合并 -> 单次调用 -> 标记协议解析
  -> 逐段回填 + 字数保护」抽为 `_fix_spans(text, issues, system, user_builder) -> tuple[str, int]`
  共用子过程（D2）；`_fixer` 改调它并保留整文降级分支（既有行为零改动，A8-A15 用例是回归护栏）；
  新增 `deai_refine(text, issues) -> tuple[str, int]`：预先过滤不可定位 issue（quote 空或非子串，
  D8 丢弃不整文降级）、走 `deai_system`/`deai_user`、`writer_llm` + max_tokens=4096 + temperature=0.5
  （Z3 同 fixer 档）；issues 为空返回 (text, 0) 零 LLM 调用。
  验证：test_agent.py 新增--deai_refine 区间外逐字节不变（B12）、未返回段回落原文、字数保护触发保留
  原段、空 issues 零调用、FakeLLM 按标记协议返回时改写段正确替换；**既有 fixer 全部用例零改动保持绿**
  （抽取回归护栏）。B10/B12/B17。

- [x] **T6 cli.py：_do_write 的 de-AI 判定链（D4 时序）**
  改动：`_do_write` 流水线 done 之后、save_run 之前插入（design §3.2 伪代码全量落地）：
  `deai_cfg = (rules or {}).get("deai") or {}`；enabled 且 final_chapter 非空 -> `load_baseline` +
  `ai_flavor_score` 算 before -> 超阈值（默认 60）-> `run_checks` 过滤可定位 issue（非空才进）->
  `agent.deai_refine` -> 复检 after -> `after < before` 才替换 `state.final_chapter`（D5 严格小于），
  `state.deai` 留痕 {before, after, spans, accepted} / {before, skipped}（B14）；未超阈值零留痕零调用；
  pass 异常 catch 打印保留原稿继续（优化器失败不阻断主流程）；save_run 与 evaluate 顺序不动
  （评委评的就是 de-AI 后终稿，D4）。
  验证：test_cli_write.py 新增五路--超阈值+分降（final_chapter 为改后稿 + state.deai.accepted=True
  + record 落盘含 deai 键）、超阈值+分不降（回退原稿 + accepted=False）、未超阈值（deai_refine 零调用、
  record 无 deai 键）、规则无 deai 键（零行为，与 quality-gate 完成态一致）、超阈值但无可定位句
  （skipped 留痕零 LLM）。测试缝：monkeypatch `cli.ai_flavor_score`/`cli.run_checks`/`cli.load_baseline`
  + FakeAgent.deai_refine（design §6 坑位）。B9/B13/B14/B17/B18。

- [x] **T7 cli.py：`去AI <文件路径>` 手动命令**
  改动：`_do_deai(args, settings)`（D7/D8：读文件 -> run_checks 可定位 issue 为空则提示退出 ->
  `_build_agent` -> `agent.deai_refine` -> 前后 ai_flavor_score 对比展示（分不降也如实展示，人不被
  阈值绑架，Z3）-> `_deai_confirm`（y/n，cli 模块级缝，EOF 保守 n）-> 存回 + rag.add_document 更新
  索引（同 refine 尾处理）；不落 run record（D8）；REPL 注册 + `_print_help` 增行；`_build_agent`
  的 RuntimeError 捕获同既有命令（A23 模式）。
  验证：test_cli_write.py 新增--confirm y 存回且索引更新、confirm n 原文件不动、无可定位句提示退出、
  文件不存在报错。B15。

- [x] **T8 harness.py：run_tests 的 deai 留痕断言**
  改动：`run_tests` 增一条：`final_state.deai` 存在且 `accepted` 为真时断言 `after < before`
  （留痕自洽性，B16 机械代理；其余情节保真由既有称呼红线/意图断言作用于 de-AI 后稿天然覆盖，
  design §3.6）；旧记录无 deai 键跳过（B20）。
  验证：test_harness.py 新增--含合法 deai 键的 record 断言通过、伪造 after >= before 的 record 断言
  FAIL、无键 record 不受影响。B16/B20。

- [x] **T9 `.env copy.example` + ROADMAP：配置注释与状态**
  改动：追加「文风闭环（1.5/1.6）」注释段--`NOVEL_STYLE_RECENT_N`（默认 3，0=禁用）、
  `NOVEL_STYLE_SLICE_CHARS`（默认 1000）、`质量规则.json` 的 `deai` 键（enabled/threshold，无键=
  不启用）；ROADMAP 阶段 1 状态行更新。
  验证：人工核对注释与 design §2 配置表逐行一致。B1/B9（可发现性）。

## P1（依赖真实运行数据，非阻塞）

- [ ] **T10 参数与阈值校准**：真实写作取数后校准 `style_recent_n`（3 是否够捕捉漂移）、
  `style_slice_chars`（1000 字是否见笔性）、`deai.threshold`（60 的拦截面与误伤，复用
  `回测门禁` 的分布输出）；与 quality-gate T12 同批做。
- [ ] **T11 deai_user 意见增强**（视实跑效果）：当前意见为 checker 机械 issue 文本；若重写质量不足，
  再议注入少量人工正文片段做参照（D3 重新评估，需 token 数据说话）。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| B1-B4 滚动注入机制（含降级/确定性/预算） | T1、T2、T3 |
| B5-B6 注入范围与可发现性 | T3 |
| B7-B8 不进 RAG / 分节防混淆 | T2、T3 |
| B9-B11 触发/输入/铁律 | T4、T5、T6 |
| B12-B13 回填与分降接受 | T5、T6 |
| B14 留痕 | T5、T6 |
| B15 手动命令 | T7 |
| B16 情节保真断言 | T5、T8 |
| B17 防空跑 | T5、T6 |
| B18-B20 兼容 | T1、T3、T6、T8 |
| 配置可发现性 | T9 |
