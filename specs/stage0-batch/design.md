# 技术设计：阶段 0 小项批（stage0-batch）

> Feature: `stage0-batch`，对应 `requirements.md`。
> 原则：每项最小改动、不动架构、依赖注入可测（宪法 §5）、存储路径约定不变（§3）。

---

## 1. 现状证据（均已核对代码）

| 项 | 位置 | 现状 |
|----|------|------|
| 0.1 | `agent.py` `parse_review` L74-77 | 兜底分支：不含「不通过」即 `return True, "（解析失败，默认通过）"`（fail-open） |
| 0.1 | `agent.py` `_reviewer` L286-293 | `max_reviews` 强制定稿只写 `state.log`，无控制台警告 |
| 0.2 | `prompts.py` `RULES` L26-34 | 8 条铁律含具体小说人物名/天气线设定 |
| 0.2 | `prompts.py` L62/L74/L93 | polisher/reviewer/EVALUATOR_RUBRIC 硬编码「男主始终用他、女主叫云依」 |
| 0.2 | `agent.py` `_writer` L226 | user 指令硬编码「不要解释风代表什么」 |
| 0.3 | `cli.py` `_do_write` L113-128 | 存章节 + 工作记忆后即止，无 `add_document` |
| 0.5 | `config.py` L47 | `exemplar_subpath="文风基准/1.txt"` 单文件 |
| 0.5 | `prompts.py` `load_exemplar` L37-39 | 单文件 `read_text`，无上限 |
| 0.6 | `rag.py` `build_index` L187-204 | 只 upsert `c0..cN`，从不删除旧块 |

## 2. 0.1 审稿解析失败不再静默放行

### 2.1 接口

```python
def parse_review(text: str) -> Tuple[Optional[bool], str]:
```

- 前三级（直接 loads / 截取 `{..}` / 补 `}`）解析成功：返回 `(bool, reason)`，行为不变。
- 第四级兜底：
  - 文本含「不通过」或 `false`：返回 `(False, text[:200])`--保守拒稿方向，保留。
  - 其余：返回 `(None, "（审稿结果不可解析）")`--**取代**「默认通过」。
- 返回 `None` = 不可解析，判定权上交（REPL 交人，未来批量交 fail-closed）。

### 2.2 `_reviewer` 处理 `None`

```
passed, reason = parse_review(result)
if passed is None:
    警告（控制台 ⚠️ + state.log，含原始返回前 200 字）
    answer = self._review_confirm(提示语)   # 注入点，见 2.3
    y -> 视为通过定稿：feedback="审稿通过（审稿结果不可解析，人工确认存稿）"，log 留痕
    n -> 不定稿：next_agent="done"，final_chapter 保持空，feedback/log 留痕
         -> cli._do_write 的既有 `if state.final_chapter:` 分支自然不存章（fail-closed）
```

- `review_count` 不递增（不可解析不构成打回循环）。
- `_reviewer` 原有的 `if "解析失败" in reason` 日志分支删除（被上面取代）。

### 2.3 确认注入（fail-closed 接口位）

```python
NovelAgent.__init__(..., review_confirm: Optional[Callable[[str], str]] = None)
```

- `None`（默认，即 REPL）：内置交互实现--`input(提示语)`；`EOFError`/`KeyboardInterrupt` 视为「弃」（保守）。
- 未来批量模式：注入 `lambda prompt: "n"` 即 fail-closed 不存盘，agent 零改动。
- 测试：注入 fake confirm 断言被询问；不注入时现有测试均返回可解析 JSON，不触发交互。

### 2.4 强制定稿逃生门（A5）

`_reviewer` 的 `max_reviews` 分支增加控制台显著警告（`⚠️ 已达打回上限…强制定稿`），log 已有、保留。

## 3. 0.2 铁律外置到 NOVEL_DIR

### 3.1 配置（config.py）

- 新字段 `rules_subpath: str = "写作铁律.md"`，env `NOVEL_RULES`（相对 novel_dir）。
- 新属性 `rules_full`（同 `instruction_full` 的写法：subpath 为空时返回 novel_path）。

### 3.2 prompts.py

- 删除 `RULES` 常量（含 `__all__` 条目）。
- 新增 `_rules_block(rules)`（模式同 `_instruction_block`）：非空时产出 `【写作铁律】（必须遵守）\n{rules}\n`。
- `writer_system / polisher_system / reviewer_system` 各加尾参 `rules: str = ""`，注入 rules 块。
- 三个 prompt 中残留的小说专属文案改为通用表述：
  - polisher 铁律 1：`只优化文字表达，严禁改动人物称呼` （删「男主始终用"他"、女主叫云依」）
  - polisher 铁律 2：`严禁改动剧情、伏笔与既定设定的含义`（删「天气线（风/雨/雪/晴/裂）」）
  - reviewer 维度 1：`人物一致性：是否符合设定与写作铁律`
  - `EVALUATOR_RUBRIC` 维度 2：`是否符合设定与写作铁律`（harness 评测 prompt，同样去小说名）

### 3.3 agent.py / cli.py

- `NovelAgent.__init__` 加 `rules: str = ""`；`_writer/_polisher/_reviewer/partial_refine` 构造 system 时传入。
- `_writer` user 指令删除「不要解释风代表什么」（收编进铁律文件；「约200字」按边界保留）。
- `cli._build_agent`：读 `settings.rules_full`（utf-8，存在才读，同 `_load_instruction` 模式），传给 NovelAgent。

### 3.4 小说名清理（A10）

`cli/` 下 20 处「云依」全部清理：产品代码（prompts.py、rag.py docstring）去小说名；测试 fixture（conftest.py、test_agent.py、test_cli_partial.py、test_rag.py）改用虚构名「林晚」（语义不变）；`操作手册.md` 两处示例改虚构名。`.env copy.example` 补 `NOVEL_RULES` 条目。

铁律文件的**默认内容**不进代码仓库--由小说方在 NOVEL_DIR 下自建（换书即换文件）。

## 4. 0.3 写完自动入库

`_do_write` 在 `save_chapter` + 工作记忆之后：

```python
print("📚 更新向量库...")
try:
    agent.rag.add_document(str(chapter_file))
except Exception as e:
    print(f"(索引更新失败：{e})")
```

- 传**绝对路径**（`chapter_file` 本就是绝对路径），`add_document` 内 `_resolve_source` 原样通过，metadata.source 为绝对路径，与精修/重写通道一致。
- type=chapter：章节落在 `正文/AI生成/` 下，`classify_type` 命中「正文」-> `"chapter"`，无需改 rag.py。
- 失败不阻断（同精修通道的策略）。
- conftest `FakeRag.add_document` stub 已存在（记录 `add_calls`），直接用。

## 5. 0.5 exemplar 语料目录化

### 5.1 配置（config.py）

`exemplar_subpath` 默认值 `"文风基准/1.txt"` -> `"文风基准"`（目录级；单文件路径也兼容）。env `NOVEL_EXEMPLAR` 默认同步。

### 5.2 加载器（prompts.py）

```python
EXEMPLAR_MAX_CHARS = 30000   # 注入上限（中文近似 1 字≈1 token 的保守近似）

def load_exemplar(path, max_chars=EXEMPLAR_MAX_CHARS, progress=print) -> str
    # 路径是文件 -> [该文件]；是目录 -> sorted(*.txt / *.md)；不存在 -> ""
    # 逐文件 utf-8 读入，按序拼接（\n\n 连接）
    # 累计超出 max_chars 时截断，progress 打日志（原总字数/上限/截断文件数）

def exemplar_info(path) -> Tuple[int, int]   # (文件数, 总字数)，供状态命令
```

- 不依赖 config（宪法 §5：prompts 模块保持独立可单测）。
- 截断按**文件序**（不抽样）：排序靠前的基准文件优先保住，与 ROADMAP「按顺序截断」一致。

### 5.3 cli.py

- `_build_agent`：判断条件 `.is_file()` -> `.exists()`（兼容目录），加载走新 `load_exemplar`。
- `_do_status`：exemplar 路径存在时输出 `文风基准：N 个文件，共 M 字 @ <路径>`。

## 6. 0.6 rebuild 陈块精确清理

### 6.1 manifest

- 位置：`settings.chroma_path / "rebuild_manifest.json"`（NOVEL_CHROMA_DIR 下，宪法 §3 路径约定的延伸）。
- 内容：`{"ids": ["c0", ..., "cN"], "count": N}`（本次 rebuild 实际写入的 id 全集）。

### 6.2 build_index 流程

```
1. old_ids = 读 manifest（不存在/损坏 -> []，首次 rebuild 不清理不报错）
2. old_ids 非空 -> collection.delete(ids=old_ids)，progress 报清理数
3. upsert c0..cN（现行逻辑不变）
4. 写本次 manifest
```

- 只按 id 精确删：`c*` 通道与章节块 `{文件名}_{i}` 通道 id 不相交，**天然不动章节块**（覆盖删除/改名/缩块三种陈化：上次在 manifest、这次不在的 id 一律被清）。
- manifest 损坏（非法 JSON/OSError）按空处理，行为退化为现状（不清理），不阻断 rebuild。

## 7. 决策记录

| # | 决策 | 理由 |
|---|------|------|
| D1 | 「弃」= 不定稿直接结束，而非打回重写 | 与未来批量 fail-closed「不存盘」语义统一；避免「LLM 每次都吐散文审稿 -> 人被反复询问」的循环 |
| D2 | 人工确认用注入 callable 而非 cli 回调 | agent 层不 import cli（§5 单向依赖）；测试无需 monkeypatch input |
| D3 | 铁律空时不输出占位块 | 与 `_instruction_block` 一致；避免空铁律文件产生噪音 prompt |
| D4 | exemplar 上限用字符数近似 token | 不引入 tokenizer 依赖（§2 无新依赖）；30000 字对 glm-5.2 上下文安全 |
| D5 | manifest 放 chroma_path 下 | 与向量库同生命周期、同备份单元；NOVEL_CHROMA_DIR 可整体迁移 |
| D6 | 「约200字」不收编 | 任务边界明确：长度控制归 ROADMAP 0.8 |

## 8. 开放问题（记录上报，不在本批处理）

1. `harness.py` `run_tests` 硬编码人物名规则断言（产品代码含具体小说男主名），同类宪法 §1 问题，归 ROADMAP 1.2 词表外置。
2. SKILL.md 称文风基准有 14 个文件，当前工作副本无 `.env`/真实 NOVEL_DIR 无法核实；0.5 按「多文件可能存在」的目录级设计（天然兼容 1 或 N 个）。
3. 存量失败 3 个（`test_strip_polisher_meta` 的 `---` 分隔语义、`test_runtime_dir_override` 的 Windows 绝对路径解析、`test_defaults` 的 `max_reviews` 期望值 2 vs 6）与本批无关，不修。
4. `parse_review` 返回类型变更（`Optional[bool]`）是**有意的行为变更**：`test_parse_review_fallback_true` 期望值需同步更新（旧期望「默认通过」正是本项要消灭的行为）。
