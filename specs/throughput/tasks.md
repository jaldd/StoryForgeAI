# 阶段 2：吞吐（throughput）- 任务分解

> 对应需求：`requirements.md`（T1-T29）；详细设计：`design.md`（D1-D12/Z1-Z8）。
> 任务编号用 W 系列（T 已被本 feature 需求条目占用，避免撞号；
> quality-gate/style-loop 的任务用 T 是因其需求条目分别为 A/B）。
> 开工前状态：quality-gate + style-loop 均已实现（397 passed 基线）；
> style-loop 真车验收由用户执行中，不阻塞。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` =
> **397 passed / 0 failed / 1 deselected**（2026-08-30 实测），零新增失败。
> 收口实测（2026-08-31）：**461 passed / 0 failed / 1 deselected**（W1-W7 全量，零新增失败）。
> 真车验收（2026-09-06）：**批量连写通过**——`写第42-44章` 实跑第 42/43 章
> （第 44 章用户主动 n 停止，停止路径同验）：每章 planner→writer→polisher→reviewer
> 全链路、章间 y/n 确认、伏笔计数连续（42 章后未回收 7 → 43 章后 9）、
> 弧光逐章更新、每章入库 6 块；章间连续性内容层证实（43 章节拍消费 42 章
> 新埋的「按住风未说出口」伏笔，评委理由「速写本上的风旋延续控风暧昧线」）。
> 流式真车（Z1）同轮通过：NOVEL_STREAM=1 下 writer/polisher 流式输出正常、
> 审稿/评测/抽取非流式正常。W8-W11 留 P1。
> 行号锚点基于 2026-08-30 代码（style-loop 完成态），实现时以函数名为准。

## P0

- [x] **W1 config.py：流式/批量/章纲配置**
  改动：Settings（`config.py:53`）增 `stream: bool = True`（env `NOVEL_STREAM`，
  0 = 关）、`batch_max: int = 10`（env `NOVEL_BATCH_MAX`）与
  `chapter_plan_subpath: str = "每章.md"`（env `NOVEL_CHAPTER_PLAN`，留空 = 禁用）
  + `plan_full` 路径属性（同 `rules_full` 先例）；`get_settings`（`config.py:214`）
  接线（stream 用 `int(...) != 0`）。
  验证：test_config.py 新增--三变量默认值（stream=True/batch_max=10/
  chapter_plan_subpath="每章.md"）、setenv 覆盖、`NOVEL_STREAM=0` 解析为
  False、`NOVEL_CHAPTER_PLAN=""` 解析为空串。T26。

- [x] **W2 llm.py：ThinkFilter 增量过滤 + chat 的 on_delta 流式路径**
  改动：新增 `_ThinkFilter` 类（design §3.2：feed/flush、完整对剥离、未闭合
  前缀扣住、尾部 hold-back 防 `</th`+`ink>` 跨 chunk 截断）；`chat`
  （`llm.py:154`）增 `on_delta: Optional[Callable[[str], None]] = None` 参数，
  非空时请求 `stream=True`，逐 chunk：空 choices 跳过、`delta.content` 经
  ThinkFilter 后回调、`reasoning_content` 只累积（Z2）；末 chunk 的
  finish_reason 参与空回翻倍判定（翻倍整请求重试）；中途异常丢弃增量整请求
  退避重试；temp 400 锁定同路生效；返回值 = 收完组装 + `_strip_think_blocks`
  收尾（数据侧与非流式同源）。`on_delta=None` 时请求体不带 `stream` 键
  （现状逐字节回归）。
  **真车门槛（Z1 风险缓解，W2 完成即做、用户执行）**：`NOVEL_STREAM=1`
  真车冒烟一章，确认 ark 网关流式形态（reasoning_content 增量、末块
  finish_reason、空回翻倍路径可触发）；不兼容则 `NOVEL_STREAM=0` 兜底回退
  现状，兼容问题回填 `_chat_stream` 的 getattr 容错后重测。
  验证：test_llm.py 新增--ThinkFilter 纯逻辑五态（完整对/未闭合/跨 chunk 标签/
  纯思考流/无思考直通）；流式路径用 FakeStream（chunk 迭代器）：正常流、
  含思考块流、空流+length+reasoning 翻倍重试、中途异常退避重试、finish_reason
  仅末 chunk；非流式请求体断言无 stream 键。T1-T5/T8/T10。

- [x] **W3 agent.py + state.py + cli.py：流式接线 + 规划注入**
  改动：`NovelAgent.__init__`（`agent.py:250`）增 `stream: bool = False` 参数；
  新增 `_print_delta`（print end="" flush=True）；`_writer`（`agent.py:356`）与
  `_polisher`（`agent.py:395`）的 chat 调用追加
  `on_delta=self._print_delta if self.stream else None`，stream 为真时角色头
  文案改「（流式）」并前后换行；`cli._build_agent`（`cli.py:134`）注入
  `stream=settings.stream`。规划注入：`state.py` 的 `PipelineState` 增
  `plan: str = ""` 字段；`agent.run`（`agent.py:824`）增 `plan: str = ""` 参数
  传入 PipelineState；`_writer` user_msg（两分支）追加【本章规划】块（空串
  不占位，design §4.2 文案）。
  验证：test_agent.py 新增--stream=True 时 **kw 捕获到 on_delta 且非 None、
  FakeLLM 分片返回时 === 分离/_strip_polisher_meta/字数保护结果与非流式一致；
  默认构造（stream 缺省）时 on_delta 键在、值为 None（与 D4 接线形态一致，
  既有用例天然回归）；
  `run(task, plan=...)` 时 state.plan 进 record、_writer 的 user_msg 含
  【本章规划】块、空 plan 不占位。T6/T9/T12。

- [x] **W4 storage.py：区间解析 + 章纲解析 + 中文序数纯函数**
  改动：新增 `parse_chapter_range(task)`（标题可选：`写第5-10章` /
  `写第5-10章：模板`，分隔符 `-`/`-`/`~`/`至`）、`parse_chapter_plan(text)`
  （markdown 全表格扫描合并：列头兼容 标题/暂定标题、分隔行/脏行跳过、
  notes = (列名, 值) 对、同章号后者覆盖 Z7）、`cn_numeral(n)`（1-99，越界
  ValueError，Z6）；`__all__` 增名。
  验证：storage 侧测试--parse_chapter_range 命中（带/不带标题）/不命中
  （单章命令不匹配）/分隔符变体；parse_chapter_plan 用构造 markdown 断言
  （多表格合并、列头变体暂定标题、---行跳过、首列非章号行跳过、同章号
  后者覆盖、notes 列名值对完整）；cn_numeral 1/2/10/11/20/21/99 抽查 +
  0/-1 抛错。T11/T16 + T13 回落基座。

- [x] **W5 cli.py：_do_write 拆层 _write_one + 规划透传 + 打断语义**
  改动：`_do_write`（`cli.py:266-358`）主体改名
  `_write_one(task, settings, plan: str = "") -> str` 返回结局（saved/
  rejected/failed/interrupted，design §4.3 表）；`agent.run` 改传
  `plan=plan`；**`_write_one` 最外层包 `except KeyboardInterrupt`**
  （design §3.4 修订：覆盖流式/评测/存盘全部阶段，打印已打断、
  return "interrupted"、不存盘不更新 wm；`_gate_confirm`/`_confirm_unparseable`
  内已消化的 "n" 语义不受影响）；`_do_write` 变薄壳调它
  （对外行为 = 现状 + plan 透传）。新增 `_load_chapter_plan(settings)`
  （读 `settings.plan_full` + `parse_chapter_plan`，未配置/不存在返回 {}，
  静默降级）与 `_render_notes(entry)`（(列名,值) 对 -> 「列名：值」逐行）。
  验证：test_cli_write.py 新增--monkeypatch agent.run 抛 KeyboardInterrupt ->
  返回 interrupted 且无 save_chapter/wm 更新；四种结局各自返回值正确；
  既有 _do_write 全部用例零改动保持绿（拆层回归护栏）。T7/T17/T27。

- [x] **W6 cli.py：_do_write_batch + REPL 分发 + 单章无标题增强**
  改动：新增 `_do_write_batch(task, settings, auto)`（design §4.4 骨架全量
  落地：校验起>止/超 batch_max 报错零调用、无标题主路径缺章报错零调用 T14、
  带模板回落序数后缀且章纲照注入 T13、预算提示 T24、逐章 `[批量 i/n]` 头、
  默认章间 `_gate_confirm` y/n T18、--auto rejected/failed/interrupted 中断
  T19/T20/T22、单章区间退化 T25）；主循环（`cli.py:1015`）startswith("写")
  分支按 design §4.1 分发序（剥 --auto -> 区间 -> 单章无标题查章纲 -> 现状
  `_do_write`），单章无标题形态构造 `写第N章：{章纲标题}` + plan 进
  `_do_write`（T15）；`_print_help` 增区间写命令行（含章纲说明）。
  验证：test_cli_write.py 新增--无标题主路径（章纲供标题+规划、任务串与
  plan 注入正确、章间 wm.current_chapter 递增、每章 rag.add_document 各一次
  T21）、缺章报错零调用、带模板回落（序数后缀 + 有章纲章规划照注入）、
  默认模式 y 连写/n 停止（第二章零调用）、--auto 门禁弃中断（后续章零调用）、
  failed/interrupted 中断、起>止/跨度超限报错零调用、单章无标题命令走章纲、
  `写第5章：标题` 不进批量且无章纲时零变化（分发断言）。
  测试缝：FakeAgent/monkeypatch `_write_one` 返回值 + `_gate_confirm` 替换，
  与既有批量无关用例同模式。T11/T13/T14/T15/T17-T25。

- [x] **W7 `.env copy.example` + 早期规划：配置注释与状态更新**
  改动：追加「吞吐（2.1/2.2）」注释段--`NOVEL_STREAM`（默认 1，0=关，
  含「writer/polisher 专属」说明）、`NOVEL_BATCH_MAX`（默认 10）、
  `NOVEL_CHAPTER_PLAN`（默认 每章.md，留空禁用，含章纲表格格式说明：
  章 | 标题 | 核心事件 | …）、区间命令与 `--auto` 用法一句（含 fail-closed
  语义提示）；早期规划阶段 2 状态行更新（实现完成、真车验收待跑）。
  验证：人工核对注释与 design §2 配置表逐行一致。T24/T28。

## P1（依赖真实运行数据，非阻塞）

- [ ] **W8 流式体验校准**：真车取数后校准首 chunk 前提示文案、重试提示的
  降噪（翻倍重试时已打印内容的清屏/分隔处理）、增量打印的 flush 节奏
  （是否需要按块聚合降低 syscall）。
- [ ] **W9 --auto 低分章隔离方案重估**：批量真车数据说话后重启 design D9
  备选（隔离待审清单），需先回答「隔离章是否参与后续连续性」的两难；
  与 quality-gate T12 门禁阈值校准同批做（早期规划的「阶段 2 批量
  开闸前复核一次」即指此）。
- [ ] **W10 规划喂 reviewer 作验收基准**：D12 备选--reviewer 拿【本章规划】
  验收「是否按规划写」（对齐 0.8 构思喂 reviewer 的先例）；待批量真车
  观察规划遵循度后再议。
- [ ] **W11 标题显式列表语法**：若模板回落场景实际高频，再议
  `写第5-7章：标题一|标题二|标题三`（D6 旧备选，章纲主路径下优先级很低）。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| T1/T8/T10 流式接口与提示、非流式回归 | W2 |
| T2-T3 思考块双路兜底（打印过滤 + reasoning 字段） | W2 |
| T4-T5 空回翻倍/退避/temp 锁定流式适配 | W2 |
| T6/T9 流式范围与后处理不变 | W3 |
| T7 Ctrl-C 打断 | W5 |
| T11 区间解析（无标题主路径） | W4、W6 |
| T12 规划注入 writer + record 留痕 | W3、W5 |
| T13 带模板回落（序数后缀 + 规划照注入） | W4、W6 |
| T14 缺章/未配置报错与回落 | W6 |
| T15 单章无标题走章纲 | W6 |
| T16 章纲解析兼容性 | W4 |
| T17/T27 单章复用与零行为变化 | W5、W6 |
| T18 默认章间确认 | W6 |
| T19 --auto fail-closed | W6 |
| T20/T22 失败与打断中断 | W5、W6 |
| T21 章间连续性 | W6 |
| T23 非法区间护栏 | W6 |
| T24 预算提示 | W6、W7 |
| T25 单章退化 | W6 |
| T26 配置默认值 | W1 |
| T28 可发现性 | W7 |
| T29 回归基线 | 全部任务收口（每 W 完成即跑相关测试，W6 后全量） |
