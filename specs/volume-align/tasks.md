# 卷对齐落盘（volume-align）- 任务分解

> 对应需求：`requirements.md`（V1-V8）；详细设计：`design.md`（D1-D5/Z1-Z2）。
> 回归基线：`cli/` 下 `python -m pytest tests/ -q` = **537 passed / 0 failed /
> 1 deselected**（2026-09-05 实测，527 基线 + 10 条新增全绿），零既有用例修改。
> 行号锚点基于 2026-09-05 代码（character-arc 完成态），实现时以函数名为准。

## P0

- [x] **T1 config.py：NOVEL_VOLUME_ALIGN 开关**
  改动：Settings 增 `volume_align: bool = False`（env `NOVEL_VOLUME_ALIGN`，
  `!=0` 开，Z1 opt-in）；`get_settings` 接线（int 解析对齐既有开关先例）。
  验证：test_config.py 新增--默认 False、`=1` 解析 True、`=0` 解析 False。V5/Z1。

- [ ] **T2 storage.py：save_chapter 对齐分支**
  改动：`save_chapter`（`storage.py:218`）在 num 可解析且 `settings.volume_align`
  时走 design §3.1 分支--卷名 = `Path(settings.chapter_subdir).name`、路径
  `{卷名}-{num:02d}.md`、头行 `## 第{cn_numeral(num)}章 {title}`（越界回落
  阿拉伯）、`_strip_leading_title` 剥模型头行、**直接覆盖不加后缀**；num=None
  或开关关走现状路径零改动。
  验证：test_storage.py 新增--对齐落盘（文件名/路径/头行/剥重）、覆盖（预置
  旧稿被替换 + 目录内仅 1 个 md）、番外回落 run_id 命名、>99 阿拉伯头行、
  开关关现状命名。V1-V5。

- [ ] **T3 storage.py：parse_chapter_file 卷模式**
  改动：新增 `_VOLUME_FILE_RE = r"^(.+?)-(\d{1,4})$"`（懒匹配锚定结尾），
  判定序在既有「第N章-标题」格式之后（D5）；卷格式返回 `(NN, "")`。
  验证：test_storage.py 新增--`第一卷-38.md` -> (38, "")、`第一卷-05.md` ->
  (5, "")、`第05章-标题2.md` -> (5, "标题2")（既有格式优先不误判）、
  不匹配回落 (None, stem)。V6。

- [ ] **T4 test_cli_write.py：集成两例**
  改动：无产品代码（消费 save_chapter 返回路径自然继承）；新增用例--对齐
  模式（`dataclasses.replace(tmp_settings, volume_align=True,
  chapter_subdir="正文/第一卷")`）下 `_do_write` 章节落 `正文/第一卷/第一卷-38.md`
  且头行 `## 第三十八章 空`；预置人工原稿被同文件覆盖（目录内仅 1 个 md，
  RAG add_document 收到卷路径）。
  验证：两用例绿。V1/V3/V8。

- [x] **T5 `.env copy.example`：卷对齐注释段**
  改动：追加「卷对齐落盘（volume-align）」段--开关用法、前提（subdir 指到
  当前卷目录）、行为（文件名/头行/直接覆盖 + git diff 工作流一句）、换卷
  工作流（改 subdir + NOVEL_HUMAN_TEXT 指未重写卷 + 删 working_memory.json）、
  自我污染警示。
  验证：人工核对与 design §2/§4 一致。V7。

## P1（依赖真实运行数据，非阻塞）

- [x] **T6 精修/重写/去AI 对卷文件的头行保真验证**：2026-09-05 真车重写
  `第一卷-40.md` 验证通过——重写差异 diff 从第 2 行起，头行
  `## 第四十章 门缝` 原样保留（意外提前收口）。
- [ ] **T7 卷前缀章号**：跨卷撞号若真车痛感强（换卷忘重置 wm 导致伏笔/弧光
  被误抹），再议章号带卷前缀（如 "一-38"）的 schema 改造。

## 验收映射

| 验收项 | 承载任务 |
|---|---|
| V1/V2 路径/命名/头行 | T2、T4 |
| V3 覆盖 | T2、T4 |
| V4 番外回落 | T2 |
| V5 开关关闭零变化 | T1、T2 |
| V6 parse_chapter_file | T3 |
| V7 可发现性 | T5 |
| V8 兼容 | T2、T4（RAG upsert 由既有 id 方案天然保证） |
| 回归基线 | 每任务完成即跑相关测试，T5 后全量（527 基线零新增） |
