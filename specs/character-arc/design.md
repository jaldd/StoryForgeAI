# 阶段 3.2：角色弧光追踪（character-arc）- 设计

> 对应需求：同目录 `requirements.md`（C1-C15）。
> 前置：`specs/foreshadow/`（T1-T6）已实现（492 passed 基线）--本 feature 结构上
> 对标其「写后旁挂回路 + REPL 修正缝」模式，触发点/留痕/降级纪律全部同款。
> 行号锚点基于 2026-09-04 代码（foreshadow 完成态），实现时以函数名为准。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| C1-C5/C15 抽取回路 | §3.1 extract_character_arc + §3.3 触发点 |
| C6/C8 结构与护栏 | §3.2 条目结构 + snapshot 截断 |
| C7 注入格式 | §3.2 snapshot 渲染 |
| C9/C10 人工修正缝 | §3.5 REPL 命令 |
| C11-C14 配置与兼容 | §2 配置面 + §3.4 降级 |

## 1. 总体设计

流水线拓扑零改动。本 feature 是**第二条写后旁挂回路**（挂在伏笔回路之后）加一条
REPL 命令：

```
_write_one（既有，不动结构）
  └─ 存盘后写后链：摘要 -> wm.update_after_write
       -> [伏笔抽取（既有）] -> [弧光抽取（本 feature）] -> save_working_memory
            ▼
     agent.extract_character_arc(定稿正文, 既有角色状态清单)
            │  一次 JSON 调用：
            │  {"characters": [{name, stage, goal, conflict, belief, changed}]}
            ▼ 成功                       ▼ 失败/不可解析
     覆盖状态 + 新角色入库         跳过不更新（C3），打印原因
     + changed 者追加 history      （进度/摘要/伏笔/落盘已在 try 外完成）
            │
     save_working_memory（既有同一次落盘）+ 补一次 save_run（record 留痕，C4）

writer/polisher/reviewer --working_context--> snapshot(arc_cap=settings.arc_cap)
REPL：角色 / 角色 删 <名字> / 角色 改 <名字> <新阶段>（人工修正缝）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `WorkingMemory.character_states`（memory.py，恒空 dict） | 字段已在，正好接住结构化条目 |
| `snapshot()` / working_context 注入链（agent.py `_working_context`） | 渲染格式升级 + arc_cap 参数，注入面不动 |
| `save_working_memory` / `load_working_memory`（storage.py） | character_states 已随 JSON 落盘/加载，仅补脏容错 |
| 伏笔抽取的触发点/try-except 纪律/record 补写（cli.py `_write_one`） | 同一点并列挂第二条回路，纪律同款 |
| `agent._temp(kind)` 温度链 | 新 kind `arc`，默认 0.2 |
| `extract_foreshadowing` 的 JSON 容错（剥围栏/杂文字） | 解析复用同思路 |
| record 顶层键留痕先例（`foreshadow`/`exemplar_route`） | 顶层 `arc` 键 + 抽取后补写 |

## 2. 配置面（新增 3 个 env，全部有零值降级）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_ARC` | 抽取回路开关 | `1` | int，`0` = 关回路（快照新格式/人工命令保留，C12） |
| `NOVEL_ARC_TEMPERATURE` | 抽取调用温度 | `0.2` | float，走 `_temp("arc", 0.2)` |
| `NOVEL_ARC_CAP` | prompt 注入护栏角色数 | `8` | int，`0` = 不截断；只影响注入不影响抽取 |

## 3. 详细设计

### 3.1 抽取调用（D1/D2/D5）

`agent.py` 新增方法（收编模式，同 `extract_foreshadowing` 先例）：

```python
def extract_character_arc(self, chapter_text: str,
                          character_states: Dict[str, dict],
                          chapter_no: Optional[int] = None) -> dict
```

- **单次调用三职（D1）**：prompt 给出本章正文 + 既有角色状态清单（每角色一行：
  `名字：阶段（目标｜信念）`），要求返回：

```json
{"characters": [
  {"name": "林晚", "stage": "复仇决心初动摇", "goal": "查清父亲死因",
   "conflict": "复仇与良知的拉扯", "belief": "真相值得任何代价", "changed": true}
]}
```

  备选「状态更新与变化判定拆两次调用」被否：输入高度重叠（都要正文 + 清单），
  一次调用 token 省一半且 changed 判定能看到完整状态上下文。
- **名字协议（D2）**：清单已有角色**必须用清单原名回报**（prompt 明令，防「林晚」/
  「晚晚」分裂成两键）；清单外新角色用正文中的正式全名。机械侧不做模糊匹配--
  返回 name 与既有键完全同串 -> 覆盖；不同串 -> 新角色（dict 键天然去重）。
  命名漂移残余风险靠人工 `角色 删` 清噪音（§4 已知局限）。
- **changed 语义判定（D7）**：阶段是否实质变化由 LLM 判（`changed: bool`），不做
  字符串比较--LLM 措辞每次都会漂（「决心动摇」vs「决心开始动摇」），字符串不等
  ≠ 阶段变化；反之阶段真变了但措辞巧合相同也该记。changed 是 history 追加的
  唯一依据。
- **快照语义**：prompt 明令「以本章正文结束时角色状态为准」--重写旧章时状态快照
  回退到该章时点（后续章不回溯重算，§4 已知局限，同伏笔哲学）。
- **输出预算（C5/C11）**：max_tokens=2048（宪法 §4；6 角色 × 4 字段 JSON 比伏笔
  描述长）；prompt 明令单章回报 ≤6 个主要角色（**软约束**：超限全收不截断--
  截断丢真主角，违背宁缺勿错；≤6 防的是输出截断与龙套灌水）。
- 返回 `{"characters": [...], "raw": 原始返回}`，raw 供留痕与调试。

### 3.2 条目结构与 snapshot 渲染（C6-C8）

`WorkingMemory` 侧（memory.py）：

- `character_states: Dict[str, dict]`，键 = 角色名，条目：

```python
{"stage": str, "goal": str, "conflict": str, "belief": str,
 "chapter": Optional[int],                      # 最近更新章号
 "history": [{"chapter": int, "stage": str}]}   # 阶段变化点，章升序
```

- 新增 `update_character_states(entries: List[dict], chapter_no)`：
  - 逐条按 name 覆盖/新增（`chapter` 记 chapter_no）；
  - `changed` 为真的条目追加 `{"chapter": chapter_no, "stage": 新 stage}` 进
    history（变化点 = 新阶段起点，history 尾条即当前阶段起点，全列 + 当前 =
    完整曲线）；
  - history 护栏 20 条，超出丢最老（固定常量不进配置，Z3）；
  - 同章重写覆盖（C15）：`chapter_no` 非 None 时先清各角色 history 中
    `chapter == chapter_no` 的条目再走上述逻辑（`num=None` 守卫：不清洗）。
- 新增 `remove_character(name) -> bool`（人工删，直接移除不归档，Z4）与
  `revise_character_stage(name, stage, chapter=None) -> bool`（人工改 stage，
  chapter 缺省取 current_chapter；**不打 manual 标记**，D9）。
- `snapshot(cap=None, arc_cap=None)` 渲染升级（cap 既有伏笔参数不动，arc_cap 新参）：

```
角色弧光（写作时保持各角色当前阶段与人设连续，不可无故突变）：
  林晚（第12章）：复仇决心初动摇｜目标：查清父亲死因｜信念：真相值得任何代价
  沈砚（第12章）：…
  …（共 12 角色，仅注入最近更新 8 个）
```

  - **截断按更新章倒序**（D10：最近活跃优先），标注总数；
  - 状态为空 -> 整块不占位（首章前天然安静）；
  - `chapter` 为 None：省略「（第N章）」前缀；
  - 调用方：`agent._working_context` 传 `arc_cap=self.settings.arc_cap`
    （三角色注入面一致）；`状态`/`角色` 命令传 None 看全量。
- `load_working_memory` 容错：character_states 非 dict -> 置 `{}`；条目非 dict 或
  缺 stage -> 丢弃（不因一条脏数据拒载整个文件）。旧文件该字段恒 `{}`，天然兼容。

### 3.3 触发点与留痕（C1-C4/C15）

`cli._write_one` 存盘分支内、伏笔抽取块之后、`save_working_memory` 之前：

```python
if settings.arc_enabled:                          # C12 开关
    try:
        ar = agent.extract_character_arc(
            state.final_chapter, wm.character_states, chapter_no=num)
        wm.update_character_states(ar["characters"], num)
        record["arc"] = {                         # C4 成功留痕
            "updated": [c["name"] for c in ar["characters"]],
            "changed": [c["name"] for c in ar["characters"] if c.get("changed")],
            "total": len(wm.character_states)}
        save_run(record, settings)                # 补写一次（同 run_id 覆盖）
        print(f"🎭 弧光：更新 {len(ar['characters'])} 角色"
              f"（跟踪 {len(wm.character_states)}）")
    except Exception as e:
        print(f"(弧光抽取跳过：{e})")              # C3：状态不更新，写作流程照常
        record["arc"] = {"error": str(e)}         # C4 失败留痕
        try:
            save_run(record, settings)
        except Exception:
            pass
save_working_memory(wm, settings)                 # 既有，无条件（try 外）
```

- **与伏笔回路的关系**：两条回路各自独立 try/except，一个失败不影响另一个；
  record 补写各补各的（同 run_id 覆盖幂等，伏笔先补一次、弧光再补一次，落盘
  路径不变）。
- **既有纪律继承**：进度指针/摘要/伏笔/落盘都在各自 try 外无条件执行；弧光抽取
  失败最坏损失 = 本章角色状态未记账，绝不丢进度/摘要/伏笔。
- **批量模式零适配**：同伏笔 C1 结论--`_build_agent` 每章重读盘，`save_working_memory`
  章末无条件落盘保证连续性；测试走落盘-重读链。
- **中断章不抽取**（同哲学）：`interrupted/failed/rejected` 结局不走存盘分支。

### 3.4 降级与兼容（C12/C14）

- `NOVEL_ARC=0`：`settings.arc_enabled` 为假 -> 触发点整段跳过；快照新格式与
  `角色` 命令保留（开关只关抽取回路，不关基础设施）。
- 旧 run record 无 `arc` 键：replay/compare 不读该键，天然兼容。
- 旧 working_memory.json 的 character_states 恒 `{}`：直接进新结构，无迁移。

### 3.5 REPL 命令（C9/C10）

| 命令 | 行为 |
|---|---|
| `角色` | 列出全部跟踪角色：名字（更新章）：阶段｜目标｜冲突｜信念｜历史 N 条；为空时提示暂无跟踪角色 |
| `角色 删 林晚` | 停止跟踪（直接移除；角色再出场会被抽取重新发现，状态从该章重新起算） |
| `角色 改 林晚 复仇决心已崩溃` | 修正当前阶段（chapter 取 wm.current_chapter，为空则 None），落盘 |

- 命令入口先 `settings.require_novel_dir()`（读盘需要，C9）；
- `角色 改` 的参数切分：第一个空格分名字、其余整体作 stage（stage 含空格是常态）；
- `_do_status` 无需增补：snapshot 升级后「角色状态」行自动受益；首章前
  character_states 恒空（无 `角色 加` 命令），不存在伏笔 F17 类的补丁需求；
- `_print_help` 增一行。

## 4. 已知局限与不动清单

**已知局限**（真车数据说话后再议，不在本 feature 修）：

- **重写/精修/去AI 路径不抽取**：同伏笔局限--`_do_rewrite`/`_do_refine`/`_do_deai`
  走 `_refine_postprocess`，无抽取通道；大幅改动后该章角色状态可能失真，人工经
  `角色 改` 修正。
- **重写旧章快照回退不回溯**：重写第 5 章后状态快照回到第 5 章时点，第 6-12 章
  的状态不回溯重算（回溯重算 token 爆炸）；后续章抽取会自然把状态拉回最新。
- **命名漂移**：LLM 回报名字与清单键不同串会分裂成两键（prompt 原名回报预防，
  残余靠人工 `角色 删` 清噪音）。
- **截断削弱 reviewer 判定依据**：reviewer 的「人物一致性」维度消费的也是
  working_context 快照，arc_cap 截断后它看到的是最近活跃子集。接受：cap 默认 8
  对绝大多数作品覆盖主要角色；cap=0 可关截断换 token 成本。
- **reviewer 无弧光维度**：不加「角色弧光」审查维度（Z9）--已有「人物一致性」
  维度覆盖静态人设；弧光的验收基准归 3.3 planner（拿节拍验收）再议。
- **changed 误报/漏报**：LLM 单次语义判定无确认门；误报多一条 history 噪音、
  漏报丢一个变化点，均不污染当前状态（当前状态每次全量覆盖），危害有界。

**不动清单**（防漂移）：

- 流水线状态机与角色拓扑（writer->polisher->checker->reviewer+fixer）。
- 伏笔回路的全部逻辑（本 feature 只在其后并列挂一条，零改动）。
- `update_after_write` 既有语义（current_chapter/last_plot_point/伏笔）。
- working_context 的注入范围（三角色同一份，不窄化不扩面，C7）。
- `save_chapter`/`parse_chapter_task`/RAG 入库链路。
- 批量编排 `_do_write_batch` 的结局判定与章间循环。
- `py/`、Java 侧。

## 5. 实现注意（坑位）

- **名字口径**：抽取 prompt 清单渲染的名字必须与 `wm.character_states` 键逐字一致；
  返回名同串覆盖、异串新键--三处（清单渲染/覆盖判定/`角色` 命令显示）同源。
- **changed 判定输入错位**：重写旧章时 LLM 看到「当前状态（可能来自第 12 章）+
  本章（第 5 章）正文」，prompt 明令「以本章正文结束时角色状态为准」，快照回退
  是有意语义（§3.1）。
- **截断只影响注入不影响抽取**：`extract_character_arc` 的输入清单必须全量
  （不活跃角色再出场时其旧状态是判定基准）。
- **JSON 解析容错**：剥围栏/杂文字同伏笔；剥完仍非法 -> 整体失败走 C3
  （宁缺勿错，不做部分采信）。
- **空清单首次抽取**：prompt 里「既有角色：无」也要能正确返回全 new
  （正文里所有主要角色）。
- **温度链**：`_temp("arc", 0.2)` 不属于写作侧 kind，不吃 `NOVEL_TEMPERATURE`
  兜底（与 reviewer/foreshadow 同类，只看自己的键和默认）。
- **record 补写时序**：伏笔已补写一次，弧光再补写一次（同 run_id 覆盖幂等）；
  打印的 run_file 路径不变。
- **批量测试口径**：同伏笔 C1--断言「第二章抽取输入含第一章状态」要走真实
  `load_working_memory` 落盘-重读链，不能假设 wm 同实例传递。

## 6. 测试策略（全程不联网）

- **test_storage.py（memory 侧既有用例同居处）**：条目结构 roundtrip（含 history）；
  脏容错（character_states 非 dict 置空/条目缺 stage 丢弃/不拒载）；
  `update_character_states`（清单内覆盖/清单外新增/changed 追加 history/未 changed
  不追加/history cap 20 丢最老/同章重写清 chapter==num 条目/num=None 不清洗）；
  `remove_character`/`revise_character_stage`（命中/未命中）；snapshot 新格式
  （分节文案/每角色一行/空不占位/arc_cap 截断按更新章倒序+总数标注/cap=0 不截断/
  chapter=None 无章号前缀）。
- **test_agent.py**：`extract_character_arc` 的 JSON 解析（正常/围栏包裹/带杂文字/
  非法 JSON 抛异常）、同名覆盖 vs 异名新键、changed 字段透传、温度链走
  `arc_temperature`、max_tokens=2048、prompt 含 ≤6 软上限与原名回报文案、
  `_working_context` 截断传参（arc_cap=2 时快照只含最近 2 个角色）。
- **test_cli_write.py**：触发点接线（monkeypatch extract 断言 wm 更新/record 留痕
  **且落盘后 load_run 读得到**/🎭 行）；失败路径（抛异常 -> 状态不变、**伏笔照常
  抽取且落盘**、进度指针与摘要照常、record 落 error 键、写作流程走完存盘）；
  `NOVEL_ARC=0` -> 零调用；同章重写覆盖（第二次 `写第5章` 后 history 无重复条目）；
  `num=None` 任务不清无章号 history；批量两章场景第二章抽取输入含第一章状态
  （走落盘-重读链）；预算提示 8-11 文案。
- **test_cli（角色命令，并入 test_cli_write.py）**：三形态（列表空/非空、删命中/
  未命中、改命中落盘 roundtrip/未命中提示）、require_novel_dir 校验、help 增行。
- **test_config.py**：三 env 默认值与覆盖、`NOVEL_ARC=0` 解析 False。
- **回归**：`cli/` 下 `python -m pytest tests/ -q`，**492 passed / 0 failed /
  1 deselected**（2026-09-04 实测基线）+ 新增约 30 条，零新增失败。
  **基线变更声明**：`test_batch_plan_driven_titles_plans_continuity` 的预算提示
  断言需 7-10 -> 8-11（C13，foreshadow T4 已改过一次的同款）。

## 7. 决策表

### 7.1 继承决策（早期规划/用户已拍板）

| # | 决策 | 理由 |
|---|---|---|
| R1 | 3.2/3.3 拆两个 feature，3.2 先行 | 用户拍板（2026-09-04）：3.3 planner 消费 3.2 弧光数据，依赖方向明确；3.2 对标伏笔模式风险低 |
| R2 | 防人设漂移 = 写前注入当前阶段 | 阶段 3.2 规划原文；静态设定卡（RAG）管「角色是谁」，本 feature 管「角色走到哪了」 |

### 7.2 设计决策（本 design 拍板）

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 抽取调用次数 | a) 状态更新与变化判定拆两次；b) 单次 JSON | **b** | 输入高度重叠；单次省 token 且 changed 判定能看到完整状态上下文（对标伏笔 D1） |
| D2 | 角色标识 | a) 编号协议（同伏笔）；b) 名字做 dict 键 | **b** | 伏笔用编号因描述文本会变；名字是稳定 id，dict 键天然去重。命名漂移风险 prompt 原名回报预防 + 人工删兜底 |
| D3 | 条目结构 | a) 只 stage 一句话；b) stage+goal+conflict+belief+history | **b** | 对齐 Java 设计文档 CharacterArcStage（goal/conflict/belief 三要素）；goal/conflict/belief 是 3.3 planner 产节拍的原料。evidence 字段弃（token 重、注入不用） |
| D4 | 触发点 | a) 流水线内（reviewer 后）；b) `_write_one` 写后链 | **b** | 状态以**定稿正文**为准（打回重写的中途稿不该被抽）；与摘要/伏笔同点，失败兜底纪律同款 |
| D5 | 抽取失败处理 | a) 部分采信；b) 整体放弃 | **b** | C3 宁缺勿错；错误状态污染后续所有章 prompt，比空着更糟 |
| D6 | 修正缝形态 | a) 等可视化；b) REPL `角色` 命令 | **b** | 宪法 §2 CLI 内置；LLM 抽取必错，无修正缝则错误单调累积 |
| D7 | history 追加条件 | a) 字符串比较；b) LLM changed 语义判定 | **b** | 措辞漂移 ≠ 阶段变化；语义判定只有 LLM 能做 |
| D8 | 同章重写 | a) 累积；b) 覆盖（清 chapter==num history + 状态重抽） | **b（含 num=None 守卫）** | C15：同章两个阶段是脏曲线；覆盖是文档自然语义（对标 F16，含同款守卫） |
| D9 | `角色 改` 是否打 manual 标记 | a) 打（同伏笔 F16 守卫）；b) 不打 | **b** | 语义不同：伏笔是人工资产需永久保护；角色状态是快照，剧情推进本就该覆盖。人工改的价值 = 立即生效供下章抽取输入（模型在修正基础上演进） |
| D10 | 注入截断序 | a) 字典序；b) 更新章倒序 | **b** | 最近活跃角色对下一章写作最相关；伏笔截「最近埋的」同哲学 |

### 7.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | `NOVEL_ARC` 默认 1（开） | 每章 +1 次短调用成本有界；同 `NOVEL_FORESHADOW` 先例，0 一行回退 |
| Z2 | 抽取走主 llm（非 writer_llm） | 判定类调用，同审稿/摘要/伏笔侧；写作侧换商不影响 |
| Z3 | arc_cap 默认 8；history cap 固定 20 不进配置 | cap 防长篇 prompt 膨胀（可调）；history cap 只防无界，无需调参面 |
| Z4 | `角色 删` 直接删不归档 | 角色状态是快照不是线索（伏笔归档因误判不可逆）；删了再出场自然重建，危害有界 |
| Z5 | record 顶层 `arc` 键 + 补写落盘 | 对齐 `foreshadow`/`exemplar_route` 先例；replay 真读得到 |
| Z6 | max_tokens=2048、单章 ≤6 角色（软约束超限全收） | 宪法 §4 推理预算；≤6 防灌水防截断，超限全收不截断（截断丢真主角，对标 F5） |
| Z7 | 已知局限显式入 §4（rewrite 不抽取/快照回退不回溯/命名漂移/reviewer 截断） | 对标 foreshadow Z7：不假装不存在，留给 P1 数据说话 |
| Z8 | 抽取失败 record 留 `{"error": ...}` 键 | replay 必须能分清「没动角色状态」与「抽取挂了」；成本一行 |
| Z9 | reviewer 不加弧光维度 | 已有「人物一致性」覆盖静态人设；弧光验收基准归 3.3 planner（拿节拍验收）再议，防 scope creep |
