# 事件锚门禁（event-anchor）- 任务分解

前置：design.md 已定稿（D1-D10 / Z1-Z3 拍板口径）。
约定：每个任务单文件单职责；全程测试不联网（tmp 目录 + FakeLLM + monkeypatch）。
全量回归命令（在 `cli/` 下）：`python -m pytest tests/ -q`。
基线：628 passed / 0 failed / 1 deselected（2026-09-19，真车修复后实测），验收口径为**保持全绿**。
测试分工（宪法 §8）：AI 只跑纯逻辑最小验证脚本（checker/prompts 层直接 import + assert，跑一次即收）；
全量回归由用户在 IDE 终端执行，贴回结果再继续。
实施顺序即依赖顺序：T1 -> T2 -> T3 -> T5。P1 任务（T4）观察 P0 效果后再启动。

## P0（实现主干）

- [ ] **T1 checker.py：run_structure_checks + _checker 接线**
  改动：追加 `run_structure_checks(text, rules) -> list[dict]`（design §3.1 三项：
  碎片章 min_chars（quote 置空）/ 零对话独白章（quote=首个有效行截50）/
  状态堆叠（quote=首个状态词所在句截50，`_first_sentence_with` 复用）；
  Z1 有效行口径：剔除 `#` 标题行与 `---`/`***` 分隔行；三项共用一次遍历；
  键缺失/词表空逐项跳过，rules 为 None 或 text 空 -> []）。
  `__all__` 增 `run_structure_checks`。
  agent.py `_checker`：structure issues 走 report-only 通道（design D9）——逐条打印 ⚠️ +
  `state.log` 留痕 + 直通 reviewer；不进 `state.issues`、不消耗 `review_count`、不触发 fixer。
  验证：test_checker.py 追加——三项各自命中 / 恰等于阈值不报 / 键缺省逐项跳过 /
  词表空跳过 / 标题行与分隔行不计入 / quote 子串断言（碎片章恒空）；
  test_agent.py 追加——structure issue 命中 -> 不进 fixer / `review_count` 不变 /
  next_agent=reviewer / `state.log` 含警告留痕 / 与既有检查命中混合时两路互不干扰 /
  quality_rules 为 None 时与现状逐字节一致（E12 回归护栏）/ refine 路径同样生效。E1-E6、E12。

- [ ] **T2 prompts.py + agent.py：reviewer 第 9 维与事件锚分流**
  改动：`reviewer_system` 审查维度追加第 9 条「事件锚」（design §3.3 文案；
  现状 8 维，**按现状续号追加，不插入中间**——插入会挤掉既有 7/8 条，
  problem 前缀「维度名：」约定会错位）；
  scores 示例 JSON 增 `"事件锚"` 键；issue problem 前缀约定「事件锚：」写进模板说明。
  schema 四键（pass/reason/scores/issues）不变（E14）。
  agent.py `_reviewer` 增事件锚分流（design D10）：仅事件锚不达标 -> 放行留痕定稿
  （feedback 标注建议人工重写）；混合不达标 -> 事件锚 issue 剔除出 fixer 批次仅留痕；
  复检仅余事件锚 -> 放行（防循环）。
  验证：test_prompts_exemplar.py 或 test_agent.py 追加——system 文本含第 9 维与 scores 键；
  `parse_review_full` 对含「事件锚」scores 的返回解析正常（1-5 整数收编，越界丢弃现状）；
  旧格式返回（八维 scores 无事件锚键）解析不受影响（D3 向后兼容）；
  分流三情形（仅事件锚放行 / 混合剔除 / 复检仅余事件锚防循环）。E7、E8、E14。

- [ ] **T3 checker.py + cli.py：状态章嫌疑榜**
  改动：checker.py 追加 `_state_suspicion(text, state_words) -> dict`（纯函数，Z1 同款
  有效行口径；score = 状态词命中/有效行 − 对话行/有效行×2）；
  `scan_style_report` 增 `report["state_chapters"]`（全量降序，D7）；
  state_words 缺省或空 -> None（D8 未配置分态）。`__all__` 不新增（内部函数）。
  cli.py `_do_style_scan`：第四节打印 Top 20（file/score/行数/对话行/状态词命中）；
  None -> 一行未配置提示；help 文案更新。
  验证：test_checker.py 追加——嫌疑分计算（构造已知状态词/对话比的 tmp 假章）/
  降序与字段完整 / 未配置 None / 配置后无文件 [] 分态 / 零 LLM（monkeypatch 断言无调用，
  E10）。E9-E11。

- [ ] **T5 rewrite 路径事件锚提示**（report-only 拍板后从 P1 提前：人工重写是结构章的正解通道）
  改动：`rewrite()` 的 writer user prompt 补一句「若原文缺少完整事件（碎片章/状态章），
  按规划补事件锚重写，不要只润色状态描写」（design D9 配套）。
  验证：rewrite 的 writer user 文本含该句；run 路径（非 rewrite）不含（不加噪音）。

## P1（观察后启动）

- [ ] **T4 planner 事件锚声明（非目标 3 解禁令）**
  前置：P0 上线后观察 reviewer 第 9 维拦截率；若状态章仍从 planner 源头产出
  （规划只有状态没有事件），则 planner_system 增「节拍第一条必须声明本章事件锚」。
  涉及 planner 回归测试，单独立项评估。
