# 技术设计：文风基准按章路由（exemplar-routing）

> Feature: `exemplar-routing`
> 对应 `requirements.md`。遵循 `.specify/memory/constitution.md`。

---

## 1. 总体思路

在「构建 agent（加载 exemplar）」与「写章」之间插一步**廉价路由调用**：

```
写第N章：xxx
   ↓
cli._do_write
   ├─ 读 样文标签.md（不存在 → 跳过路由，_build_agent 现状加载）
   ├─ route_exemplars(llm, task, tags)     ← 新增，一次 ~1k token 调用
   │     输入：任务描述 + 标签行列表
   │     输出：{"files": [...], "reason": "..."}
   ├─ 按需加载 exemplar = 说明全文 + 选中样文（复用 0.5 的拼接/截断）
   └─ NovelAgent(exemplar=按需加载结果)   ← 其余流水线零改动
```

**不动状态机、不动 agent 内部**：路由发生在 cli 层构建 agent 之前，`NovelAgent` 拿到的仍是拼好的 exemplar 字符串，对 agent 完全透明（A2 的实现保证）。

## 2. 现状证据（先读代码后下的结论）

| # | 论断 | 证据 |
|---|------|------|
| 1 | exemplar 在 `_build_agent` 启动时一次性加载 | `cli.py:95-98`（`load_exemplar(settings.exemplar_full)`） |
| 2 | 目录级加载已支持「说明全文 + 文件清单」两段式 | `prompts.py:_exemplar_corpus` 返回 `(manifest_text, files)`；`load_exemplar` 拼接 |
| 3 | manifest 过滤已存在（注入清单机制） | `prompts.py:_parse_manifest_names` + `_exemplar_corpus` 的 `by_name` 过滤 |
| 4 | run 记录的 config 段是 dict，可加键 | `cli.py:_do_write` → `save_run(record)`；record 由 `agent.run` 产出，`cli` 落盘前可增补 |
| 5 | 路由用 JSON 出口的先例（审稿/评测）都是「纯 JSON + 多级解析兜底」 | `agent.py:parse_review`（四级解析）；本 feature 复用同一哲学 |
| 6 | `改` 不注入 exemplar（只 `polisher_system`） | `agent.py:584-586`；A7 = 不动这里 |

## 3. 模块与数据流

### 3.1 `prompts.py` 新增

```python
EXEMPLAR_ROUTER_SYSTEM = """你是文风样文路由器。根据本章写作任务，从样文标签列表中选出最适合注入的样文。
规则：
1. 选 3 到 5 篇；宁缺毋滥，场景不贴的不要选
2. 只返回纯 JSON，不要 markdown 包裹：{"files": ["文件名", ...], "reason": "一句话理由"}
3. files 必须来自标签列表中出现的文件名，不得编造
"""

def exemplar_router_user(task: str, tag_lines: list[str]) -> str: ...
```

纯函数拼接，无 IO。

### 3.2 新模块 `routing.py`（避免 prompts.py 膨胀，且路由是独立关注点）

```python
def parse_tag_lines(text: str) -> list[tuple[str, str]]
    # 解析 样文标签.md："- 5.txt: 她在场时他慢慢落下来" -> ("5.txt", "描述")
    # 纯函数；复用 _MANIFEST_LINE_RE 思路但带冒号分割

def route_exemplars(llm, task: str, tags: list[tuple[str, str]]) -> RouteResult | None
    # 调 llm.chat(EXEMPLAR_ROUTER_SYSTEM, exemplar_router_user(task, tags),
    #            max_tokens=1024, temperature=0.2)
    # 解析 JSON（容错：剥代码围栏/找首尾大括号，复用 parse_review 哲学）
    # 校验：files ∈ 标签文件名集合；过滤不存在的；全落空/解析失败 → None
    # 返回 RouteResult(files=[...], reason=str)
```

- 走**主 llm**（`agent.llm`），不用 writer_llm：路由不是创作，且 writer_llm 可能是便宜模型（语义匹配要求稳）。
- LLM 调用失败（网络/超时）抛异常 → cli 捕获 → 回落现状，写作不中断（A3）。

### 3.3 按需加载：`prompts.load_exemplar` 增参

```python
def load_exemplar(path, max_chars=EXEMPLAR_MAX_CHARS, progress=print,
                  only_files: list[str] | None = None) -> str
```

- `only_files=None`：现状（清单/全量）。
- `only_files=[...]`：在「说明全文 + manifest 过滤后」的基础上再按此清单过滤（顺序遵 only_files）。
- 截断逻辑不动（A6）。`_exemplar_corpus` 不改签名，过滤放在 `load_exemplar` 内（拿到 files 后按名字筛）。

### 3.4 `cli._do_write` 接线

```python
# _build_agent 增可选参 exemplar_override: str | None（None=现状加载）
# _do_write 流程：
tags_text = _load_tag_file(settings)          # config.exemplar_tags_full，不存在返回 ""
if tags_text:
    tags = parse_tag_lines(tags_text)
    if tags:
        route = route_exemplars(agent_llm, task, tags)   # 需要先有 llm —— 见 D1
        ...
```

**D1 取舍：路由需要 LLMClient，但 LLMClient 在 `_build_agent` 里构造。** 解法：`_build_agent` 拆两步——先构造 `profiles`+`LLMClient`（轻量无 IO），路由用它调一次，再把结果作为 `exemplar_override` 传进 agent 构造。不拆函数，只把路由插在 `_build_agent` 内部：加载 tags → 若有则用 default profile 的 LLMClient 路由 → `load_exemplar(only_files=...)` → 构造 agent。**路由发生在 `_build_agent` 里**，`_do_write`/`_do_refine`/`_do_rewrite` 零改动即全受益（US5）。

- 路由打印：`🧭 样文路由：5.txt、10.txt、14.txt（她在场+风停=落下来感）`（A4/F4）。
- run 记录增补：`record["exemplar_route"] = {"files": [...], "reason": ...}`（A5）。`_do_write` 落盘前塞进 record（record 是 dict，直接加键）。

### 3.5 `config.py` 新增

```python
exemplar_tags_subpath: str = "文风基准/样文标签.md"   # NOVEL_EXEMPLAR_TAGS
@property def exemplar_tags_full(self) -> Path
```

留空（`NOVEL_EXEMPLAR_TAGS=""`）= 显式禁用路由。

### 3.6 `状态` 命令

`_do_status` 增一行：标签文件存在 → `样文路由：启用（N 条标签）`；否则不显示（不添噪音）。

## 4. 数据契约

### 样文标签.md 格式（人写，机器解析）

```markdown
# 样文标签

说明文字（随意，解析只取列表行）。

- 1.txt: 天气感强，内在拉扯，风与身体感受同写
- 5.txt: 她在场时他慢慢落下来；风停
- 10.txt: 日常靠近感，小事里的默契
```

解析规则：`^[-*]\s+(<文件名>):\s*(<描述>)`；文件名 token 与 0.5 `_MANIFEST_LINE_RE` 同口径（截到空白/括号/冒号逗号）；无冒号描述的行跳过。行内不含具体小说名（A8 由用户侧保证，spec 提示即可）。

### 路由 LLM 出口契约

```json
{"files": ["5.txt", "10.txt"], "reason": "本章写日常靠近，选日常向样文"}
```

解析容错链（复用审稿哲学）：直接 `json.loads` → 剥 ``` 围栏再 loads → 正则抓首个 `{...}` 块再 loads → 全败返回 None（回落）。

## 5. 错误与回落矩阵

| 情形 | 行为 | 验收 |
|------|------|------|
| 标签文件不存在/留空 | 不路由，现状加载 | A1 |
| 标签解析为空（格式全不对） | 不路由，现状加载 + 一行提示 | A3 |
| 路由调用抛异常（网络等） | 回落现状加载 + 提示，写作继续 | A3 |
| JSON 解析失败 | 同上 | A3 |
| files 全不存在 | 回落现状加载 + 提示 | A4 |
| files 部分不存在 | 过滤掉不存在的，用剩余 | A4 |
| 选中总量超限 | 按序截断 + 提示（0.5 现有逻辑） | A6 |

**核心原则：路由永远不阻塞写作。** 最坏情况 = 现状（3 万字全量），不比今天差。

## 6. 测试设计（宪法 §5：mock LLM 不联网）

- `tests/test_routing.py`：`parse_tag_lines` 纯函数（正常/无冒号/杂行/空）；`route_exemplars` 四分支（成功、JSON 坏、编造文件名被滤、全滤空→None）——FakeLLM 走 script。
- `tests/test_prompts_exemplar.py` 增补：`load_exemplar(only_files=...)` 过滤顺序与截断叠加。
- `tests/test_cli_write.py` 增补：标签存在 + FakeLLM 路由成功 → writer prompt 只含选中样文（A2）；run 记录含 exemplar_route（A5）；标签缺失 → prompt 与现状一致（A1）。
- 回归：全量 pytest，存量 3 failed（`test_strip_polisher_meta`/`test_runtime_dir_override`/`test_defaults`）不新增失败。

## 7. 取舍记录

| 决策 | 备选 | 为什么这么选 |
|------|------|--------------|
| 路由放 cli 层（`_build_agent` 内） | 放 agent 状态机新增"router"角色 | 状态机是创作流水线，路由是输入准备；放 cli 对 agent 零侵入，`改`/`精修` 免费受益且天然不注入（A7） |
| 主 llm 路由 | writer_llm 路由 | 路由要求语义判断稳定；writer_llm 常配便宜模型 |
| 标签文件独立（样文标签.md） | 塞回 00-使用说明.md 的注入清单节 | 注入清单=静态兜底，标签=动态路由依据，职责不同；且说明全文要进 prompt，标签文件不用（省 token） |
| 一次性全量标签进路由 prompt | 标签也做检索 | 14 条 × ~20 字 ≈ 300 token，检索纯属过度设计 |
| 温度 0.2 | 0 | glm-5.2 推理模型 0 有时反而啰嗦；0.2 与审稿一致 |

## 8. 开放问题

1. 路由结果要不要缓存（同章重写时复用）？——v1 不做：`重写` 路径的 task 含文件名，语义已变，缓存键麻烦；且一次路由 ~1k token 不值得。
2. 标签文件要不要支持「场景分组」结构？——不做，等真实使用反馈。一行一标签已覆盖说明第五节的全部映射。
