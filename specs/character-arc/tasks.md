# 阶段 3.2：角色弧光追踪（character-arc）- 任务分解

> 对应需求：`requirements.md`（C1-C15）；详细设计：`design.md`（D1-D10/Z1-Z9）。
> 任务编号用 T 系列（对齐 foreshadow tasks 惯例；跨 feature 引用一律带目录前缀，
> 如 `character-arc/T4` vs `foreshadow/T4`）。
> 开工前状态：foreshadow T1-T6 已实现（492 passed 基线）；style-loop/throughput/
> foreshadow 真车验收由用户执行中，不阻塞。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` = **492 passed / 0 failed /
> 1 deselected**（2026-09-04 实测），零新增。
> **基线变更声明**：本 feature 修改 **1 处**既有用例（实现时同步修改，显式记录）：
> `test_cli_write.py::test_batch_plan_driven_titles_plans_continuity` 的预算提示
> 文案断言（C13：7-10 -> 8-11 次，foreshadow T4 已改过一次的同款）。
> 除此之外既有 492 条用例零改动。
> 行号锚点基于 2026-09-04 代码（foreshadow 完成态），实现时以函数名为准。
> **实现完成（2026-09-04）**：T1-T6 全绿，`cli/` 下 `python -m pytest tests/ -q`
> = **527 passed / 0 failed / 1 deselected**（原 492 基线 + 新增 35 条，
> 含 1 处既有用例的显式修改：预算提示 7-10 -> 8-11）。T7/T8 留在 P1 等真车数据。
> 实现备注：prompt 构造用例落在 `test_prompts_exemplar.py`（仓库无独立
> test_prompts.py，spec 测试策略一节的文件名以实际布局为准）。

## P0

- [x] **T1 config.py + memory.py：开关/温度/护栏配置 + 条目结构升级**
  改动：Settings 增 `arc_enabled: bool = True`（env `NOVEL_ARC`，0 = 关）、
  `arc_temperature: Optional[float] = None`（env `NOVEL_ARC_TEMPERATURE`）、
  `arc_cap: int = 8`（env `NOVEL_ARC_CAP`，0 = 不截断）；`get_settings` 接线
  （int/float 解析对齐既有 foreshadow 键先例）。memory.py：`character_states`
  条目结构化 `{"stage", "goal", "conflict", "belief", "chapter", "history"}`
  （history 只记变化点、章升序、cap 20 丢最老）；新增
  `update_character_states(entries, chapter_no)`（清单内覆盖/清单外新增/
  changed 追加 history/同章重写清 `chapter == chapter_no` 条目且 `chapter_no`
  为 None 不清洗，C15）、`remove_character(name)`、`revise_character_stage(name,
  stage, chapter=None)`；`snapshot(cap=None, arc_cap=None)` 渲染升级（C7/C8：
  分节文案「写作时保持各角色当前阶段与人设连续，不可无故突变」+ 每角色一行
  名字（更新章）：阶段｜目标｜信念 + 空不占位 + arc_cap 按更新章倒序截断 +
  总数标注 + chapter=None 省章号前缀；既有 cap 参数语义不动）。
  验证：test_config.py 新增--三变量默认值、setenv 覆盖、`NOVEL_ARC=0` 解析
  False；test_storage.py 新增--update（覆盖/新增/changed 追加/未 changed 不追加/
  history cap 20 丢最老/同章清洗/num=None 守卫）、remove/revise 命中与未命中、
  snapshot 新格式（分节文案/一行紧凑/空不占位/arc_cap 截断倒序+标注/cap=0
  不截断/None 前缀省略）。C6/C7/C8/C11/C12。

- [ ] **T2 storage.py：character_states 序列化容错**
  改动：`load_working_memory` 对 character_states 增脏容错（非 dict -> `{}`；
  条目非 dict 或缺 stage -> 丢弃，不因一条脏数据拒载整个文件）；序列化侧
  dict 直写无适配（字段已在既有落盘链路，C6 天然无迁移）。
  验证：test_storage.py 新增--新格式 roundtrip（含 history）、脏数据
  （character_states 为 list/条目缺 stage/条目为 str）加载不拒载且脏条目丢弃、
  旧文件（character_states 缺省或 `{}`）加载为空。C6/C14。

- [ ] **T3 prompts.py + agent.py：抽取 prompt + extract_character_arc**
  改动：prompts.py 新增 `ARC_SYSTEM`（角色弧光审计员：以本章正文结束时状态为准/
  清单已有角色必须用清单原名回报/新角色用正文正式全名/阶段描述自包含一句话/
  单章回报 ≤6 个主要角色软约束/changed = 阶段是否实质变化（措辞微调不算）/
  输出纯 JSON 协议；不硬编码书名）与 `arc_user(chapter_text, character_lines)`
  （正文 + 既有角色状态清单，每角色一行）。agent.py 新增
  `extract_character_arc(chapter_text, character_states, chapter_no=None) -> dict`
  （design §3.1：单次调用、max_tokens=2048、JSON 解析剥围栏/杂文字容错、非法
  整体抛异常、返回含 raw；名字同串覆盖/异串新键的机械判定在 memory 侧，agent
  只透传）；`_temp` 增 `arc` kind（默认 0.2，不吃写作侧兜底温度，Z2）；
  `agent._working_context` 调 `snapshot(cap=..., arc_cap=self.settings.arc_cap)`
  （C8 接线，注入面三角色一致）。
  验证：test_prompts.py 新增--system 含原名回报/≤6 软上限/changed 语义/自包含
  要求文案、user 清单每角色一行；test_agent.py 新增--正常 JSON/围栏包裹/带杂
  文字/非法抛异常、changed 字段透传、温度链 override、max_tokens=2048、
  `_working_context` 截断传参（arc_cap=2 时快照只含最近 2 个角色）。
  C1/C5/C7/C11。

- [ ] **T4 cli.py：触发点接线 + 留痕落盘 + 预算口径**
  改动：`_write_one` 存盘分支内、伏笔抽取块之后、`save_working_memory` 之前按
  design §3.3 伪代码接线--独立 try/except（弧光失败不影响伏笔已落的结果）；
  成功路径 `wm.update_character_states` -> record 顶层 `arc` 键
  `{updated, changed, total}` -> 补一次 `save_run(record, settings)`（同 run_id
  覆盖）-> 🎭 打印；失败路径 `record["arc"] = {"error": str(e)}` + best-effort
  补写（C4）；`settings.arc_enabled` 为假整段跳过（C12）；批量预算提示文案
  7-10 -> **8-11 次**（C13）。
  验证：test_cli_write.py 新增--monkeypatch extract 断言 wm 更新/record 留痕
  **且落盘后 load_run 读得到**/🎭 行；抛异常 -> 角色状态不变、**伏笔照常抽取
  且落盘**、进度指针与摘要照常更新且落盘、record 落 error 键、写作流程走完
  存盘；`NOVEL_ARC=0` 零调用；同章重写覆盖（第二次 `写第5章` 后 history 无
  同章重复条目）；`num=None` 任务（「写一段番外」）不清无章号 history；批量
  两章场景第二章抽取输入含第一章角色状态（**走落盘-重读链断言，monkeypatch
  每次新建的 agent**）；预算提示 8-11 文案（**基线变更声明处**）。
  C1-C4/C13/C15。

- [x] **T5 cli.py：`角色` 命令三形态 + help**
  改动：主循环增 `角色` 分支（design §3.5 表：列表（名字（更新章）：阶段｜目标｜
  冲突｜信念｜历史 N 条，空时提示）/删（直接移除不归档，Z4）/改（第一个空格分
  名字、其余整体作 stage，chapter 取 wm.current_chapter，D9 不打 manual））；
  命令入口先 `settings.require_novel_dir()`（C9）；`_print_help` 增一行。
  验证：test_cli_write.py 新增--三形态（列表空/非空、删命中移除/未命中提示、
  改命中落盘 roundtrip/未命中提示）、require_novel_dir 校验（未配置报错不崩）、
  help 增行。C9/C10。

- [ ] **T6 `.env copy.example` + 早期规划：配置注释与状态更新**
  改动：追加「角色弧光（3.2）」注释段--`NOVEL_ARC`（默认 1，0 = 关回路，含
  「人工修正/展示保留」说明）、`NOVEL_ARC_TEMPERATURE`、`NOVEL_ARC_CAP`、
  `角色` 命令用法一句（含 `删/改`）；早期规划：阶段 3 状态行更新（3.2 实现完成
  待真车验收）、3.2 正文补 spec 指向。
  验证：人工核对注释与 design §2 配置表逐行一致。C11/C12（可发现性）。

## P1（依赖真实运行数据，非阻塞）

- [ ] **T7 抽取质量校准**：真车取数后校准 prompt（stage 粒度、角色发现宽严、
  changed 判定的误报/漏报率、龙套入库率）、arc_cap 截断阈值、`角色 删`/`角色 改`
  使用率；与 foreshadow T7 同批做。
- [ ] **T8 `角色 详 <名字>` history 可视化**：列表只显当前状态，完整弧光曲线
  （history 全列）若真车有查看需求再做；`角色 改` 扩展改 goal/conflict/belief
  同理（当前只改 stage，最常用字段）。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| C1-C5 抽取回路与 fail-safe | T3、T4 |
| C6 结构与旧数据兼容 | T1、T2 |
| C7/C8 注入格式与护栏（arc_cap 参数化 + 更新章倒序） | T1、T3 |
| C9/C10 人工修正缝与命令边界 | T5 |
| C11 温度/max_tokens 配置 | T1、T3 |
| C12 一键降级（只关回路） | T1、T4 |
| C13 预算口径 | T4 |
| C14 旧记录兼容 | T2 |
| C15 同章重写覆盖（含 num=None 守卫） | T1、T4 |
| 回归基线 | 每任务完成即跑相关测试，T6 后全量（基线 492 passed，含 1 处既有断言显式修改，零新增失败） |
