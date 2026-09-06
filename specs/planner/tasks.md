# 阶段 3.3：章节规划师（planner）- 任务分解

> 对应需求：`requirements.md`（P1-P12）；详细设计：`design.md`（D1-D8/Z1-Z4）。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` = **555 passed / 0 failed /
> 1 deselected**（2026-09-05 实测，537 基线 + 18 条新增全绿），零新增失败、
> 零既有用例修改（Z3 文案适配除外）。
> 行号锚点基于 2026-09-05 代码（volume-align 完成态），实现时以函数名为准。

## P0

- [x] **T1 config.py：NOVEL_PLANNER / NOVEL_PLANNER_TEMPERATURE**
  改动：Settings 增 `planner_enabled: bool = False`（env `NOVEL_PLANNER`，
  `!=0` 开，D4 opt-in）与 `planner_temperature: Optional[float] = None`
  （env `NOVEL_PLANNER_TEMPERATURE`，float 解析走 `_env_float`）；
  `get_settings` 接线（int/float 解析对齐既有先例）。
  验证：test_config.py 新增--默认 False/None、`=1` True、`=0` False、
  温度覆盖。P10。

- [x] **T2 prompts.py：PLANNER_SYSTEM + planner_system + planner_user**
  改动：新增 `planner_system(novel_name, retrieved, instruction, rules)`
  （复用 `_rules_block`/`_instruction_block`；不含 exemplar/recent_human，
  节拍不学文风）与 `planner_user(task, plan, target_words)`（任务 + 章纲
  如有 + 四要素清单：场景序列含字数/伏笔操作收旧埋新/弧光推进/结尾钩子 +
  「只输出节拍表，不要写正文」）。
  验证：test_agent.py 断言 prompt 含章纲/字数/四要素文案。P5。

- [x] **T3 agent.py：_planner 角色 + writer 分支 + 文案中性化**
  改动：
  - agents map 增 `"planner"`；`run()` 起点 `next_agent = "planner"`（开关
    开时）；`_temp` 写作侧 tuple 增 `"planner"`；
  - `_planner`（design §3.1）：`_retrieve` + `planner_system` +
    `_working_context` + `planner_user`，chat 包 try/except（Z4），空回/
    异常降级 log 警告，成功填 `state.outline`；
  - `_writer` 分支（design §3.2）：`plan_block` 条件收窄
    （`state.plan and not state.outline`）；outline 已填时注入节拍块 +
    「直接写正文」指令（含 rewrite 分支同款适配）；outline 不被 writer
    覆盖（P8）；
  - polisher/reviewer 的 outline_hint 文案中性化（Z3）；
  - state.py：`outline` 字段注释更新为「planner 节拍（planner 开且成功）
    或 writer 构思（其余情况）」（design §3.2）。
  验证：test_agent.py 新增约 12 条（design §6 清单）。P1-P3/P6-P8。

- [x] **T4 cli.py：预算文案动态 + 状态命令开关行**
  改动：`_do_write_batch` 预算文案按 `planner_enabled` 二选一（8-11 /
  9-12，Z2）；`_do_status` 增 planner 开关行（P12）。
  验证：test_cli_write.py 断言两态文案与状态行。P11/P12。

- [x] **T5 测试三处收口**
  改动：test_agent.py / test_config.py / test_cli_write.py 按 design §6
  清单补全（含 planner off 现状零变化对照例）。
  验证：新增全绿；grep 既有断言无「writer 构思」字样依赖（有则同步更新，
  Z3）。

- [x] **T6 `.env copy.example`：planner 注释段**
  改动：追加「章节规划师（planner）」段--开关、行为（先规划再写/节拍进
  run record/reviewer 验收基准/构思前移）、降级说明（空回落 writer 自行
  构思）、与章纲关系（章纲是原料、节拍是成品）、token 成本提示（每章
  +1 次大输入调用）。
  验证：人工核对与 design §3.5 一致。

- [x] **T7 全量回归**
  验证：`python -m pytest tests/ -q` = **555 passed / 0 failed / 1 deselected**
  （2026-09-05 用户终端实测，537 基线 + 18 条新增全绿），零新增失败。
  附带修复：cli.py readline 顶部 import 在无 tty 环境阻塞 -> 懒加载进 main()
  （sandbox/CI 可安全 import cli；pytest 在 sandbox 仍卡属框架 tty 探测，非代码问题）。

## T8 rewrite 路径接 planner（本轮，2026-09-05 真车证实价值后从 P1 提前）

> spec 更新：requirements §3.4（P13-P16）、design §3.6（D9-D11）。
> 真车证据：重写第40章（无节拍）打回两轮整文修复；写第41章（有节拍）
> 一次过审。

- [ ] **T8.1 prompts.py：planner_user 增可选参数 source_content**
  改动：签名 `planner_user(task, plan, target_words, source_content="")`；
  非空时注入【原文（重写参考）】块 + 重写模式指令（基于原文结构：提取
  场景序列 → 逐场景标注处理方式（保留/重排/合并/增强/删除）→ 保留核心
  意图与既有伏笔，不从零规划）；为空时输出与现状逐字节一致（P16）。
  验证：test_agent.py 断言两态输出（含/不含原文块与重写指令）。P14。

- [x] **T8.2 agent.py：rewrite() 起点分支 + _planner 透传**
  改动：`rewrite()` 内 `if self.settings.planner_enabled:
  state.next_agent = "planner"`（否则现状 writer）；`_planner` 的
  planner_user 调用增传 `state.source_content`；rewrite() docstring 同步。
  writer 侧零改动（D11：P7 统一条件天然覆盖 rewrite 分支）。
  验证：test_agent.py 新增约 5 条（design §6 T8 清单）。P13/P15/P16。

- [x] **T8.3 全量回归**
  验证：`python -m pytest tests/ -q` = **566 passed / 0 failed / 1 deselected**
  （2026-09-05 用户终端实测，555 基线 + 11 条新增：6 条 T8 + 5 条 llm.py
  截断翻倍修复），零新增失败。

## P1（依赖真实运行数据，非阻塞）

- [ ] **T9 节拍结构化 schema**：harness 断言「正文节拍覆盖率」需求出现时，
  再议 JSON schema（D3 备选复活）。
- [ ] **T10 planner 价值 A/B 校准**：真车用 `compare` 对同任务跑
  planner on/off 各一次，验证节拍假设（质量提升 > token 成本）后再议
  默认开（D4）。on/off 区分从 steps 有无 planner 步骤推断；若 compare
  不便，可在 `_record` config 补 `planner_enabled` 字段（foreshadow/arc
  亦不在 config，补则三者一起补）。同时关注节拍对章纲的覆盖率
  （design §4 已知局限）。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| P1/P6 规划回路与留痕 | T3 |
| P2/P7/P8 构思前移与消费 | T3 |
| P3 降级 | T3（Z4 try/except） |
| P4 开关关零变化 | T1、T3、T5 |
| P5 输入汇合 | T2、T3 |
| P9 范围外 | T3（refine_agents 不含 planner） |
| P10 配置 | T1 |
| P11 批量与预算 | T4 |
| P12 兼容与可发现性 | T4、T6 |
| P13-P16 rewrite 接 planner | T8.1、T8.2 |
| 回归基线 | 每任务完成即跑相关测试，T7/T8.3 全量（537 基线零新增） |
