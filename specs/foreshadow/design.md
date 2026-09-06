# 阶段 3.1：伏笔自动追踪（foreshadow）- 设计

> 对应需求：同目录 `requirements.md`（F1-F17）。
> 前置：`specs/throughput/`（W1-W7）已实现（461 passed 基线）--本文消费其
> `_write_one` 写后链路与批量「复用既有路径即得连续性」的结构保证。
> 行号锚点基于 2026-08-31 代码（throughput 完成态），实现时以函数名为准。
> 修订（2026-08-31，评审后）：record 补写落盘（A1）、进度指针移出 try（A2）、
> 回收归档不物理删除（A3）、F12 口径统一（B1）、截断参数化（B2）、批量 wm
> 逐章重读盘的事实修正（C1）。
> 修订（2026-08-31，评审二轮）：num=None 清洗守卫（防抹掉无章号条目）、失败留痕
> error 键（F4 补齐）、`伏笔 删` 统一归档路径（硬删通道取消）、manual 标记防
> 覆盖误删人工条目、≤5 软约束超限全收。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| F1-F5 抽取回路 | §3.1 extract_foreshadowing + §3.3 触发点 |
| F6/F8 结构与护栏 | §3.2 条目结构 + snapshot 截断 |
| F7 注入格式 | §3.2 snapshot 渲染 |
| F9/F10/F15/F17 人工修正缝 | §3.5 REPL 命令 |
| F11-F14 配置与兼容 | §2 配置面 + §3.4 降级 |
| F16 同章重写覆盖 | §3.3 触发点 |

## 1. 总体设计

流水线拓扑零改动。本 feature 是一个**写后旁挂回路**加一条 REPL 命令：

```
_write_one（既有，不动结构）
  └─ 存盘后写后链：摘要 -> wm.update_after_write -> save_working_memory
       │  本 feature：摘要之后、update 之前插入（顺序见 §3.3）
       ▼
  agent.extract_foreshadowing(定稿正文, 带编号的 unresolved 清单)
       │  一次 JSON 调用：{"new": [{"desc"...}], "resolved": [编号...]}
       ▼ 成功                    ▼ 失败/不可解析
  回收出列->归档 + 覆盖式追加      跳过不更新（F3），打印原因
       │                          （进度指针/摘要/落盘已在 try 外完成）
       ▼
  save_working_memory（既有同一次落盘，不额外写）+ 补一次 save_run（record 留痕落盘，F4）

writer/polisher/reviewer --working_context--> snapshot(cap=settings.foreshadow_cap)
REPL：伏笔 / 伏笔 删 N / 伏笔 加 <描述> / 伏笔 已回收（人工修正缝）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `WorkingMemory.update_after_write(new_foreshadowing=)`（memory.py:49） | 参数已在从未被传，正好接住新增 |
| `snapshot()` / working_context 注入链（agent.py:346） | 渲染格式升级 + cap 参数，注入面不动 |
| `save_working_memory` / `load_working_memory`（storage.py） | 序列化随结构升级 + 旧数据兼容读取 |
| `summarize_chapter` 的调用位置与异常兜底纪律（cli.py `_write_one`） | 抽取调用放在同一点，失败不阻断同款 |
| `agent._temp(kind)` 温度链（0.9 全量可配） | 新 kind `foreshadow`，默认 0.2 |
| `record` 顶层键留痕先例（`exemplar_route`，A5） | 顶层 `foreshadow` 键 + 抽取后补写（A1 修正） |
| parse_review 的 JSON 提取容错（剥围栏/杂文字） | 抽取 JSON 解析复用同思路 |

## 2. 配置面（新增 3 个 env，全部有零值降级）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_FORESHADOW` | 抽取回路开关 | `1` | int，`0` = 关回路（快照新格式/人工命令保留，F12） |
| `NOVEL_FORESHADOW_TEMPERATURE` | 抽取调用温度 | `0.2` | float，走 `_temp("foreshadow", 0.2)` |
| `NOVEL_FORESHADOW_CAP` | prompt 注入护栏条数 | `30` | int，`0` = 不截断；只影响注入不影响判定 |

## 3. 详细设计

### 3.1 抽取调用（D1/D2/D8）

`agent.py` 新增方法（收编模式，同 `summarize_chapter` 先例）：

```python
def extract_foreshadowing(self, chapter_text: str, unresolved: List[dict],
                           chapter_no: Optional[int] = None) -> dict
```

- **单次调用双职（D1）**：prompt 给出本章正文 + 带编号的既有伏笔清单，要求返回：

```json
{"new": [{"desc": "一句话自包含描述"}, ...], "resolved": [2, 5]}
```

备选「抽取与回收判定拆两次调用」被否：两次短调用的输入高度重叠（都要正文），
且判定回收必须看到新伏笔全集防误判双计；一次调用 token 省一半、判定质量更高。
- **编号协议（D2）**：`resolved` 只收编号（1 起，与清单展示序一致），不收描述文本--
  描述回写要做模糊匹配，错一个字就既不出列也不报错（静默失败）；编号是机械映射。
  越界/重复编号静默丢弃。
- **输出预算（D8/F5/F11）**：max_tokens=2048（宪法 §4 推理模型思考计入预算，
  30 条判定 + 多条自包含描述比审稿 JSON 更长；对齐 reviewer 调用档而非 1024）；
  prompt 明令单章新增 ≤5 条（**软约束**：模型返回超限时全收不截断--截断丢真伏笔，
  违背宁缺勿错；≤5 防的是输出截断与灌水倾向，不是硬闸，Z6）。
- 新条目落 `{"desc": ..., "chapter": chapter_no}`（埋设章号，F6）；`new` 与既有清单
  描述完全同串的跳过（机械去重，D7）；近义重复靠 prompt 明令「清单里已有的不要重复报」。
- 返回 `{"new": [...], "resolved": [...], "raw": 原始返回}`，raw 供留痕与调试。

### 3.2 条目结构与 snapshot 渲染（D3/D4/F6-F8）

`WorkingMemory` 侧（memory.py）：

- `unresolved_foreshadowing: List[dict]`，条目 `{"desc": str, "chapter": Optional[int]}`，
  人工补录条目另带 `"manual": True`（F16 覆盖清洗跳过）；
- 新增 `resolved_foreshadowing: List[dict]`，条目 `{"desc": str, "chapter": 埋设章,
  "resolved_chapter": int}`（A3：回收归档不物理删除，误判可人工移回；人工
  `伏笔 删` 同入此归档，resolved_chapter 取当前章、current_chapter 为空则 None）；
-   `update_after_write` 签名不变（`new_foreshadowing` 收 `List[dict]`，str 元素转 dict
  容错）；新增 `resolve_foreshadowing(indices, chapter_no)`（按 1 起编号出列并移入
  归档，越界/重复/非整数编号忽略，一次结算防错位；模型回收与人工 `伏笔 删` 同调）；
  新增 `add_foreshadowing(desc, chapter=None, manual=False)`（人工补录入口）；
- `snapshot(cap: Optional[int] = None)` 渲染升级（B2：cap 参数化，None = 全量）：

```
未回收伏笔（写作时应考虑推进或回收，不强行回收）：
  1.（第5章埋）抽屉里的怀表停在案发当晚十点
  2.（第7章埋）林晚始终没拆那封信
  …（共 35 条，仅注入最近 30 条）
```

  - **截断保留原编号**（F8）：取尾部 cap 条但沿用全量编号（被截头部条目不重排），
    与 `伏笔` 命令的全量编号一致；
  - `chapter` 为 None（旧数据/章号解析失败）：省略「（第N章埋）」前缀只显描述；
  - 调用方：`agent._working_context` 传 `cap=self.settings.foreshadow_cap`
    （writer/polisher/reviewer 注入面一致）；`状态`/`伏笔` 命令传 None 看全量。
- `load_working_memory` 兼容：列表元素是 `str` -> `{"desc": s, "chapter": None}`；
  是 dict 且有 `desc` -> 原样收；其余脏元素丢弃（不因一条脏数据拒载整个文件）。

### 3.3 触发点与留痕（D5/F1-F4/F16）

`cli._write_one` 存盘分支内（摘要之后、`save_working_memory` 之前）：

```python
summary = agent.summarize_chapter(...)              # 既有，异常兜底同现状
wm.update_after_write(num, summary or task)          # 既有：无条件在 try 外（A2 修正）
if settings.foreshadow_enabled:                     # F12 开关
    try:
        fo = agent.extract_foreshadowing(
            state.final_chapter, wm.unresolved_foreshadowing, chapter_no=num)
        wm.resolve_foreshadowing(fo["resolved"], num)      # 出列 -> 归档（A3）
        if num is not None:                               # F16 覆盖清洗（num 守卫）
            wm.unresolved_foreshadowing = [
                e for e in wm.unresolved_foreshadowing
                if e.get("chapter") != num or e.get("manual")]
        for e in fo["new"]:
            wm.unresolved_foreshadowing.append({"desc": e["desc"], "chapter": num})
        record["foreshadow"] = {                          # F4 成功留痕
            "new": fo["new"], "resolved": fo["resolved"],
            "unresolved_after": len(wm.unresolved_foreshadowing)}
        save_run(record, settings)                        # A1 修正：补写一次（同 run_id 覆盖）
        print(f"🧵 伏笔：+{len(fo['new'])} 回收 {len(fo['resolved'])}"
              f"（未回收 {len(wm.unresolved_foreshadowing)}）")
    except Exception as e:
        print(f"(伏笔抽取跳过：{e})")                      # F3：列表不更新，写作流程照常
        record["foreshadow"] = {"error": str(e)}          # F4 失败留痕（评审二轮）：
        try:                                              # replay 必须能分清「没埋伏笔」
            save_run(record, settings)                    # 与「抽取挂了」；补写失败仅吞掉，
        except Exception:                                 # 不反噬主流程
            pass
save_working_memory(wm, settings)                         # 既有，无条件（try 外）
```

- **A2 关键点**：进度指针（current_chapter/last_plot_point）更新与 wm 落盘都在 try 外
  无条件执行；try 内只有伏笔三步 + record 留痕。抽取失败最坏损失 = 本章伏笔未记账，
  绝不丢进度/摘要。
- **A1 关键点**：`save_run` 在该分支前已执行（cli.py:346），record 后补写一次
  （同 run_id 覆盖，落盘路径不变故无需改打印）；留痕位置在 `exemplar_route` 之后的
  record 顶层。
- **F16 覆盖语义**：抽取成功后先清 `chapter == num` 的旧条目再追加（`写第5章` 重跑
  不累积近似重复）。**两道守卫（评审二轮）**：`num is None`（任务串解析不出章号，
  如「写一段番外」）时**不清洗只追加**--`!= None` 会把所有无章号条目（旧 str 兼容
  数据、首章前 `伏笔 加` 补录）一次抹掉；`manual` 条目跳过清洗（人工补的线不该被
  模型重跑覆盖）。清洗发生在 resolve 之后、基于同一份抽取输入（编号以抽取调用时
  清单为准）。
- **批量模式零适配（C1 修正）**：`_build_agent` 每章 `load_working_memory` **重读盘**
  （非同实例传递）--行为等价的前提是「每章末已落盘」，`save_working_memory` 在章末
  无条件执行保证了这一点。测试按「落盘 -> 再读回」断言，monkeypatch 打在每次新建的
  agent 上。
- **中断章不抽取**（Z5 同哲学）：`interrupted/failed/rejected` 结局不走存盘分支，
  自然不抽取。

### 3.4 降级与兼容（F12/F14）

- `NOVEL_FORESHADOW=0`：`settings.foreshadow_enabled` 为假 -> 触发点整段跳过；
  快照新格式与 `伏笔` 命令保留（B1 统一口径：开关只关抽取回路，不关基础设施）。
- 旧 run record 无 `foreshadow` 键：replay/compare 不读该键，天然兼容。

### 3.5 REPL 命令（D6/F9/F10/F15/F17）

| 命令 | 行为 |
|---|---|
| `伏笔` | 列出全部未回收（编号+埋设章+描述）；为空时提示可 `伏笔 加` 手动补 |
| `伏笔 删 3`（支持多编号空格分隔） | 出列入归档（与模型回收**同一条 resolve 路径**，resolved_chapter 取当前章、为空则 None；一切「从清单消失」都可从归档恢复，物理删除暂无通道--评审二轮：硬删与 A3 哲学矛盾） |
| `伏笔 加 <描述>` | 追加一条（chapter 取 wm.current_chapter，**打 manual 标记**--F16 覆盖清洗跳过），落盘 |
| `伏笔 已回收` | 列出归档（描述 + 埋设章 + 回收章），可人工抄回 `伏笔 加`（移回不自动化，P1 视误伤率再议） |

- 命令入口先 `settings.require_novel_dir()`（读盘需要，F9）；
- `伏笔 删` 编号 = 列表序号（1 起）；连续删多条**先算索引集再一次删除**（删一条后
  其余编号错位，Z4 坑位）；
- `_do_status` 增补：current_chapter 为空但 unresolved 非空时也打印伏笔块（F17，
  现状 None 分支只打「尚未创作任何章节」，人工补录不可见）；**只在 None 分支补伏笔
  块，别改成无条件 `print(snapshot())`**（会打出「当前进度：第None章」类噪音，
  评审二轮边界）；
- `_print_help` 增一行。

## 4. 已知局限与不动清单

**已知局限**（真车数据说话后再议，不在本 feature 修）：

- **重写/精修/去AI 路径不抽取**：`_do_rewrite`/`_do_refine`/`_do_deai` 走
  `_refine_postprocess`，有 wm 更新（cli.py:90）但无抽取通道--重写大幅改动后该章
  旧伏笔条目可能失真，人工经 `伏笔` 命令修正。同章重写的 `写第5章` 路径有 F16 覆盖，
  rewrite 路径没有。
- **截断削弱 reviewer 判定依据**：reviewer 的「伏笔一致性」维度（harness._SCORE_DIMS）
  消费的也是 working_context 快照，cap 截断后它看到的是尾部子集。接受：cap 默认 30
  对绝大多数作品覆盖全量；cap=0 可关截断换 token 成本。
- **回收判定误伤**：LLM 单次判定无确认门（W8 备选）；A3 归档保证误伤可恢复。
- **归档只增不减**：`resolved_foreshadowing` 无清理通道，长篇累积无界（单条很小，
  量级可控）；P1 视真车体量再定清理/导出策略。

**不动清单**（防漂移）：

- 流水线状态机与角色拓扑（writer->polisher->checker->reviewer+fixer）。
- `update_after_write` 既有两参语义（current_chapter/last_plot_point 覆写行为）。
- working_context 的注入范围（三角色同一份，不窄化不扩面，F7）。
- `save_chapter`/`parse_chapter_task`/RAG 入库链路。
- 批量编排 `_do_write_batch` 的结局判定与章间循环。
- `py/`、Java 侧。

## 5. 实现注意（坑位）

- **编号口径**：清单展示、`resolved` 回报、`伏笔 删 N` 三处编号同源（1 起、列表序），
  抽取 prompt 里的清单编号必须与传入顺序一致；snapshot 截断**不**影响抽取输入--
  抽取拿全量清单，且截断后的快照保留原编号（F8）。
- **截断只影响注入不影响判定**：`extract_foreshadowing` 的输入清单必须全量
  （截断的旧伏笔仍可能在后续章被回收，必须留在判定池里）。
- **JSON 解析容错**：模型可能裹 ```json 围栏或前后加话，解析前剥围栏；剥完仍非法
  -> 整体视为失败走 F3（宁缺勿错，不做部分采信）。
- **空伏笔清单的首次抽取**：prompt 里「既有伏笔：无」也要能正确返回全 new
  （不能因为清单空把 new 也返回空）。
- **温度链**：`_temp("foreshadow", 0.2)` 不属于写作侧 kind，不吃 `NOVEL_TEMPERATURE`
  兜底（与 reviewer/judge 同类，只看自己的键和默认）。
- **record 补写的时序**：`save_run` 第二次调用发生在 gate 判定之后（存盘分支内），
  record 内容与第一次落盘版差异仅多 `foreshadow` 键；打印的 run_file 路径不变。
- **批量测试口径（C1）**：批量场景断言「第二章抽取输入含第一章新增伏笔」要走真实
  `load_working_memory` 落盘-重读链（或 monkeypatch `_build_agent` 内的 load），
  不能假设 wm 同实例传递。

## 6. 测试策略（全程不联网）

- **test_storage.py（memory 侧既有用例同居处）**：条目结构升级（str 兼容读取/dict
  原样收/脏元素丢弃）；`resolve_foreshadowing` 正常/越界/重复编号 + 归档落盘
  roundtrip；snapshot 新格式（编号+埋设章+指令文案）、cap 截断（>cap 标注、原编号
  保留、cap=0 不截断、chapter=None 无章号前缀）。
  **基线变更声明**：既有 `test_working_memory_roundtrip` 断言
  `unresolved_foreshadowing == ["伏笔A"]` 需随结构升级改为 dict 条目断言（本 feature
  唯一被修改的既有用例，实现时在 tasks 里显式记录）。
- **test_agent.py**：`extract_foreshadowing` 的 JSON 解析（正常/围栏包裹/带杂文字/
  非法 JSON 抛异常）、resolved 越界编号丢弃、new 与既有同串去重、温度链走
  `foreshadow_temperature`、空清单返回全 new、max_tokens=2048 与 prompt 含 ≤5 条
  上限文案。
- **test_cli_write.py**：触发点接线（monkeypatch extract 断言 new 入 wm/resolved
  出列入归档/record 留痕且**落盘后 load_run 能读到**（A1）/打印 🧵 行）；失败路径
  （抛异常 -> 伏笔列表不变、**进度指针与摘要照常更新且落盘**（A2）、**record 落
  `{"error": ...}` 留痕（F4 二轮）**、写作流程走完存盘）；`NOVEL_FORESHADOW=0` ->
  零调用；同章重写覆盖（F16，含两守卫：manual 条目不被清、`num=None` 任务（如
  「写一段番外」）不清无章号条目）；批量两章场景第二章抽取输入含第一章新增伏笔
  （走落盘-重读链，C1）；预算提示 7-10 文案。
- **test_cli（伏笔命令，并入 test_cli_write.py）**：四形态（列表/删（断言入归档
  而非物理删除，F15 二轮）/加（断言 manual 标记与落盘）/已回收）、删编号一次给全
  不错位、require_novel_dir 校验、help 增行、_do_status 首章前伏笔可见且不打
  「第None章」噪音（F17）。
- **test_config.py**：三 env 默认值与覆盖、`NOVEL_FORESHADOW=0` 解析。
- **回归**：`cli/` 下 `python -m pytest tests/ -q`，**492 passed / 0 failed /
  1 deselected**（2026-09-01 实测：原 461 基线 + 新增 31 条，含 2 处既有断言的
  显式修改--`test_working_memory_roundtrip` 的条目结构、`test_batch_...continuity`
  的 6-9 -> 7-10 预算文案），零新增失败。

## 7. 决策表

### 7.1 继承决策（早期规划已拍板）

| # | 决策 | 理由 |
|---|---|---|
| R1 | 伏笔追踪独立成 feature（不与 3.2/3.3 捆绑） | 开放问题 4；字段已在，只缺回路 |
| R2 | 回收即出列（unresolved 只留未回收） | 阶段 3.1 规划原文 |

### 7.2 设计决策（本 design 拍板）

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 抽取与回收判定 | a) 两次调用；b) 单次 JSON | **b** | 输入高度重叠；单次省 token 且判定能看到新伏笔全集 |
| D2 | 回收回报协议 | a) 描述文本；b) 编号 | **b** | 文本模糊匹配是静默失败源；编号是机械映射 |
| D3 | 伏笔条目结构 | a) 纯 str（现状）；b) {desc, chapter} | **b** | 埋设章号是「拖了多久该收了」的判据；str 兼容读取保旧数据 |
| D4 | 触发点 | a) 流水线内（reviewer 后）；b) `_write_one` 写后链 | **b** | 伏笔以**定稿正文**为准（打回重写的中途稿不该被抽）；与摘要同点，失败兜底纪律同款 |
| D5 | 抽取失败处理 | a) 部分采信（new 收 resolved 弃）；b) 整体放弃 | **b** | F3 宁缺勿错；半次更新比不更新更难推理 |
| D6 | 修正缝形态 | a) 等下版可视化；b) REPL `伏笔` 命令 | **b** | 宪法 §2 CLI 内置；LLM 抽取必错，无修正缝则错误单调累积 |
| D7 | 去重口径 | a) LLM 判重；b) 机械同串 + prompt 预防 | **b** | 判重交给 LLM 又是模糊匹配；机械去重兜底，prompt 明令不重复报 |
| D8 | 回收去向 | a) 物理删除；b) 移入 resolved 归档 | **b** | A3（评审）：误判不可逆是 F3 自己反对的事；归档成本近零且可人工恢复；二轮修订：`伏笔 删` 同走此路径（硬删与「不丢数据」哲学矛盾，且模型漏判的人工回收通道只能经删） |
| D9 | 同章重写 | a) 累积（靠同串去重）；b) 覆盖（先清同章旧条目） | **b（含两守卫）** | F16：近似重复机械去重挡不住；覆盖是文档的自然语义（Z7 先例）；二轮守卫：`num=None` 不清洗（否则抹掉全部无章号条目）、manual 条目跳过（人工补录不被模型重跑覆盖） |
| D10 | 截断实现位置 | a) snapshot 内固定截断；b) snapshot(cap) 参数化 | **b** | B2（评审）：a 会让 `状态` 也被截断违反 F8；参数化让命令侧全量、注入侧受限 |

### 7.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | `NOVEL_FORESHADOW` 默认 1（开） | 每章 +1 次短调用成本有界；同 `NOVEL_STREAM` 先例，0 一行回退 |
| Z2 | 抽取走主 llm（非 writer_llm） | 判定类调用，同审稿/摘要侧；写作侧换商不影响 |
| Z3 | 截断护栏默认 30 条 | 防多年连载下 prompt 无界膨胀；截断只影响注入不影响判定（§5 坑位）；对 reviewer 伏笔一致性维度的削弱见 §4 已知局限 |
| Z4 | `伏笔 删` 编号 = 列表序号 | 简单命令不引入持久 id；一次给全防错位 |
| Z5 | 抽取留痕进 record 顶层键 + 补写落盘 | 对齐 `exemplar_route` 先例；A1（评审）修正后 replay 真读得到 |
| Z6 | max_tokens=2048、单章新增 ≤5 条（软约束） | 宪法 §4 推理预算；30 条判定 + 多条描述比 1024 长；≤5 防灌水防截断，超限全收不截断（截断丢真伏笔，评审二轮） |
| Z7 | 已知局限显式入 §4（rewrite 不抽取 / reviewer 截断 / 归档只增不减） | 评审 D 组+二轮：三处都不假装不存在，留给 P1 数据说话 |
| Z8 | 抽取失败 record 留 `{"error": ...}` 键 | 评审二轮：replay 必须能分清「没埋伏笔」与「抽取挂了」；成本一行 |
