# 阶段 1 续：文风复读防治（style-repeat）- 设计

> 对应需求：同目录 `requirements.md`（C1-C18）。
> 前置：`specs/quality-gate/design.md`（D1-D12/Z1-Z10）与 `specs/style-loop/design.md`（D1-D8/Z1-Z6）均已实现；本文引用其决策编号与模块。
> 行号引用基于 2026-09-06 代码（planner 完成态；`_checker` 在 agent.py:623，`save_chapter` 在 storage.py:223）。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| C1-C8 跨章检查 | §3.1 指纹纯函数 + §3.2 run_cross_checks、§3.3 _checker 接线 |
| C9-C12 负面清单注入 | §3.4 build_style_taboos + writer_system 第 7 参 |
| C13-C15 风格体检 | §3.5 scan_style_report + `风格体检` 命令 |
| C16-C18 兼容 | §3.6 双降级 + 既有留痕复用 + exclude 防自比 |

## 1. 总体设计：三个旁挂能力，拓扑零改动

复盂数据（某 300 章实测长篇，anonymized）——四类失效在单章视角下的可见性：

| 失效模式 | 实测数据 | 既有检查可见性 |
|---|---|---|
| 收束句复读 | 同一收束句全书 79+ 次独立成行，后期卷几乎每章结尾 | **不可见**（checker/reviewer 均单章纯函数） |
| 句式模板堆积 | 「像一个人」模板 11 次集中于一卷；「不是X，是Y」单卷 40+ 次 | metaphor 只测标记词密度（8% 上限），每章合规、跨章成癖 |
| 章节字数均一 | 一卷 45 章全落 5.8-6.0KB（变异系数≈0.02） | 不可见（无任何字数统计） |
| 总结型章节 | 14 章从场景退化为议论，全部通过既有检查 | monologue 上限 80 行太松；语义级归 reviewer（本 feature 非目标 3） |

前两类是本 feature 的主战场（机械可查）；第三类只诊断（非目标 1）；第四类不碰（非目标 3）。

```
（1.8 预防）                               （1.7 检测）
_build_agent ──读 chapter_path 尾部 N 章──>  流水线（拓扑不动）：
   │  现算 recent_endings + taboos            writer -> polisher -> checker -> reviewer
   │                                            ^ cross issues 并入 _checker（§3.3）
   └──> writer_system 增【近期文风禁则】分节      | 打回（共享 review_count）
                                              v
                                             fixer（既有闭环，白拿）

（1.9 诊断）
风格体检 [目录] ──递归扫描──> scan_style_report（纯函数）──> 三张清单（改稿工作台）
```

复用矩阵（不重复建设）：

| 既有资产 | 本 feature 消费方式 |
|---|---|
| checker 结构化 issue（quote/problem/fix）与 `_checker` | cross issues 同构并入，fixer 打回-复检闭环零改动 |
| `质量规则.json` 加载与 fail-fast 口径（A23） | 新增两键沿用同一加载器，pattern 预编译校验 |
| `_fix_spans` 段落定位/标记协议/字数保护（style-loop D2 抽取） | 结尾行与句式命中句均为可定位 quote，fixer 直接修 |
| `writer_system` 参数演进先例（recent_human 第 6 参） | 第 7 参 style_taboos 同款「默认空串零改动」 |
| style-loop Z1 字典序章序约定 | 参照章**组内**（同卷）尾部选取同口径；跨卷排序本 feature 新增（Z7） |
| `状态` 命令可发现性（Z7 哲学） | 禁则状态一行 |

## 2. 配置面（质量规则.json 新增两键，零新 env）

```json
{
  "ending": {"lookback": 10, "max_repeat": 2, "min_chars": 3},
  "syntax_patterns": {
    "patterns": ["像一个人", "不是[^，。]{1,12}[。，][^。]{0,4}是"],
    "max_per_chapter": 1
  }
}
```

- `ending.lookback`：参照章窗口（含写入 prompt 禁则与 checker 比对，同源）。
- `ending.max_repeat`：窗口内（含本章）同一归一化结尾的容忍次数，超出即 issue。
- `ending.min_chars`：归一化后长度下限，低于它不参与比对（默认 3：「风很轻」在网内，「挨着」豁免）。
- `syntax_patterns.patterns`：正则列表，作用于全文（`re.findall` 计数）。
- `syntax_patterns.max_per_chapter`：每章配额（默认 1）。
- 两键独立缺省，全缺 = C5/C16 双降级。
- P1 预留：`NOVEL_TARGET_WORDS_JITTER_PCT`（默认 0 = 现状），见 tasks P1。

## 3. 详细设计

### 3.1 指纹纯函数（checker.py 追加，零 LLM）

```python
_SENT_STRIP = "。！？…—，、；：""''」』?!."

def extract_ending(text: str) -> str:
    """最后一个非空行；跳过 ---/***/# 标题行；无正文返回 ""。"""

def normalize_ending(line: str) -> str:
    """strip + 循环去句末标点尾缀 + 再 strip。"""

def load_recent_endings(
    dir_path: Path,
    lookback: int,
    exclude: Optional[Path] = None,
) -> list[str]:
    """人工正文目录递归收集 .md（忽略点前缀目录与 .agent，Z6 同款），
    按跨卷章序（Z7：卷序 = 目录名解析「第X卷/部/册」中文或阿拉伯数字，
    失败回退字典序且排在可解析之后；章序 = 文件名尾部 -0*(\\d+)，
    无数字回退字典序）取尾部 lookback 个的归一化结尾列表。
    exclude = 当前被精修/重写/去AI 的文件路径（C18 防自比）。
    目录不存在/无文件 -> []；不可读跳过。纯函数、现算、无缓存。"""

def compile_syntax_patterns(rules: dict) -> list[re.Pattern]:
    """syntax_patterns.patterns 预编译；非法正则或可零宽匹配
    （pat.search("") 命中）-> RuntimeError（含 pattern 原文，C4）。
    键缺失 -> []。"""
```

零宽拒收（Z2）：`re.findall` 对零宽模式会产出海量空匹配，计数直接爆炸，加载期拒收最安全。

### 3.2 run_cross_checks（checker.py 追加）

```python
def run_cross_checks(
    text: str,
    recent_endings: list[str] | None,
    rules: dict,
) -> list[dict]:
    """两项跨章检查 -> issues（与 run_checks 同构）。

    1. ending：mine = normalize_ending(extract_ending(text))；
       len(mine) >= min_chars 且 recent_endings.count(mine) + 1 > max_repeat
       -> issue{quote=结尾行原文截50, problem=f"收束句复读：最近{len(recent_endings)}章已用{n}次",
               fix="重写结尾段：换一个动作或画面收束，不要复用近期用过的句子"}
    2. syntax_patterns：compile 后逐 pattern findall 计数 > max_per_chapter
       -> issue{quote=首个命中句截50, problem=f"句式模板超配额：命中{n}次（上限{k}）",
               fix="删或改写多余命中，保留最有效的一处"}
    recent_endings 为 None/[] 或键缺失 -> 对应项跳过。
    """
```

- 两个 quote 均为原文子串（D12 可定位性），fixer 走既有段落级修复。
- 命中句定位：取 `split_sentences` 中首个含 `match.group(0)` 的句子（`_first_sentence_with` 同款纪律）。

### 3.3 接线（agent.py + cli.py）

**注入**（`NovelAgent.__init__`，同 `recent_human` 先例）：

```python
recent_endings: Optional[list[str]] = None,   # cross 检查参照（None = 跳过）
style_taboos: str = "",                       # writer 禁则分节（空 = 不占位）
```

**`_checker`**（`agent.py:623`）两行改动：

```python
issues = run_checks(state.polished, self.quality_rules)
if self.quality_rules and self.recent_endings is not None:
    issues += run_cross_checks(state.polished, self.recent_endings, self.quality_rules)
```

打回目标、review_count 共享、fixer 复检全部既有机制（C6/C8 零新状态）。

**`cli._build_agent`**（5 个调用点：写/精修/重写/去AI/改，均在 try 外的 RuntimeError 捕获已覆盖 C4 落点）：

```python
ending_cfg = (rules or {}).get("ending") or {}
recent_endings = None
if ending_cfg:
    recent_endings = load_recent_endings(
        settings.human_text_full, ending_cfg.get("lookback", 10),
        exclude=active_file,   # 精修/重写/去AI 传入被处理文件；写新章为 None
    )
taboos = build_style_taboos(recent_endings, rules)     # §3.4
```

- 参照章取 `human_text_full`（D6：实测工作流是 AI 初稿直接写进 `正文/第X卷/` 原位精修，初稿与定稿同目录演化；`chapter_path` 在该工作流为空）。参照集与滚动注入/体检同源，改 `NOVEL_HUMAN_TEXT` 一处全生效；写第 N 章时窗口 = 已存的 N-1 章，卷尾→卷首过渡被跨卷排序（Z7）正确覆盖。
- `精修`/`重写`/`去AI` 把被处理文件路径经 `_build_agent` 新增可选参 `active_file` 传入 exclude（C18；既有调用点默认 None 零改动）。
- 写/精修/重写/改 四命令复用 `_build_agent` 天然生效（agent 内 `_checker` 走 cross checks）。
- **去AI 是直调例外**：`_do_deai` 不经 agent 流水线，直接 `run_checks(content, rules)`（cli.py:793）——需在同处追加 `run_cross_checks(content, recent_endings, rules)` 直调（参照集已在 `_build_agent` 构造，exclude=被处理文件，C18 语义落地）；只取可定位 issue（quote in content）同 B10 口径。

### 3.4 负面清单注入（prompts.py + 复用 §3.1）

```python
def build_style_taboos(recent_endings, rules) -> str:
    """纯函数：近期超配额收束句（count+1 > max_repeat）+ 句式配额 -> 分节文本。
    recent_endings 为 None/[] 且无 syntax_patterns -> ""（不占位）。
    上限护栏：收束句最多列 5 条（按次数降序），防分节膨胀。"""

def _style_taboos_block(style_taboos: str) -> str:
    """空串不占位（_recent_human_block 同款先例）。"""
```

`writer_system` 增第 7 参 `style_taboos: str = ""`（既有调用零改动），分节落在【近期人工正文】之后：

```
【近期文风禁则】（以下收束句/句式近期已重复使用，本章禁止再用或按配额限量）
- 收束句「风很轻」：最近10章已用3次，本章结尾禁止再用
- 句式模板「像一个人……」：每章最多1次，超出会被打回修改
```

`_writer` 构造 system 时传参（仅 writer，C10）。`状态` 命令（`cli.py` `_do_status`）增一行（C12）：

```
跨章禁则：参照最近 10 章 · 禁用收束句 2 条 · 句式配额 2 条（或「未配置」）
```

### 3.5 风格体检（checker.py 纯函数 + cli 命令）

```python
def scan_style_report(
    dir_path: Path,
    rules: dict,
) -> dict:
    """递归扫描 .md/.txt（rglob，含子目录=分卷），纯函数：
    {
      "endings":  [{"ending": "风很轻", "count": 79, "files": [...]}],   # count >= max_repeat+1，降序
      "patterns": [{"pattern": "像一个人", "total": 11,
                    "over": [{"file": ..., "count": 3}]}],              # 超配额章清单
      "sizes":    [{"group": "第一卷", "n": 60, "min": ..., "max": ...,
                    "mean": ..., "cv": ...}, ..., {"group": "全局", ...}],
      "files_scanned": 317,
    }
    字数分组按**顶层子目录**（Z3：规避中文数字卷名字典序陷阱，组内零填充章号
    字典序=章序成立）；无子目录时全归一组。
    结尾/句式统计是全局频次，不依赖顺序。规则键缺失 -> 对应节为空列表。
    """
```

- 空目录/不存在 -> `{"files_scanned": 0, ...}`，命令层提示退出（C15）。
- cli 增命令 `风格体检 [目录]`（`_do_style_scan`）：目录参数可选（相对 `novel_dir` 解析或绝对），默认 `human_text_full`；打印中文报告；**不落 run record**（Z6：诊断工具，人是标尺，同 style-loop 手动命令 D7 先例）。
- 榜单阈值：ending 用 `max_repeat+1`（未配置默认 3）；patterns 全量列出（诊断要全貌，不是拦截）。

### 3.6 双降级与留痕（C16/C17）

- 规则无 `ending` 键 -> `_build_agent` 不读文件、`recent_endings=None`、checker 跳过；无 `syntax_patterns` -> 跳过。两键全缺：`写`/`精修`/`重写` 与 style-loop 完成态逐字节一致。
- cross issues 复用 `state.issues`（problem 前缀「收束句复读：」「句式模板超配额：」自带来源标识），run record steps/final_state 天然留痕，replay/compare `.get` 容错已有（A37 同款）。

## 4. 不动清单（防漂移）

- 流水线拓扑与 agents_map（writer/polisher/checker/reviewer/fixer 零增删）。
- `run_checks` 五项检查与 `ai_flavor_score` 三组件公式（只追加不修改）。
- `_fixer` / `_fix_spans` / deai_refine 的对外行为（cross issue 只是新顾客）。
- 滚动注入（`load_recent_human`）、exemplar 精选与样文路由。
- evaluate / 门禁 / 回测（harness 全部不动；体检是独立新命令）。
- `改` 命令交互、LLM 配置面、温度/max_tokens 既有值。
- run record 既有键（无新字段）。

## 5. env 变量表（零新增）

本 feature 全部配置走 `质量规则.json` 两新键（§2）。`.env copy.example` 不动；P1 的 jitter 若立项再补注释段。

## 6. 实现注意（坑位）

- **零宽正则**：`compile_syntax_patterns` 必须拒收（`pat.search("")` 真即拒），否则 findall 计数爆炸且难定位（用户配 `(像|仿佛)?` 这类模式会踩）。
- **捕获组**：pattern 含组时用 `match.group(0)` 定位句；纯字符串 pattern（如「像一个人」）无组，`re.findall` 返回字符串列表——统一 `re.finditer` 取 `group(0)` 计数，规避两种返回形态分叉。
- **跨句命中的 quote 定位**（真车 refine_20260919_201749 踩坑）：pattern 如「不是X，是Y」允许 `[。，]` 后接 `[^。]{0,4}`，会命中跨句串「不是拨。\\n\\n是」——group(0) 含句号换行，不落在任何单句内，`_first_sentence_with` 兜底返回命中串本身 -> fixer 段落定位失败 -> 整文降级 -> 4 轮不收敛烧到 review_count 上限。修复：quote 改按**命中起点所在句**定位（`_sentence_at`），单句必为原文子串且不含段落边界，段落级修复每轮可达（命中 4->3->…收敛）。
- **章号重复文件**：`save_chapter` 平铺模式同名追加 `-run_id` 后缀保留历史（`storage.py:262-263`），参照章不去重（D8：旧版结尾也算「用过」，防复读优先于防误伤）；volume-align 模式直接覆盖（`storage.py:244-255`），无重复文件问题。
- **`_build_agent` 读文件耗时**：lookback ≤ 10 个小文件，秒级；`去AI` 命令复用 `_build_agent` 时也读（可接受，读文件无副作用）。
- **fixer 修结尾行**：quote=结尾行是末段子串，`split_paragraphs` 命中末段；fixer prompt「只改问题处」已覆盖；字数保护已有。改后新结尾复检 vs 同一 `recent_endings` 快照（agent 构造时捕获）——语义正确：参照系就是写入时的近期历史。
- **句式超配额的收敛节奏**：C3 每 pattern 发 1 条 issue（quote=首个命中句），fixer 段落级修复一轮只改一个命中点——命中 n 次超配额 k 时最多烧 n-k 轮 review_count 才收敛（C8 共享预算）。行为可接受（配额默认 1、命中通常 2-3 次），若真车数据出现多轮打回，再议「按超配额数发多条 issue」的增强。
- **测试缝**：cross 检查测试用 tmp 目录写假章节文件驱动 `load_recent_endings`；`_checker` 级测试直接注入 `recent_endings` 列表，不碰文件系统。
- **体检递归**：`rglob` 会扫到 `.agent/`（在 novel_dir 下但体检默认目录是 human_text，不含 .agent）；若用户把目录指到 novel_dir 根，忽略 `.agent`/隐藏目录（`p.parts` 含 `.agent` 或 `.` 前缀目录即跳过）。
- **跨卷章序解析**（Z7）：`第X卷/部/册` 中文数字转换（一~百、组合如「二十三」）与纯数字目录名三态都要测；章号取文件名尾部 `-0*(\d+)`——规范命名已拍板为 `{卷}-{NN}.md`（阶段 1.10 规划，2026-09-04），新章与存量同构，此解析为主路径。注意 `parse_chapter_file`（`storage.py:168`）的 `第N章-` 前缀约定不匹配该命名——1.10 会在 `storage.py` 侧兼容两格式（服务工作记忆更新），本 feature 的 Z7 解析器独立实现（服务跨卷排序），职责不混。

## 7. 测试策略（全程不联网）

- **test_checker.py 追加**：`extract_ending` 边界（末行是分隔线/标题/引号行/空文）；`normalize_ending`（全半角标点、多标点尾缀、引号结尾）；`load_recent_endings`（尾部 N、字典序、不可读跳过、空目录 []）；`compile_syntax_patterns`（非法正则 RuntimeError、零宽拒收、键缺失 []）；`run_cross_checks` 命中/不误伤（次数恰等于 max_repeat 不报）/None 跳过/两键缺省全跳过/quote 为原文子串；`scan_style_report`（分卷分组、cv 计算、空目录、`.agent` 忽略）。
- **test_agent.py 追加**：`_checker` 合并 cross issues 并打回 fixer（FakeLLM 脚本含修复输出）；cross 打回共享 review_count（连续打回达上限放行）；`recent_endings=None` 时零行为变更；fixer 修复结尾行后复检通过（新结尾不在参照集）。
- **test_prompts.py 追加**：`build_style_taboos` 确定性、空输入空串、5 条上限护栏、分节文案含「禁」语义；`writer_system` 第 7 参空串时输出与既有用例逐字节一致。
- **test_cli_write.py 追加**：`风格体检` 命令冒烟（tmp 目录 + monkeypatch 打印缝）；`状态` 命令含禁则行。
- **回归**：`cli/` 下 `python -m pytest tests/ -q`；基线 566 passed / 0 failed / 1 deselected（2026-09-06），验收口径为保持全绿。测试分工按宪法 §8 两步走：AI 只跑纯逻辑最小验证脚本（checker/prompts 层直接 import + assert，跑一次即收），全量回归由用户在 IDE 终端执行。

## 8. 决策表

### 8.1 设计决策（本 design 拍板）

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 参照系载体 | a) 持久账本 `.agent/style_ledger.json`；b) 现算读章节文件 | **b** | 零状态同步问题（重写/去AI/手改后天然最新）；章节文件是唯一真源（宪法 §3 精神）；lookback≤10 读取消耗可忽略 |
| D2 | 结尾比对口径 | a) 归一化完全相等；b) 编辑距离/子串 | **a** | 确定性、零依赖；子串会把超短结尾全灭，误伤不可控 |
| D3 | 句式模板载体 | a) 代码内置；b) `质量规则.json` 正则列表 | **b** | 模板随小说走（宪法 §1）；blacklist 先例已验证 JSON 词表模式 |
| D4 | cross 检查接入点 | a) 新第六角色；b) 并入既有 `_checker` | **b** | 零拓扑改动；fixer 打回-复检闭环白拿（quote 可定位是关键前提） |
| D5 | 禁则注入范围 | 仅 writer / 全角色 | **仅 writer** | 定调归 writer（style-loop B5 同哲学）；polisher 润色不动调、reviewer 尺度要稳 |
| D6 | 参照章与体检的数据源 | a) `chapter_path`（CLI 产出史）；b) `human_text_full`（人工正文目录，递归） | **b** | 实测工作流：AI 初稿直接写进 `正文/第X卷/` 原位精修，初稿与定稿同目录演化，`chapter_path` 在该工作流为空；参照集与滚动注入/体检同源，精修后的章天然进参照集（禁则学最新文风），改 `NOVEL_HUMAN_TEXT` 一处全生效 |
| D7 | 字数方差处理 | a) 进 checker 拦截；b) 只进体检报告 | **b** | 单章无法归因（fixer 修不了「太均匀」）；生成期 jitter 归 P1 校准后议 |
| D8 | 参照章含同名旧版 | a) 按章号去重取最新；b) 不去重 | **b** | 「用过就算」防复读优先；去重需解析章号且弃用版语义不明（可能都是候选） |
| D9 | 体检落 record | a) 轻量 record；b) 不落 | **b** | 诊断工具人是标尺（style-loop D7 同款拍板）；报告输出即产物 |

### 8.2 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | `min_chars` 默认 3 | 「风很轻」3 字在网内；「挨着」2 字豁免——超短结尾的重复容忍度高于完整句 |
| Z2 | 零宽 pattern 加载期拒收 | findall 对零宽模式计数爆炸，且用户无感知；fail-fast 最安全（A23 同哲学） |
| Z3 | 体检字数按顶层子目录分组 | 中文数字卷名（一 U+4E00 / 三 U+4E09 / 二 U+4E8C）字典序≠卷序，分组规避排序依赖；组内零填充章号字典序=章序成立 |
| Z4 | pattern 预编译在加载点（`_build_agent`） | RuntimeError 落点同 A23（命令层捕获不崩 REPL）；运行期零重复编译 |
| Z5 | `re.finditer` + `group(0)` 统一计数 | findall 对含组/不含组 pattern 返回形态分叉，finditer 规避 |
| Z6 | 体检忽略 `.agent` 与点前缀目录 | 用户把目录指到 novel_dir 根时不扫运行时数据 |
| Z7 | 跨卷章序 = 卷名数字解析 + 文件名尾部数字 | 实测布局分卷编号每卷重启（第一卷-01…60 / 第二卷-01…），纯字典序跨卷必错（一 U+4E00 < 三 U+4E09 < 二 U+4E8C，「第二卷」会排在「第三卷」后）；卷尾→卷首恰是复读最该防的位置。解析失败回退字典序排后，确定性优先 |
| Z8 | 精修/重写/去AI 时 exclude 被处理文件 | 被精修的章既是「本章」又在参照窗内，count+1 口径下等于自比双计、阈值实际 -1；exclude 一个参数解决 |

## 9. 已知局限（接受，不修）

- 归一化相等抓不住变体复读（「风很轻」vs「风很轻，像没听见」）——变体检测是语义问题，归 reviewer/未来；完全相等已覆盖实测主要失效（79 次原样复读）。
- 句式模板靠用户配置正则，初始词表需要人工归纳（本 feature 附带从复盘语料提炼的起步模板，见 tasks T2 验证）。
- `ending` 检查只看最后非空行；多段式结尾（最后两三行合谋复读）抓不住——先上线看回测数据。
- 参照集 = `human_text`（D6，与实测工作流对齐）；若用户坚持把 AI 初稿单独放 `chapter_path` 不入正文，初稿结尾不在参照集内——分离用法留待数据说话，届时再加 `NOVEL_STYLE_REF` 覆盖项。
- 卷名解析失败的目录回退字典序排后：非「第X卷/部/册」与纯数字命名的卷目录，跨卷顺序可能不对——命名约定写进操作手册；解析器覆盖中文数字（一~百）与阿拉伯数字。
- 字数均一只能诊断（体检报告），生成期治疗（jitter）归 P1 且需真车验证对质量门禁的扰动。
