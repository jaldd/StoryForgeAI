# 任务分解：阶段 0 小项批（stage0-batch）

> Feature: `stage0-batch`
> 对应 `requirements.md` / `design.md`。按 0.1 -> 0.2 -> 0.3 -> 0.5 -> 0.6 顺序实施，每项完成即勾选。
> 宪法合规：依赖注入可测（§5）、存储路径约定不变（§3）、无新依赖（§2）、零小说名（§1）。

---

## 0.1 审稿解析失败不再静默放行

- [x] `agent.py` `parse_review` 兜底分支：不可解析返回 `(None, ...)`；「不通过」启发式保留为 False
- [x] `agent.py` `_reviewer`：`passed is None` 分支--显著警告（控制台 + log）+ 人工确认（存定稿 / 弃不定稿），两者皆留痕
- [x] `NovelAgent.__init__` 加 `review_confirm` 注入位（None=REPL 交互 input；EOF/Ctrl-C 视为弃）
- [x] `max_reviews` 强制定稿分支补控制台 ⚠️ 警告（log 已有）
- [x] 更新 `test_parse_review_fallback_true`（旧期望即本项要消灭的 fail-open 行为）
- [x] 新增用例：FakeLLM 返回散文审稿 -> 不静默过审、confirm 被询问、y 定稿留痕、n 不定稿、注入 confirm 恒弃（fail-closed）、强制定稿警告
- **验证**：`pytest tests/test_agent.py -k "parse_review or review"` 全绿（11 passed）；全量 3 failed, 126 passed，无新增失败

## 0.2 铁律外置到 NOVEL_DIR

- [x] `config.py`：`rules_subpath` 字段 + `NOVEL_RULES` env + `rules_full` 属性
- [x] `prompts.py`：删 `RULES` 常量；`_rules_block` 注入函数；三个 system prompt 加 `rules` 尾参；polisher/reviewer/EVALUATOR_RUBRIC 去小说专属文案
- [x] `agent.py`：`NovelAgent` 加 `rules` 参数，四处 system 构造传入；`_writer` 删「不要解释风代表什么」
- [x] `cli.py`：`_build_agent` 读铁律文件（utf-8）注入
- [x] `.env copy.example` 补 `NOVEL_RULES` 条目
- [x] 清理 `cli/` 全部「云依」：产品代码（prompts/rag docstring）、测试 fixture（conftest/test_agent/test_cli_partial/test_rag 改虚构名）、`操作手册.md`
- [x] 新增用例：铁律文件内容逐字出现在三处 system prompt；铁律缺失时不出现占位块；`rules_full` 路径解析
- **验证**：`grep 云依 cli/` 零命中；相关用例全绿（全量 3 failed, 130 passed，无新增失败）

## 0.3 写完自动入库

- [x] `cli.py` `_do_write`：存章节后 `rag.add_document(str(chapter_file))`（失败不阻断）
- [x] 新增用例：`_do_write` 后 FakeRag.add_calls 含章节文件（绝对路径）；章节块 metadata type=chapter 回归（既有 `test_add_document_ignores_exclude` 覆盖）
- **验证**：`pytest tests/test_cli_write.py` 全绿（3 passed）

## 0.5 exemplar 语料目录化

- [x] `config.py`：`exemplar_subpath` 默认改目录级 `"文风基准"`（env 同步）
- [x] `prompts.py`：`load_exemplar` 目录级（兼容单文件）+ `EXEMPLAR_MAX_CHARS` 截断日志 + `exemplar_info`
- [x] `cli.py`：`_build_agent` 判断 `.exists()`；`_do_status` 输出文件数/总字数
- [x] 新增用例：目录 2 文件都读入且有序；单文件兼容；超限截断 + 日志；状态命令输出清单
- **验证**：`pytest tests/test_prompts_exemplar.py tests/test_cli_write.py tests/test_config.py` 18 passed（2 failed 为存量 `test_runtime_dir_override`/`test_defaults`）；`_build_agent` 目录注入有独立用例

## 0.6 rebuild 陈块精确清理

- [x] `rag.py`：manifest 读写（`chroma_path/rebuild_manifest.json`，损坏容错为空）；`build_index` 先按上次 manifest 精确删再 upsert，末尾写新 manifest
- [x] 新增用例：删设定文件后 rebuild 该 source 块数 0；章节块数不变；首建（无 manifest）不清理；manifest 损坏不阻断
- **验证**：`pytest tests/test_rag.py` 全绿（14 passed）

---

## 全量回归与验收

- [x] 每项完成后 `cd cli && PYTHONPATH=.deps python -m pytest` 全量：146 passed，仅存量 3 failed（`test_strip_polisher_meta` / `test_runtime_dir_override` / `test_defaults`），新增失败 0
- [x] `grep 云依 cli/` 零命中（§1）
- [x] 验收对照表（requirements A1-A22 -> tasks）逐项核对

## 留给人工（真实环境）

- [ ] 真实 NOVEL_DIR 下放 `写作铁律.md`（内容自定）写一章，核对铁律注入效果（A9）
- [ ] 真实文风基准目录核对文件数/体积，确认 `EXEMPLAR_MAX_CHARS=30000` 是否合适（A17）
- [ ] 真实目录删一个设定文件 + `index rebuild`，核对陈块清零（A20）

| 验收 | 覆盖任务 |
|------|----------|
| A1-A6 | 0.1 |
| A7-A11 | 0.2 |
| A12-A14 | 0.3 |
| A15-A18 | 0.5 |
| A19-A22 | 0.6 |
