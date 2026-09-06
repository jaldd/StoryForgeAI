# 阶段 3.1：伏笔自动追踪（foreshadow）- 任务分解

> 对应需求：`requirements.md`（F1-F17）；详细设计：`design.md`（D1-D10/Z1-Z8）。
> 任务编号用 T 系列（对齐 quality-gate/style-loop 的 tasks 惯例；跨 feature 引用
> 一律带目录前缀，如 `foreshadow/T4` vs `throughput/W4`，评审 C4 修正）。
> 开工前状态：throughput W1-W7 已实现并提交（611fa4c）；真车冒烟由用户执行中，不阻塞。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` = **461 passed / 0 failed /
> 1 deselected**（2026-08-31 实测），零新增失败。
> **基线变更声明**：本 feature 修改 **2 处**既有用例（实现已同步修改，显式记录）：
> 1. `test_storage.py::test_working_memory_roundtrip` 的
>    `unresolved_foreshadowing == ["伏笔A"]` 断言（str -> dict 条目，评审 C3）；
> 2. `test_cli_write.py::test_batch_plan_driven_titles_plans_continuity` 的预算提示
>    文案断言（F13：6-9 -> 7-10 次）。
> 除此之外既有 459 条用例零改动。
> 修订（2026-08-31，评审二轮）：F16 两道守卫（num=None 不清洗 / manual 跳过）、
> 失败留痕 error 键、`伏笔 删` 统一归档路径。
> 行号锚点基于 2026-08-31 代码（throughput 完成态），实现时以函数名为准。
> **实现完成（2026-09-01）**：T1-T6 全绿，`cli/` 下 `python -m pytest tests/ -q`
> = **492 passed / 0 failed / 1 deselected**（原 461 基线 + 新增 31 条，
> 含 2 处既有用例的显式修改）。T7/T8 留在 P1 等真车数据。

## P0

- [x] **T1 config.py + memory.py：开关/温度/护栏配置 + 条目结构升级**
  改动：Settings 增 `foreshadow_enabled: bool = True`（env `NOVEL_FORESHADOW`，
  0 = 关）、`foreshadow_temperature: Optional[float] = None`（env
  `NOVEL_FORESHADOW_TEMPERATURE`）、`foreshadow_cap: int = 30`（env
  `NOVEL_FORESHADOW_CAP`，0 = 不截断）；`get_settings` 接线（int/float 解析对齐
  既有温度键先例）。memory.py：`unresolved_foreshadowing` 条目升级
  `{"desc": str, "chapter": Optional[int]}`（`伏笔 加` 补录条目另带
  `"manual": True`，F16 覆盖清洗跳过）；新增 `resolved_foreshadowing:
  List[dict]` 归档字段（`{"desc", "chapter", "resolved_chapter"}`，D8；人工
  `伏笔 删` 同入此归档）；
  `update_after_write` 的 `new_foreshadowing` 收 `List[dict]`（str 元素转 dict
  容错）；新增 `resolve_foreshadowing(indices, chapter_no)`（1 起编号、越界忽略、
  出列入归档）；`snapshot(cap: Optional[int] = None)` 渲染升级（D10：编号+埋设章
  +指令文案+cap 截断标注+**原编号保留**；chapter=None 省略章号前缀；cap=None 全量）。
  验证：test_config.py 新增--三变量默认值、setenv 覆盖、`NOVEL_FORESHADOW=0`
  解析 False；test_storage.py 新增（memory 侧用例同居处，评审 C2）--str 兼容/
  dict 原样/脏元素丢弃、resolve 正常/越界/重复编号、归档 roundtrip、snapshot
  新格式与截断（>cap 标注/原编号保留/cap=0 不截断/None 全量）；**修改既有
  `test_working_memory_roundtrip` 的伏笔断言为 dict 条目（基线变更声明）**。
  F6/F8/F11/F12。

- [x] **T2 storage.py：working_memory.json 序列化升级 + 兼容读取**
  改动：`save_working_memory` 序列化增 `resolved_foreshadowing` 字段（unresolved
  dict 条目直写无适配）；`load_working_memory` 兼容三态（str 元素 ->
  `{"desc": s, "chapter": None}`、dict 有 desc -> 原样收、其余丢弃），
  `resolved_foreshadowing` 缺省 `[]`。
  验证：test_storage.py 新增--旧格式 json（纯 str 列表）加载成 dict 条目
  （chapter=None）、新格式 roundtrip（含归档字段）、混入脏元素不拒载、
  无 resolved 键的旧文件加载为空归档。F6/F14。

- [x] **T3 prompts.py + agent.py：抽取 prompt + extract_foreshadowing**
  改动：prompts.py 新增 `FORESHADOW_SYSTEM`（伏笔审计员：自包含描述要求、编号回报
  协议、清单已有不重复报、**单章新增 ≤5 条（软约束，返回超限全收不截断，F5）**、
  空清单也返回全 new；不硬编码书名）与
  `foreshadow_user(chapter_text, unresolved_lines)`（正文 + 带编号清单）；agent.py
  新增 `extract_foreshadowing(chapter_text, unresolved, chapter_no=None) -> dict`
  （design §3.1：单次调用、**max_tokens=2048**（Z6）、JSON 解析剥围栏/杂文字容错、
  非法整体抛异常、resolved 越界/重复编号静默丢弃、new 同串机械去重、返回含 raw）；
  `_temp` 增 `foreshadow` kind（默认 0.2，不吃写作侧兜底温度，Z2）；
  `agent._working_context` 调 `snapshot(cap=self.settings.foreshadow_cap)`（D10
  接线，注入面三角色一致）。
  验证：test_prompts.py 新增--system 含协议/自包含要求/≤5 条上限文案、user 清单
  带编号；test_agent.py 新增--正常 JSON/围栏包裹/带杂文字/非法抛异常、越界编号
  丢弃、同串去重、空清单全 new、温度链 override、max_tokens=2048、
  `_working_context` 截断传参（cap=2 时快照只含尾部 2 条且原编号）。F1/F3/F5/D1/D2/D8。

- [x] **T4 cli.py：触发点接线 + 留痕落盘 + 预算口径**
  改动：`_write_one` 存盘分支内（摘要之后）按 design §3.3 修正版伪代码接线--
  **`wm.update_after_write` 保持无条件在 try 外（A2）**；try 内
  `resolve_foreshadowing` -> 同章覆盖式清追（F16，**两道守卫：`num is None`
  不清洗、manual 条目跳过**）-> record 顶层 `foreshadow` 键
  -> **补一次 `save_run(record, settings)`（A1，同 run_id 覆盖）** -> 🧵 打印；
  `settings.foreshadow_enabled` 为假整段跳过；异常打印跳过不阻断不更新，且
  **except 分支写 `record["foreshadow"] = {"error": str(e)}` + best-effort 补写
  save_run（F4 二轮：replay 分得清「没埋伏笔」与「抽取挂了」）**；
  `save_working_memory` 保持 try 外无条件。批量预算提示文案 6-9 -> **7-10 次**（F13）。
  验证：test_cli_write.py 新增--monkeypatch extract 断言 wm 增删/归档/record 留痕
  **且落盘后 load_run 读得到（A1）**/🧵 行；抛异常 -> 伏笔列表不变、**进度指针与
  摘要照常更新且落盘（A2）**、**record 落 error 键（F4 二轮）**、写作流程走完
  存盘；`NOVEL_FORESHADOW=0` 零调用；同章重写覆盖（第二次 `写第5章` 后同章旧条目
  被替换，**manual 条目保留**）；**`num=None` 任务（「写一段番外」）不清无章号
  条目**；批量两章场景第二章抽取输入含第一章新增伏笔（**走落盘-重读链断言，
  C1：monkeypatch 每次新建的 agent**）；预算提示 7-10 文案。F2/F4/F13/F16。

- [x] **T5 cli.py：`伏笔` 命令四形态 + 状态/命令边界 + help**
  改动：主循环增 `伏笔` 分支（design §3.5 表：列表/删（**出列入归档，与模型回收
  同一 resolve 路径**，先算索引集再一次删）/加（chapter 取 wm.current_chapter，
  **打 manual 标记**）/已回收）；命令入口先
  `settings.require_novel_dir()`（F9）；`_do_status` 增补--current_chapter 为空但
  unresolved 非空时也打印伏笔块（F17，**只在 None 分支补，别无条件
  print(snapshot())**）；`_print_help` 增一行。
  验证：test_cli_write.py 新增--四形态（列表空/非空、**删=入归档而非物理删除
  （F15 二轮）**、删单编号/多编号一次给全不错位、加落盘 roundtrip 且带 manual
  标记、已回收列表）、require_novel_dir 校验（未配置报错不崩）、help 增行、
  _do_status 首章前伏笔可见且无「第None章」噪音。F9/F10/F15/F17/D6/Z4。

- [x] **T6 `.env copy.example` + 早期规划：配置注释与状态更新**
  改动：追加「伏笔追踪（3.1）」注释段--`NOVEL_FORESHADOW`（默认 1，0=关回路，
  含「人工补录/展示保留」说明）、`NOVEL_FORESHADOW_TEMPERATURE`、
  `NOVEL_FORESHADOW_CAP`、`伏笔` 命令用法一句（含 `删/加/已回收`）；早期规划：
  阶段 3 状态行更新（3.1 实现完成待真车验收）、开放问题 4 标记关闭（本 feature
  即其答案）、3.1 正文「见开放问题 5」笔误改 4（评审 D 组顺手修）。
  验证：人工核对注释与 design §2 配置表逐行一致。F11/F12。

## P1（依赖真实运行数据，非阻塞）

- [ ] **T7 抽取质量校准**：真车取数后校准 prompt（自包含描述的粒度、回收判定的
  宽严、≤5 条上限是否合理）、cap 截断阈值、误报/漏报的人工修正频率
  （`伏笔 删`/`伏笔 加` 使用率）。
- [ ] **T8 回收确认门 + 归档移回自动化**：LLM 判回收直接出列若误伤率高，升级
  「回收待确认」中间态；`伏笔 已回收` 的归档条目一键移回 unresolved--两件事都
  需真车误伤数据说话才立项。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| F1/F3/F5 抽取回路与 fail-safe | T3、T4 |
| F2 结构更新与批量连续性（落盘-重读链） | T1、T2、T4 |
| F4 留痕落盘 replay 可查（含补写 save_run） | T4 |
| F6 旧数据兼容 | T1、T2 |
| F7/F8 注入格式与护栏（cap 参数化 + 原编号） | T1、T3 |
| F9/F10/F15/F17 人工修正缝与命令边界 | T5 |
| F11 温度/max_tokens 配置 | T1、T3 |
| F12 一键降级（只关回路） | T1、T4 |
| F13 预算口径 | T4 |
| F14 旧记录兼容 | T2 |
| F16 同章重写覆盖 | T4 |
| 回归基线 | 每任务完成即跑相关测试，T6 后全量（基线 461 passed，含 1 处既有断言显式修改，零新增失败） |
