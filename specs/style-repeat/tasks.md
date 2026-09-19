# 阶段 1 续：文风复读防治（style-repeat）- 任务分解

前置：design.md 已定稿（D1-D9 / Z1-Z8 拍板口径）。
约定：每个任务单文件单职责；全程测试不联网（tmp 目录 + FakeLLM + monkeypatch）。
全量回归命令（在 `cli/` 下）：`python -m pytest tests/ -q`。
基线：628 passed / 0 failed / 1 deselected（2026-09-19，style-repeat 完成态 = 566 + 53 新增 + 真车修复 9），验收口径为**保持全绿**。
测试分工（宪法 §8）：AI 只跑纯逻辑最小验证脚本（checker/prompts 层直接 import + assert，跑一次即收）；全量回归由用户在 IDE 终端执行，贴回结果再继续。
实施顺序即依赖顺序：T1 -> T2 -> T3 -> T4 -> T5 -> T6。

## P0（实现主干）

- [x] **T1 checker.py：指纹纯函数**
  改动：追加 `extract_ending`（最后一个非空行，跳 `---`/`***`/`#` 行，空文返 ""）、
  `normalize_ending`（strip + 循环去句末标点尾缀 `_SENT_STRIP` + 再 strip）、
  `load_recent_endings(dir_path, lookback, exclude=None)`（人工正文目录**递归**收集 .md，
  忽略点前缀目录与 .agent；跨卷章序排序（Z7）：卷序 = 目录名解析「第X卷/部/册」中文或
  阿拉伯数字（失败回退字典序排后），章序 = 文件名尾部 `-0*(\d+)`（无数字回退字典序）；
  取尾部 lookback 个的归一化结尾；exclude 排除被精修/重写/去AI 处理中的文件自身（C18）；
  目录不存在/无文件 -> []；不可读跳过）、
  `compile_syntax_patterns(rules)`（预编译；非法正则或 `pat.search("")` 命中零宽 ->
  RuntimeError 含 pattern 原文，C4；键缺失 -> []）。
  `__all__` 增四个名。
  验证：test_checker.py 追加--extract_ending 四边界（分隔线结尾/标题结尾/引号行/空文）；
  normalize_ending（全半角、多标点尾缀「。。。」「？！」、引号结尾）；load_recent_endings
  （tmp 目录写假章、尾部 N、**跨卷排序三态**（中文数字卷名如「第一卷/第二卷/第三卷」乱序
  放置/纯数字目录/不可解析回退排后）、exclude 生效（C18）、不可读文件跳过、空目录 []）；
  compile 三态（非法 /
  零宽拒收 / 缺键 []）。C2、C4、C7。

- [x] **T2 checker.py：run_cross_checks**
  改动：追加 `run_cross_checks(text, recent_endings, rules) -> list[dict]`，两项：ending
  （`normalize_ending(extract_ending(text))` 长度 >= min_chars 且 `recent_endings.count(mine)+1
  > max_repeat` -> issue，quote=结尾行原文截 50）；syntax_patterns（`re.finditer` +
  `group(0)` 计数 > max_per_chapter -> issue，quote=首个命中句截 50，句定位复用
  `split_sentences` 含 `match.group(0)` 的首句）。issue 与 run_checks 同构
  `{quote, problem, fix}`，problem 前缀「收束句复读：」「句式模板超配额：」（来源标识，
  C17 天然留痕）。recent_endings 为 None/[] -> ending 项跳过；键缺失 -> 对应项跳过。
  验证：test_checker.py 追加--ending 命中 / 次数恰等于 max_repeat 不报（不误伤）/
  min_chars 豁免（「嗯。」）/ None 与空列表跳过 / quote 为原文子串断言；syntax 命中 /
  配额边界（等于不报）/ 键缺省跳过；两键全缺返回 []。C1、C3、C5。

- [x] **T3 agent.py：_checker 接线（cross issues 进既有闭环）**
  改动：`NovelAgent.__init__` 增 `recent_endings: Optional[list[str]] = None`（注入模式同
  `recent_human` 先例；None = 跳过）。`_checker`（`agent.py:623`）：`run_checks` 之后，
  `self.quality_rules and self.recent_endings is not None` 时追加
  `run_cross_checks(state.polished, self.recent_endings, self.quality_rules)`，合并进同一
  issues 流（打回 fixer / review_count 共享 / 复检全部既有机制，零新状态）。
  验证：test_agent.py 追加--cross issue 打回 -> fixer（FakeLLM 按标记协议返回改写末段）->
  复检通过（新结尾不在参照集）；cross 打回共享 review_count（连续打回达 max_reviews
  放行留痕）；`recent_endings=None` 时 steps 与 issues 与现状一致（C16 回归护栏）；
  refine 路径 cross 同样生效（refine_agents 含 checker）。C6、C8。

- [x] **T4 prompts.py + cli.py：负面清单注入**
  改动：prompts.py 追加 `build_style_taboos(recent_endings, rules) -> str`（近期超配额收束句
  按次数降序最多 5 条 + 句式配额清单；无内容返 ""）与 `_style_taboos_block`（空不占位，
  `_recent_human_block` 同款先例）；`writer_system` 增第 7 参 `style_taboos: str = ""`，
  分节落在【近期人工正文】之后（既有调用零改动）。agent.py：`__init__` 增
  `style_taboos: str = ""`，`_writer` 构造 system 时传参（仅 writer，C10）。
  cli.py：`_build_agent` 在 exemplar/滚动加载之后，`ending` 键存在时调
  `load_recent_endings(settings.human_text_full, lookback, exclude=active_file)` +
  `build_style_taboos`，注入 agent（`_build_agent` 增可选参 `active_file`：精修/重写/去AI
  三命令传入被处理文件路径，写新章为 None，C18；既有调用点默认值零改动；
  5 个调用点：写/精修/重写/去AI/改，`compile_syntax_patterns` 在此预编译，RuntimeError
  走命令层既有捕获，Z4）；`_do_deai` 直调处（cli.py:793 附近）追加
  `run_cross_checks(content, recent_endings, rules)`（去AI 不经 agent 流水线，design §3.3
  直调例外；只取可定位 issue 同 B10 口径）；`_do_status` 增「跨章禁则」行（参照章数 /
  禁用收束句条数 / 句式配额条数或未配置，C12）。
  验证：test_prompts.py 追加--build_style_taboos 确定性（同输入两次相等）、空输入空串、
  5 条上限护栏、文案含「禁」语义；writer_system 第 7 参空串时与既有快照逐字节一致；
  test_cli_write.py 追加--_build_agent 后 writer prompt 含禁则分节（FakeLLM 捕获 system）、
  状态命令含禁则行。C9、C10、C11、C12。

- [x] **T5 checker.py + cli.py：风格体检命令**
  改动：checker.py 追加 `scan_style_report(dir_path, rules) -> dict`（递归 rglob .md/.txt，
  忽略 `.agent` 与点前缀目录，Z6；endings 全局频次榜 count >= max_repeat+1 降序含文件清单、
  patterns 总数 + 超配额章清单、sizes 按顶层子目录分组 n/min/max/mean/cv + 全局行，Z3；
  空目录 `files_scanned=0`）。cli.py 增 `风格体检 [目录]` 命令（`_do_style_scan`）：目录参数
  可选（相对 novel_dir 解析或绝对），默认 `human_text_full`；打印中文三节报告；
  不落 run record（D9）。
  验证：test_checker.py 追加--scan_style_report（tmp 造分卷目录 + 复读结尾 + 模板命中，
  断言三节形状与数值；cv 计算；`.agent` 忽略；空目录）；test_cli_write.py 追加--命令冒烟
  （tmp 目录 + 默认目录缺省两路，缺省路提示不崩，C15）；全流程零 LLM 断言（不触
  FakeLLM 调用计数）。C13、C14、C15。

- [x] **T6 设计文档同步：`.env copy.example` 无改动确认 + 规则模板**
  改动：`.env copy.example` 本 feature 零新 env（design §5），确认不动；design §2 的两键
  JSON 模板即上线模板，README 或操作手册若列质量规则键清单则同步补两键（无则跳过）。
  验证：人工核对 design §2 与文档一致。C5（可发现性配套）。

## P1（依赖真实数据，非阻塞）

- [ ] **T7 target_words 抖动（字数均一的治疗试点）**：新 env
  `NOVEL_TARGET_WORDS_JITTER_PCT`（默认 0 = 现状零行为变更）；writer/polisher 的目标字数 =
  base ± base×pct%（`random`，测试注入 seed 或 monkeypatch）；真车验证对 eval_gate 与
  checker 的扰动后再定去留。非目标 1 的闭环出口。
- [ ] **T8 阈值校准（真实语料回测）**：对实测长篇跑 `风格体检`（零 LLM、零联网），核对
  收束句榜 / 句式榜与人工复盘清单的吻合度（已知复读句应全部上榜、误报率），据此校准
  `ending.max_repeat` / `min_chars` / `syntax_patterns` 起步词表。
- [ ] **T9 freq 自相似组件（另立 feature，此处挂账）**：`ai_flavor_score` 的 freq 组件
  从「与文风基准的距离」改向「与自身最近 N 章的相似度」（自抄袭检测）——研究性变更，
  需 T8 数据与回测支撑，立项时另走 spec-kit 三件套。

## 验收对照表

| 验收项 | 承载任务 |
|---|---|
| C1-C3 跨章两项检查 | T1、T2 |
| C4 非法/零宽 pattern fail-fast | T1（拒收）、T4（加载点落位） |
| C5 键缺省跳过（不误伤） | T2、T6 |
| C6 issue 同构进 fixer 闭环 | T3 |
| C7 参照章现算加载 | T1、T4 |
| C8 共享 review_count | T3 |
| C9-C11 writer 禁则注入 | T4 |
| C12 状态命令可发现 | T4 |
| C13-C14 风格体检三节报告 | T5 |
| C15 空目录不崩 | T5 |
| C16 双降级逐字节一致 | T2、T3（None 回归护栏） |
| C17 旧记录兼容 | T2（problem 前缀）、T3（既有留痕复用） |
| C18 精修/重写/去AI 防自比 | T1（exclude 参数）、T4（active_file 接线） |

## 人工验收（对齐阶段 1.7-1.9 验收口径）

1. **真实语料体检**（T8 前置体验）：对实测长篇目录跑 `风格体检`——收束句复读榜应出现
   已知的 79 次复读句及所在章清单；句式榜应出现「像一个人」「不是X，是Y」两类模板；
   字数分布应显示实测的「45 章全落 5.8-6.0KB」那卷 cv≈0.02。三张清单与人工复盘吻合
   即体检达标；
2. **检测+预防闭环**（NOVEL_DIR 配两键后写一章）：writer prompt 含【近期文风禁则】分节；
   故意让任务诱导复用近期结尾（或临时把 max_repeat 调 0），run record 可见 checker 打回
   （problem 前缀「收束句复读」）-> fixer 改写末段 -> 复检通过链路；
3. **零配置回归**：移除两键复跑一章，行为与 style-loop 完成态一致（回归保险）；
4. `状态` 命令显示跨章禁则行；`风格体检` 指向不存在目录时提示退出不崩；
5. `cli/` 下 `python -m pytest tests/ -q` 保持全绿（619 passed / 0 failed / 1 deselected 基线，宪法 §8：用户在 IDE 终端跑）。

> 实现完成（2026-09-06）：T1-T6 全部落地，单测 53 个新增全绿（619 passed / 0 failed /
> 1 deselected）。人工验收 1-4（真实语料体检 / 检测+预防闭环 / 零配置回归 / 状态行）
> 待真车执行；T7-T9 留 P1（依赖真实数据）。

> 真车验收（2026-09-19）：**1.9 体检 + 1.7 检测闭环 + 状态行/容错 全部通过**——
> ① `风格体检 正文`（300 章）：复读榜实锤「他睡着了」×46+变体×7（第四卷 52/60 章以
> 睡着收尾）、「就够了」×33+「这就够了」×16（第五卷口癖）；句式榜「不是X，是Y」全书
> 629 次、第三卷近全卷超配额（复盘说的 79 次复读句与 cv≈0.02 均一卷未精确复现——
> 变体分流 + 语料已部分精修，工具如实报告当前语料）；② `精修 第一卷-52.md`：
> checker 打回「句式超配额命中4次」→ fixer 修复 1 段（4→3）→ 复检 → 5 次达上限
> → 强制定稿 → 审稿未通过分支正确拒绝存回（fail-safe 验证）；③ `状态` 跨章禁则行、
> `风格体检 不存在目录` 容错正常。**踩坑修复 1 个**：跨句命中（「不是拨。\\n\\n是」）
> group(0) 不落单句 → quote 不可定位 → fixer 整文降级 4 轮不收敛；quote 改按命中
> 起点所在句定位（`_sentence_at`，design §6 坑位已记），真车语料回归验证可定位。
> 另修 2 个真车暴露问题：active_file 相对路径 exclude 解析口径（按 NOVEL_DIR）、
> 新增 `index clear-chapters` 命令（清空全部正文块，手改正文后一键清陈块）。
