# 阶段 1 前半：质量门禁（quality-gate）- 任务分解

前置：design.md 已评审通过（含 D1-D12 拍板结论与 Z1-Z10 补充决策的落实口径；2026-08-29 评审修订已同步：独白 quote 首行截断、比喻 quote 置空、任一不可定位即整文修复（D12）、门禁豁免路径（D8）、`_build_agent` 异常落点）。
约定：每个任务单文件单职责，完成后即跑「验证」栏；全程测试不联网（FakeLLM / FakeRag / monkeypatch）。
全量回归命令（在 `cli/` 下）：`python -m pytest tests/ -q`。
基线：test_strip_polisher_meta / test_runtime_dir_override / test_defaults 共 3 个存量失败，验收口径为**零新增失败**。
实施顺序即依赖顺序：T1 -> T2 -> T3 -> T4/T5 -> T6 -> T7 -> T8 -> T9 -> T10/T11。

## P0（实现主干）

- [x] **T1 config.py：Settings 新字段与 env 接线**
  改动：新增 `quality_rules_subpath`（默认 `质量规则.json`，env `NOVEL_QUALITY_RULES`，空 = 禁用）
  与 `human_text_subpath`（默认 `正文`，env `NOVEL_HUMAN_TEXT`，空 = 不用人工语料）两字段；
  路径解析复用 `rules_subpath` 的既有模式（novel_dir + subpath property）。
  验证：test_config.py 新增用例--默认值 / setenv 覆盖 / 空串语义；setenv 后
  `get_settings.cache_clear()`、finally 再 clear（0.8 纪律）。A23、A27。

- [x] **T2 checker.py：规则加载与五项机械检查（新模块，纯函数零 LLM）**
  改动：新建 `cli/novel_agent/checker.py`。`load_quality_rules(settings)`：未配置 / 文件不存在 ->
  None；存在但非法 JSON 或顶层非 dict -> RuntimeError（报错含路径）。`split_sentences`：按
  `。！？!?；;` 与换行切分，strip 后非空为一句。对话行判定：行内含任意引号对
  `「」『』“”‘’` 即对话行（Z9）。`run_checks(text, rules) -> list[dict]`：blacklist /
  naming_redlines.forbidden / sentence.max_len / monologue.max_lines / metaphor（markers
  句级命中率 > max_rate 或相邻命中对 > max_adjacent_pairs）五项，规则键缺失跳过对应项；
  issue 与 reviewer 同构 `{quote, problem, fix}`，quote 截断展示（前 50 字）防 token 爆；
  独白 quote=区间首行截前 50 字（前缀子串，保可定位）；比喻密度 quote 置空（密度是全文属性，
  fixer 按 D12 走整文修复），problem 含占比 / 总数 + 至多 3 句截断样例。
  验证：test_checker.py（新文件）--五项各自命中 / 未命中不误伤（A22）/ 未配置跳过；
  load_quality_rules 三态（缺文件 None / tmp 写非法 JSON 断言 RuntimeError / 正常返回 dict）；
  split_sentences 边界（空串、连续标点、无标点单句、引号内终止符）。A16-A24。

- [x] **T3 checker.py：AI 味量化**
  改动：`Baseline` frozen dataclass（total_chars / sent_mean / sent_std / freq）；
  `load_baseline(settings)`：exemplar 目录全量（复用 `prompts._exemplar_files`，**不受
  EXEMPLAR_MAX_CHARS 注入上限约束**，Z8）+ human_text 目录，语料不足返回 None；
  `ai_flavor_score(text, rules, baseline) -> {"score", "components", "degraded"}`：三组件按
  design §3.1.3 公式与锚点（A_bl=3.0 / A_s=2.0 / A_f=0.3，锚点可配）、`ai_score.weights`
  线性加权、缺失组件权重重归一（D6）、无基准降级（degraded=True，freq 不参与，句长用内置
  μ=35 / σ=15）。
  验证：test_checker.py 新增--确定性（同输入两次调用结果相等，A25）；区分度（构造 AI 味重稿
  vs 仿人写稿，前者分数显著更高）；降级路径（无基准语料时 degraded=True 且 freq 不参与）；
  blacklist 未配置时重归一仍出有效分；组件分夹在 0-100。A25-A27、A29。

- [x] **T4 state.py + agent.py：state 新字段与 parse_review_full**
  改动：state.py 增 `scores: Dict[str, int]` 与 `issues: List[dict]`（default_factory，A4）；
  agent.py 把四级 JSON 提取（`agent.py:57-82`）抽为模块级共享 `_extract_json(text)`；新增
  `ReviewResult` dataclass 与 `parse_review_full(text) -> Optional[ReviewResult]`（scores 只收
  1-5 整数，越界 / 非整数丢弃；issues 字符串项归一为 `{"quote": "", "problem": s, "fix": ""}`）；
  `parse_review` 签名与语义零改动，`__all__` 增新名。
  验证：test_agent.py 新增--parse_review_full 四态（新 schema 全字段 / 旧 schema 字符串
  issues 归一 / 不可解析返 None / scores 越界与非整数丢弃）；parse_review 既有用例零改动保持绿；
  test_state.py 增新字段默认空容器。A1、A2、A4、A5、A6。

- [x] **T5 prompts.py：reviewer schema 演进 + fixer prompt**
  改动：`reviewer_system`（`prompts.py:197-214`）按 design §3.2 重写：6 既有维原文保留 +
  比喻密度 / 视角越界两维 + 新 JSON schema（pass / reason / scores 八维 / issues 对象数组；
  不通过时一次性列全问题，通过时 issues 留空数组）。新增 `fixer_system(novel_name, rules)`
  （修稿师：只改问题处，情节 / 人称 / 伏笔 / 其余表达不动，不加说明标题）、`fixer_user(spans_data)`
  （多段 + 各自意见 + 上下文，合并单次调用）、`fixer_whole_user(text, issues)`（整文降级用）。
  验证：轻量断言 reviewer_system 文本含八维名与 scores / issues 键名（进
  test_prompts_exemplar.py 或 test_agent.py）；fixer prompt 为纯构造函数无状态；实质验证经
  T6 / T7 的 FakeLLM 脚本走通（新 schema 脚本 + 旧 schema 脚本各留一份，A6 兼容）。A1-A3、A11。

- [x] **T6 agent.py：_reviewer 富解析、_checker 与 _fixer（新代码先落，T7 再接线）**
  改动：`__init__` 增 `quality_rules: Optional[dict] = None`（注入模式同 rules 字符串；
  None = checker 直通）。`_reviewer` 改用 parse_review_full：scores / issues 存 state，打回时
  feedback = reason + 各 issue 的 problem 摘要（维度名自带指路，A3）。新增 `_checker(state)`：
  run_checks 为空或 review_count 达上限 -> 放行 reviewer + log 留痕（D7）；否则 review_count+1
  （与 reviewer 共享预算，A14）、state.issues、feedback 附规则名 + 次数摘要（Z2）、
  next_agent="fixer"。新增 `_fixer(state)`：`split_paragraphs` 按 quote 定位命中段（首个含
  quote 的块），排序去重合并 spans；**任一 issue 的 quote 为空或非原文子串 -> 整组直接走
  整文降级**（D12，不做混合协议）；全部问题段 + 各自意见 + `build_context_pair` 上下文合成
  **一次** writer_llm 调用（max_tokens=4096、temperature=0.5，Z3）；输出按
  `【第N段·修复后】` 标记协议解析（D11），未返回段回落原文；逐段字数保护（len(old)>=50 且
  new < 50% 保留原段）；`apply_replacements` 回填，区间外逐字节不变；清空 state.issues（Z5）；
  log 留痕，next_agent="checker"。`_record` config 增 `"quality_rules": bool`（Z6）。
  验证：test_agent.py 新增（方法级直调）--_checker 三态（无规则直通 / 命中打回且
  review_count+1 且 issues 入 state / 达上限放行留痕）；_fixer：FakeLLM 脚本按标记协议构造，
  断言仅问题段被改、区间外逐字节不变、issues 清空、next_agent=checker；多 issue 合并单次调用
  （FakeLLM 调用计数=1，A11）；quote 不可定位（空或非子串）走整文修复（断言 payload 含全文，
  D12）；修复缩水超
  50% 保留原稿 + log（A15）；reviewer 富解析后 state.scores / issues 正确落 state。A8-A15、A24。

- [x] **T7 agent.py：拓扑切换（checker / fixer 上线）**
  改动：agents_map 三处--`self.agents` 增 checker / fixer（五角色）、`refine_agents`（
  `agent.py:523`）改 polisher / checker / reviewer / fixer、`rewrite_agents` 同 self.agents；
  `_polisher` 尾 `next_agent` 改 `"checker"`（`agent.py:310`）；`_reviewer` 打回目标改 fixer；
  删除 `_reject_target` 与 refine 的 try/finally 复位（D9）；删除 `_writer` / `_polisher` 的
  feedback_hint 死分支（`agent.py:234-236`、`280-282`）；reviewer 逃生门 / max_rounds 兜底 /
  `_confirm_unparseable` 不动（对 fixer 循环同样生效）。
  验证：test_agent.py 更新--happy path 步数 3 -> 4（writer / polisher / checker / reviewer，
  行为变更非回归破坏）；checker 打回 -> fixer -> checker 复检 -> reviewer 序列；reviewer 打回
  进 fixer（FakeLLM 断言 writer 仅被调用一次，好稿不陪葬，A8）；review_count 共享预算：checker
  连续打回达 max_reviews 后放行至 reviewer；既有 `test_refine_reject_goes_to_polisher` 重写为
  refine 打回进 fixer 语义；`test_refine_skips_writer` 步数 2 -> 3（polisher / checker /
  reviewer）、`test_pipeline_max_reviews_cap` / `test_pipeline_max_reviews_forced_finalize_warns`
  的 FakeLLM 打回脚本序列随 checker 步数同步调整；record 的 steps 含 checker 步、final_state
  含 scores / issues、config 含 quality_rules 键。A4、A9、A13、A14、A16。

- [x] **T8 cli.py：门禁统一（evaluate 移存盘前 + 确认缝）**
  改动：`_build_agent` 调 `load_quality_rules(settings)` 注入（非法 JSON 在装配点 fail-fast
  显性化；4 个调用点 `cli.py:124/268/304/359` 均在 try 外，命令层捕获 RuntimeError 打印后
  return，不崩 REPL）；新增模块级 `_gate_confirm(prompt)`（input，EOF / KeyboardInterrupt 返 "n" 保守弃）
  与 `_gate_ok(score, rules)`：rules None 或 eval_gate.enabled falsy -> True；score None 或
  无任何配权维度 -> True（A33 测试缝）；标题评分从 weights 硬排除（A32）；加权分
  Σw·s / Σw >= threshold。豁免口径（D8）：state.feedback 含「强制定稿」或「人工确认」（沿用
  `cli.py:192` 既有字符串匹配）-> 跳过门禁判定直存，向量库 / 摘要 / evaluate 照常。`_do_write`
  （`cli.py:117-175`）重排：agent.run -> save_run（先落 run record，弃而不失数据）->
  evaluate（从存盘后移到存盘前，报告照打一次）-> 未豁免且 final_chapter 非空且 gate 不过时
  `_gate_confirm` 应答弃则不写章节文件 -> 通过（或豁免、或确认存）才 save_chapter + rag +
  摘要 / 工作记忆（顺序不变）。`_refine_postprocess`（`cli.py:178-252`）：evaluate 从尾部
  提前到分支判定前（每命令仍恰一次评委调用），仅 passed 自动存回分支过门禁（D8），尾部重复
  调用删除。`状态` 命令（`cli.py:537`）增「质量规则」「人工语料」两行（Z7）。
  验证：test_cli_write.py 更新--门禁三路（低分 + 确认弃 -> 章节文件未写但 run record 已落 /
  低分 + 确认存 -> 写入 / evaluate 返 None -> 跳过门禁照常存），monkeypatch `cli.evaluate`
  与 `cli._gate_confirm`；豁免路径（feedback 含「强制定稿」/「人工确认」）不弹确认直存且
  向量库照入；规则未配置时门禁全程不生效；refine passed 分支同构用例；既有把
  `cli.evaluate` monkeypatch 为 None 的存量用例天然回归 A33；_gate_ok 标题维硬排除单测；
  非法规则 JSON 走命令层捕获不崩 REPL。
  A29、A30-A34。

- [x] **T9 harness.py：评测 / 对比 / 自检扩展**
  改动：`evaluate`（`harness.py:112-157`）评分后追加 AI 味浓度行（`load_quality_rules` +
  `load_baseline` + `ai_flavor_score`，降级时附提示行），返回 dict 增 `"AI味浓度"` 键；
  `compare`（`harness.py:195-219`）增「AI味浓度」行（双方现算，旧记录无键不影响），
  含风 / 含许风两行改读规则文件（forbidden / intent_words，未配置跳过，Z1）；`run_tests`
  （`harness.py:160-192`）改读规则文件（forbidden -> 不出现断言、intent_words -> 出现断言、
  规则缺失只剩流程断言，A36），另增维度分断言：final_state.scores 八维齐全且各分 1-5 整数
  （旧记录无 scores 跳过）。
  验证：test_harness.py 更新--run_tests 两方向断言与规则缺失降级；evaluate 输出含 AI 味行
  （monkeypatch `checker.ai_flavor_score` 或 tmp 语料直算）；compare 新旧记录混排不崩、新记录
  展示 AI 味与规则行；run_tests 对含八维 scores 的新记录断言通过、旧记录跳过。A7、A28、A36、A37。

- [x] **T10 harness.py + cli.py：回测门禁（A35）**
  改动：harness 增 `backtest_gate(settings, out=print, limit=None)`：遍历 runs（limit 控条数、
  跳过无 final_chapter 的记录），对每条 final_chapter 跑 evaluate（LLM 评委，顺序执行），
  按 `eval_gate.weights` 算加权分，输出分数分布 + 候选阈值（3.0 / 3.5 / 4.0）拦截面 run_id
  清单（误伤无自动 ground truth，人工核对）；分数缓存 `.agent/gate_backtest.json` 按 run_id
  增量（Z10，命中不重烧）；cli 增 `回测门禁` 命令。
  验证：test_harness.py 新增--缓存命中时不重复调 evaluate（spy 计数）；无 final_chapter 记录
  跳过；命令冒烟（monkeypatch evaluate 返回固定分）。A35。

- [x] **T11 `.env copy.example`：配置注释段**
  改动：追加 `NOVEL_QUALITY_RULES` / `NOVEL_HUMAN_TEXT` 注释段：含义、默认值、「留空 = 禁用」、
  一句「无 质量规则.json = checker 与门禁不启用」、规则文件字段模板指针（指向 design §2）。
  验证：人工核对注释与 design §5 env 表逐行一致。A23（可发现性）。

## P1（依赖真实运行数据，非阻塞）

- [ ] **T12 锚点与阈值校准**：跑 `回测门禁`（联网、烧评委）取分布，据拦截面校准
  `ai_score.anchors`（A_bl / A_s / A_f）、句长降级基线（μ=35 / σ=15）与 checker
  `sentence.max_len=80`（现值保守，误伤优先级低于漏检）；改动后全量回归零新增失败。
- [ ] **T13 metaphor 双阈值清理**：实跑观察 `max_rate` 与 `max_adjacent_pairs` 是否冗余，
  留一删一（design 已知局限末条）。

## 验收对照表

| 验收项 | 承载任务 |
|---|---|
| A1-A3 审核维度化（scores / 结构化 issues / 维度指路） | T4、T5、T6 |
| A4 维度分落 state 与 run record | T4（字段）、T6（写入）、T7（落盘断言） |
| A5-A6 parse_review 兼容与旧 schema 归一 | T4 |
| A7 run_tests 断言八维分 | T9 |
| A8-A9 打回统一进 fixer | T6、T7 |
| A10-A12 段落定位 / 合并单次 / 整文降级 | T6 |
| A13 修复后复检闭环 | T7 |
| A14 共享 review_count 预算 | T6、T7 |
| A15 字数保护 | T6 |
| A16-A22 checker 五项检查与不误伤 | T2、T7 |
| A23 规则缺失跳过 / 非法 fail-fast | T2、T8、T11 |
| A24 issue 同构入 state | T2、T6 |
| A25-A27 AI 味量化与降级 | T3 |
| A28 eval / compare 展示 | T9 |
| A29 AI 味默认不进门禁 | T3（只度量）、T8（_gate_ok 不含 AI 味） |
| A30-A34 门禁统一 | T8 |
| A35 回测 | T10（+P1 T12 校准） |
| A36 run_tests 规则化 | T9 |
| A37 旧记录兼容 | T4、T7、T9 |

## 人工验收（对齐 ROADMAP 1.1-1.4 验收口径）

1. NOVEL_DIR 放 `质量规则.json`（抄 design §2 模板改词表），跑「写一章」：run record 的
   steps 出现 checker 步；若产出命中黑名单词，日志可见 checker 打回 -> fixer 修复调用 ->
   checker 复检链路；
2. `eval_gate.threshold` 调高（如 4.8）跑一章：REPL 出现低分确认提示，「弃」时章节文件未写
   而 run record 已落，「存」时正常写盘，各验一次；
3. 跑 `评测`：输出含 AI 味浓度行与组件分（语料不足时见降级提示）；跑 `对比`：两记录 AI 味分
   并列展示；
4. 跑 `回测门禁`（联网、烧评委）：看各阈值拦截面与分布，据此执行 P1 T12 校准；
5. 移除 `质量规则.json` 复跑一章：checker 直通、门禁不启用，行为与改造前一致（回归保险）；
6. `cli/` 下 `python -m pytest tests/ -q` 零新增失败（3 存量失败除外）。
