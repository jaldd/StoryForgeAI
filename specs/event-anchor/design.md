# 事件锚门禁（event-anchor）- 设计

> 对应需求：同目录 `requirements.md`（E1-E14）。
> 前置：`specs/quality-gate/design.md`（D1-D12/Z1-Z10）、`specs/style-repeat/design.md`（D1-D9/Z1-Z8）
> 均已实现；本文引用其决策编号与模块。
> 行号引用基于 2026-09-19 代码（style-repeat 完成态；`run_checks` 在 checker.py:98，
> `_is_dialogue_line` 在 checker.py:69，`scan_style_report` 在 checker.py:477，
> `reviewer_system` 在 prompts.py:414，`_do_style_scan` 在 cli.py:1355）。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| E1-E6 结构检查 | §3.1 run_structure_checks + §3.2 report-only 接线（D9） |
| E7-E8 reviewer 第 9 维 | §3.3 reviewer_system 模板 + _reviewer 分流（D10） |
| E9-E11 状态章嫌疑榜 | §3.4 scan_style_report 第四节 + _do_style_scan 输出 |
| E12-E14 兼容 | §4 降级哲学 + 既有留痕复用 + schema 不变 |

## 1. 总体设计：三层分工，拓扑零改动

复盘数据（某 300 章实测长篇，anonymized）——两类状态章病灶在既有门禁下的可见性：

| 失效模式 | 实测数据 | 既有检查可见性 |
|---|---|---|
| 碎片章 | 一卷尾部连续 10 章（47-54、58-59），各 4-9 行、170-450 字 | **不可见**（无任何最小体量检查；字数分布只在体检报告，无拦截） |
| 零对话独白章 | 一卷 4 章，1400-2700 字零对话行；含该卷最高潮章 | **不可见**（monologue 上限 80 行，独白靠换行切碎即绕过） |
| 状态堆叠 | 嫌疑分 Top 章状态词密度达 1.5-1.9 次/行（健康章 ≤0.4） | metaphor 只测比喻标记密度，不测状态词 |
| 无事件锚 | 14 章「删掉天气和身体描写后没有完整事件」，全部通过既有检查 | 语义判断，机器不可查，reviewer 八维无此维度 |

分工哲学（D1）：**机器判结构，LLM 判完整，诊断归体检**。
checker 只做三个词法代理（字数/对话行/状态词密度）——它判不出「这件事完不完整」，
但碎片章与零对话章是结构性事实，纯计数即可判死；「事件锚是否成立」是语义判断，
归 reviewer 第 9 维；批量排查归体检榜，服务人工改稿决策。

```
（检测）                                       （预防）
pipeline（拓扑不动）：                          reviewer_system 增第 9 维「事件锚」
  writer -> polisher -> checker -> reviewer      （scores 增键，schema 不变；
                          |                     仅事件锚不达标 -> report-only 放行留痕，D10）
                          | structure issue：不进 fixer 循环、不消耗 review_count（D9）
                          v
                     report-only 通道：显著警告 + state.log 留痕（随 run record）
                          |
                          v
                     人工 `重写`（rewrite 带原文，writer 上下文完整，病灶正解）

（诊断）
风格体检 [目录] --> scan_style_report 增第四节「状态章嫌疑榜」（纯函数，零 LLM）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| `_is_dialogue_line`（checker.py:69，Z9 词法代理） | 对话行计数直接复用，口径与 monologue 检查一致 |
| 结构化 issue 格式（quote/problem/fix） | report-only 通道复用同构格式，零新 issue 类型 |
| run record steps 快照（asdict(state) 含 log/issues） | report-only 留痕零新字段：警告写 state.log 即随 record 落盘 |
| reviewer system 已注入 instruction/rules（写作铁律） | 刻意氛围章的既有逃生通道：铁律中声明「本书允许纯过渡章」（§3.3 D4 补注） |
| `质量规则.json` 加载与 fail-fast 口径（A23） | 新增 `chapter_structure` 一键沿用同一加载器 |
| `scan_style_report` 三节报告与 `_do_style_scan`（style-repeat） | 第四节同款接入，输出段落并列 |
| reviewer JSON schema（pass/reason/scores/issues） | scores 增键不改结构，harness 消费面零改动 |
| `rewrite()` 路径（source_content + writer 完整上下文） | 结构章的正解修复通道（E6），人工触发 |

## 2. 配置面（质量规则.json 新增一键，零新 env）

```json
{
  "chapter_structure": {
    "min_chars": 500,
    "dialogue_check_min_chars": 800,
    "min_dialogue_lines": 2,
    "state_words": ["胸口", "太阳穴", "那处", "睡不着", "头疼", "麻木"],
    "state_density_max_per_100_lines": 40
  }
}
```

- `min_chars`：碎片章阈值（有效字符数，口径见 §3.1）。默认 500；某书若有刻意短章系列，
  按该书章体量分布下调或置 null 跳过（E4）——阈值是诊断锚点，不是目标（总纲「单章字数」同哲学）。
- `dialogue_check_min_chars` / `min_dialogue_lines`：零对话判定 = 体量达标但对话行不足。
  默认 800 字 / 2 行（复盘数据：独白章 1400-2700 字零对话，远在网内；正常短章 500-800 字天然豁免）。
- `state_words`：状态词表，静态配置（非目标 4）。**词表进 NOVEL_DIR，代码仓库零小说词（宪法 §1）。**
- `state_density_max_per_100_lines`：每百行状态词命中上限。默认 40
  （复盘数据：健康章 ≤40，碎片章 150-190；零对话独白章由 E2 主判，E3 补网）。
- **Z3 校准纪律**：`state_words` 词表与密度阈值必须按书的文风基准实测校准，
  **不要直接抄默认值**——若该书文风原则为「天气和身体一起写、每章多次」，
  健康章的状态词密度天然偏高（复盘书即此型，40 是按其数据定的锚点，不是通行标准）。
- 子键独立缺省，逐项跳过（E4）；一键全缺 = E12 逐字节一致。

## 3. 详细设计

### 3.1 run_structure_checks（checker.py 追加，零 LLM）

```python
def run_structure_checks(text: str, rules: Optional[dict]) -> list[dict]:
    """chapter_structure 三项检查 -> issues（与 run_checks 同构）。

    口径（Z1）：
    - 有效行 = 非空行中剔除 `#` 标题行与 `---`/`***` 分隔行（与 extract_ending C2 同款跳过集）；
    - 有效字符数 = 有效行拼接后去空白的长度；
    - 对话行数 = 有效行中 _is_dialogue_line 命中的行数；
    - 非空行数 = 有效行数（密度分母）。

    1. 碎片章（E1）：min_chars 配置且有效字符数 < min_chars
       -> issue{quote="", problem=f"碎片章：正文{有效字符数}字（下限{min_chars}字）",
                fix="本章缺少完整事件。按章节规划补事件锚，扩写为完整章节；不要只往里加字。请使用重写命令。"}
       （quote 置空 = 全文属性；report-only 通道下仅供留痕展示，不参与修复定位，D9）
    2. 零对话独白章（E2）：dialogue_check_min_chars 与 min_dialogue_lines 配置、
       有效字符数 >= 前者且对话行数 < 后者
       -> issue{quote=首个有效行截50, problem=f"零对话独白章：{有效字符数}字仅{对话行数}行对话",
                fix="补回场景与对话：让人物在场、让对话发生；内心独白压缩为不超过3笔的状态登记。"}
    3. 状态堆叠（E3）：state_words 非空且 state_density_max_per_100_lines 配置、
       状态词总命中数/有效行数×100 > 上限
       -> issue{quote=首个状态词所在句截50（_first_sentence_with 复用）,
                problem=f"状态堆叠：状态词每百行{密度}次（上限{上限}）",
                fix="状态登记删至每章3笔以内，删出来的篇幅让给事件。"}
    键缺失/词表空 -> 对应项跳过（E4）；rules 为 None 或 text 为空 -> []。
    """
```

- **Z1 口径统一**：三项共用一份有效行序列，一次遍历产出全部计数，与 monologue 检查同量级开销。
- **Z2 阈值即锚点**：阈值不参与 fail-fast 校验（非负即可），非法值（负数字符串）由加载层类型不符
  自然跳过对应项——不新增 A23 类硬错误（阈值配错最多漏判，不会误判，fail-open 方向安全）。
- **D2 碎片章只判不细分**：不尝试区分「刻意短章」与「没写成」——阈值可配就是出口；
  语义判断归 reviewer（非目标 1）。

### 3.2 _checker 接线（report-only 通道，D9）

**D9 决策依据（2026-09-19 评审实证，prompts.py:440-491）**：

- `fixer_system` 铁律原文：「只改问题处，其余表达一个字都不动」「严禁改动情节」
  「不要合并、移动或增删段落」；`fixer_whole_user` 同款「保留内容，只改问题处……都不要动」。
  给碎片章补事件锚 = 增情节 = 模型按 prompt 行事**必然改不动**。
- `fixer_whole_user(text, issues)` 不携带任何规划上下文；本 feature 的根因正是
  「规划只给状态时 writer 只能产出状态」——fixer 上下文比 writer 还少，事件无从而来。
- 必须避免的后果链：checker 打回 -> fixer 改不动 -> 复检仍命中 -> 烧完 review_count ->
  逃生门放行。检测响了但闭环修不好，且每轮白烧一次整文修复调用
  （碎片章本身一两百字，4096 max_tokens 纯浪费）。

因此结构类 issue 的处置为 **report-only**（E5）：

```python
# _checker 内，run_checks / run_cross_checks 的 issues 维持原打回闭环（不动）。
# run_structure_checks 的命中走独立通道：
structure_issues = run_structure_checks(state.polished, self.quality_rules)
for issue in structure_issues:
    print(f"  ⚠️ 结构检查：{issue['problem']}")
    state.log.append(f"[checker] ⚠️ report-only：{issue['problem']}（建议人工重写）")
# 不并入 state.issues、不消耗 review_count、不触发 fixer；next_agent 照常到 reviewer
```

- 留痕零新字段：`state.log` 经 asdict 随 steps 快照进 run record（复用矩阵）。
- **复检轮重复留痕口径**：`_checker` 每轮复检都会重跑 `run_structure_checks`，
  与常规 issue 打回并存时，结构警告会按打回轮次重复打印/留痕——**可接受（持续可见），
  不去重**：口径确定（每轮必打，与 review_count 无关），实现零状态，
  避免实现时各自发明去重逻辑。
- `quality_rules` 为 None 时函数内直返 []，调用点无需新增条件分支（E12 双降级）。
- 结构命中与既有检查命中并存时两路独立：既有 issue 照走 fixer 闭环，
  结构警告照打，互不干扰。

### 3.3 reviewer 第 9 维（prompts.py reviewer_system 模板）

现状 8 维（prompts.py:417-425）：1-6 一致性维度 + 7 比喻密度 + 8 视角越界。
事件锚追加为第 9 维（E7）——**按现状维度数续号，不插入中间**（插入会挤掉既有 7/8 条，
problem 前缀「维度名：」约定也会错位）：

```
9. 事件锚：删掉天气描写、身体感受、心理描写后，本章是否还剩一件完整成立的事？
   （纯氛围/纯心情/纯状态章 = 不通过）
```

scores 示例 JSON 增 `"事件锚": <1-5>` 键（E7）；issue problem 前缀「事件锚：」（E8）。

- **D3 只改模板不改 schema**：pass/reason/scores/issues 四键同构（E14）；
  `parse_review_full` 对 scores 只收 1-5 整数、对多余键不敏感（A6 容错），解析面零改动。
- **D4 维度无条件存在**：事件锚是跨小说通用维度（每本小说都需要「章里有事发生」），
  不做配置开关——与既有八维同地位。这与 style-repeat 非目标 10（planner 不注入禁则）不冲突：
  那是散文层禁则，这是结构层验收维度。
- **D5 planner 不动（本阶段）**：节拍层注入事件锚声明归 P1（非目标 3）；
  本阶段 reviewer 拦截 + 体检诊断已构成闭环。
- **D10 reviewer 分流（report-only 同哲学，E8）**：解析后将 issues 按 problem 前缀
  「事件锚：」分为两路——
  **仅事件锚不达标**：放行留痕（feedback 标注「事件锚不达标，建议人工重写」，
  final_chapter 定稿，state.log 留痕）；
  **混合不达标**：事件锚 issue 剔除出 fixer 修复批次（不可段落修复，quote 空会触发
  无意义的整文降级调用），仅留痕，其余 issue 走正常闭环。
  **防循环**：复检时若剩余不达标项全为事件锚，按「仅事件锚不达标」放行——
  每章最多经历一轮可修复项的 fixer 循环，事件锚不制造重复打回。
- **D4 补注（已知局限，评审次要点 3）**：第 9 维无条件启用，对「刻意氛围章/纯过渡章」
  无配置出口。既有逃生通道：reviewer system 已注入 NOVEL_DIR 的写作铁律
  （instruction/rules 参数），在铁律中声明「本书允许纯过渡章」即可让 reviewer 豁免；
  P1 T4（planner 声明事件锚）落地后从源头消解。

### 3.4 状态章嫌疑榜（checker.py scan_style_report 追加 + cli 输出）

`scan_style_report` 增第四节（E9/E10）：

```python
def _state_suspicion(text: str, state_words: list[str]) -> dict:
    """单章嫌疑数据（纯函数）：{"score", "lines", "dialogue", "state_hits"}。
    score = state_hits/有效行数 - 对话行数/有效行数×2（Z1 同款有效行口径）。"""

# report["state_chapters"] = [
#   {"file": rel, "score": round(score, 2), "lines": n, "dialogue": d, "state_hits": s}
#   ... 按 score 降序，全量入报告；cli 只打 Top 20
# ]
# state_words 缺失或为空 -> report["state_chapters"] = None（未配置），
# cli 打一行「状态章嫌疑榜：未配置 chapter_structure.state_words，跳过」
```

- **D6 事件侧不做词表代理**：嫌疑分只用「状态-对话」两极。配角名/物件词表（audit 脚本原型
  曾有 event_words）砍掉——事件完整性是语义判断，词法代理误伤面大（散文体章配角稀薄是正常的），
  配置面少一个键，判断责任边界干净（机器判结构）。
- **D7 榜全量入报告、截断在展示层**：`scan_style_report` 是纯函数，全量数据留给调用方
  （未来批量模式/API 可复用）；Top 20 只是 `_do_style_scan` 的打印口径。
- **D8 None 与空榜分态**：未配置（None）与配置后无文件（[]）输出文案分开，
  配置静默失效必须可发现（quality-gate Z7、style-repeat C12 同哲学）。

## 4. 降级与边界

| 场景 | 行为 |
|---|---|
| `chapter_structure` 键全缺 | E12：结构检查与体检新节全跳过、逐字节一致（reviewer 第 9 维按 D4 无条件生效，不属本行范围） |
| 子键部分缺失 | E4：逐项独立跳过（如只配 min_chars = 只查碎片章） |
| state_words 空表 | 密度项与嫌疑榜跳过（D8 未配置提示） |
| 结构检查命中 | report-only：警告 + state.log 留痕，直通 reviewer，不消耗 review_count（D9） |
| reviewer 仅事件锚不达标 | 放行留痕，feedback 标注建议人工重写（D10） |
| reviewer 混合不达标 | 事件锚 issue 仅留痕；其余 issue 走正常 fixer 闭环（D10） |
| 碎片章/零对话章修复 | 人工 `重写` 命令（E6）；闭环内修复不做（非目标 9） |
| 旧 run 记录回放 | E13：无新 state 字段，天然兼容 |
| 刻意短章系列 | 调低或置 null min_chars（§2，阈值即锚点） |

## 5. 测试设计（全部离线：tmp 目录 + FakeLLM）

- **checker**：三项命中/边界（恰等于阈值不报）/键缺省跳过/词表空跳过/quote 为原文子串断言
  （碎片章除外，其 quote 恒空）；有效行口径（标题行、分隔行不计入）。
- **agent 接线**：structure issue 命中 -> 不进 fixer、review_count 不变、
  next_agent=reviewer、state.log 含警告留痕；与既有检查命中混合时两路互不干扰；
  规则为 None 时 steps 与现状一致（E12 回归护栏）。
- **reviewer 分流**：仅事件锚不达标 -> 放行留痕定稿；混合不达标 -> fixer 批次不含
  事件锚 issue、复检仅余事件锚时放行（防循环）；全为非事件锚问题 -> 行为与现状一致。
- **prompts**：reviewer_system 含第 9 维文本与 scores 键；JSON 模板四键同构（E14）。
- **scan 报告**：嫌疑分计算（构造已知状态词/对话比的假章）；降序与字段完整；
  state_words 缺省 -> None；空目录 -> files_scanned=0（E11 现状）。
- **harness 兼容**：旧 run 记录 replay 正常（E13）。
