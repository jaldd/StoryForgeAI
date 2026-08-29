# 阶段 1 前半：质量门禁（quality-gate）- 技术设计

> 评审修订（2026-08-29）：§3.1.2 独白 quote 改首行截断、比喻 quote 置空（可定位性）；§3.5 拍死「任一不可定位即整文修复」（D12）；§3.6 豁免路径拍死（强制定稿/人工确认直存，evaluate 照跑留报告）；§6 补 `_build_agent` 异常落点与 steps 计数全清单；§8.3 Z 表重排对齐正文引用。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| A1-A7 审核维度化 | §3.2 reviewer schema 演进、§3.3 parse_review_full、§3.4 state 新字段 |
| A8-A15 修复式打回 | §1 拓扑、§3.5 fixer / _checker |
| A16-A24 规则硬 gate | §2 规则文件 schema、§3.1 checker.py |
| A25-A29 AI 味量化 | §3.1.3 三组件公式与基准语料 |
| A30-A35 门禁统一 | §3.6 门禁重排 + _gate_confirm、§3.7 回测 |
| A36-A37 兼容与工具 | §3.8 harness 扩展、§7 测试策略 |

## 1. 总体设计：流水线新拓扑

现状（`agent.py:179-183` agents 注册；`agent.py:267/310/390` 转移；`agent.py:177/527/532` `_reject_target`）：
writer -> polisher -> reviewer；reviewer 打回 -> `_reject_target`（run/rewrite 回 writer，refine 回 polisher）。

新拓扑：

```
run/rewrite: writer -> polisher ─┐
refine:                     ─────┘
                                    v
   checker --通过--> reviewer --通过--> done
      ^  |打回            | 打回
      |  v                v
      └---- fixer <-------+          （fixer 修复回填 state.polished 后回 checker 复检）
```

状态转移表（`state.next_agent`）：

| 当前 agent | 完成后 |
|---|---|
| writer | polisher |
| polisher | **checker**（原 reviewer，`agent.py:310`） |
| checker 通过 | reviewer |
| checker 打回（`review_count < max_reviews`） | fixer |
| checker 达上限 | reviewer（放行 + 留痕；强制定稿由 reviewer 逃生门统一收口，D7） |
| reviewer 通过 / 强制定稿 / 不可解析人工确认 | done |
| reviewer 打回 | fixer |
| fixer | checker（复检，A13） |

agents_map 变化：

- `self.agents`（run）= writer / polisher / **checker** / reviewer / **fixer** 五角色。
- `refine_agents`（`agent.py:523`，现仅 polisher/reviewer）= polisher / checker / reviewer / fixer。
- `rewrite_agents` 同 self.agents。

关键点：

- **`_reject_target` 删除**（D9）：打回固定 fixer，`refine` 的 try/finally 复位（`agent.py:527/532`）随之删除。
- `_polisher` 尾部 `next_agent = "reviewer"`（`agent.py:310`）改 `"checker"`。
- `_writer`/`_polisher` 的 feedback_hint 分支（`agent.py:234-236`、`280-282`）成为死代码（打回不再回 writer/polisher，意见由 fixer 消费），删除。
- `max_rounds` 超限兜底（`agent.py:434-437`）与 reviewer 不可解析人工确认（`agent.py:368-377`）不动，对 fixer 循环同样生效（双保险）。

## 2. 质量规则.json（D2 已拍板：独立 JSON）

位置：`NOVEL_DIR/质量规则.json`（`settings.quality_rules_subpath`，env `NOVEL_QUALITY_RULES`，默认 `质量规则.json`；留空 = 禁用）。

Schema（各节可独立缺省；文件存在但非法 JSON / 顶层非对象 -> 启动报错 fail-fast，A23）：

```json
{
  "blacklist": ["一丝", "不禁", "眼眸", "嘴角勾起一抹弧度"],
  "naming_redlines": {"forbidden": ["许风"]},
  "sentence": {"max_len": 80},
  "monologue": {"max_lines": 12},
  "metaphor": {"markers": ["像", "仿佛", "宛如", "如同", "恰似"],
               "max_rate": 0.2, "max_adjacent_pairs": 2},
  "ai_score": {"weights": {"blacklist": 0.4, "sentence": 0.3, "freq": 0.3},
               "anchors": {"blacklist_per_1k": 3.0, "sentence_sigma": 2.0,
                            "freq_cos_gap": 0.3, "min_baseline_chars": 10000}},
  "eval_gate": {"enabled": true, "threshold": 3.5,
                "weights": {"连贯性": 1.0, "人物一致性": 1.0, "剧情合理性": 1.0}},
  "intent_words": ["风"]
}
```

语义与去留：

- `blacklist`：AI 高频词。checker 命中即 issue；同时是 AI 味组件一。
- `naming_redlines.forbidden`：禁用称呼（男主被取名/错名）。**required 方向不做**（D10）：机械断言「必备称呼缺失」误伤不可控（一章不提某角色很正常）；「该出现」的意图断言归 `intent_words`（run_tests 消费）。
- `sentence.max_len`：单句字数上限（分句规则见 §3.1.2）。
- `monologue.max_lines`：连续非对话行上限（Z9 词法代理）。
- `metaphor`：句级命中率 = 含任一 marker 的句子占比 > `max_rate` 即违规；相邻句双双命中的对数 > `max_adjacent_pairs` 亦违规。
- `ai_score`：三组件权重 + 锚点（§3.1.3）。
- `eval_gate`：门禁开关/阈值/各维权重；`标题评分` 写进 weights 也会被硬排除（A32）。
- `intent_words`：run_tests 意图断言（A36）。

加载（checker.py 模块级函数）：

```python
def load_quality_rules(settings) -> Optional[dict]:
    # 路径未配置或文件不存在 -> None（checker 与门禁全跳过，不误伤）
    # 存在但 json 解析失败 / 顶层非 dict -> RuntimeError（fail-fast，报错含路径）
```

加载点：`cli._build_agent`（注入 agent，同 `rules` 字符串模式）与 `harness.evaluate`/`compare`/`run_tests`（checker 与 AI 味分）。本节 JSON 即模板，上线 = 复制到 NOVEL_DIR 改词表；`状态` 命令显示规则文件状态防静默失效（Z7）。

## 3. 模块改动清单

### 3.1 checker.py（新模块：纯函数，零 LLM）

```python
"""规则硬 gate 与 AI 味量化：纯代码检查，零 LLM 调用。"""
def split_sentences(text: str) -> list[str]: ...
def run_checks(text: str, rules: dict) -> list[dict]: ...      # 五项检查 -> issues
def load_baseline(settings) -> Optional[Baseline]: ...          # 基准语料统计
def ai_flavor_score(text: str, rules: dict, baseline: Optional[Baseline]) -> dict: ...
```

issue 与 reviewer 同构（A24）：`{"quote": "...", "problem": "规则名：...", "fix": "..."}`。

#### 3.1.1 分句与行判定

- 分句：按 `。！？!?；;` 与换行切分，strip 后非空为一句。
- 对话行（Z9）：行内出现任意引号对（`「」『』“”‘’`）即视为对话行；连续非对话行数即独白长度。

#### 3.1.2 五项机械检查

| 检查 | 实现 | issue 内容 |
|---|---|---|
| 黑名单 | 逐词 `text.count(w)` | quote=命中句（截前 50 字），problem=命中词与次数，fix=「删除或换成具体描写」 |
| 称呼红线 | forbidden 逐词 | 同上 |
| 句长 | 分句后 `len > max_len` | quote=该句，problem=句长 |
| 独白 | 连续非对话行 `> max_lines` | quote=区间首行截前 50 字（前缀子串，保持 §3.5 可定位），problem=行数 |
| 比喻密度 | marker 句占比或相邻对超阈 | quote=空（密度是全文属性，按 §3.5 定位规则走整文修复），problem=占比/总数 + 至多 3 句截断样例 |

quote 一律截断展示，防 issue 本身爆 token。

#### 3.1.3 AI 味量化（A25-A29）

```python
@dataclass(frozen=True)
class Baseline:
    total_chars: int
    sent_mean: float      # 基准平均句长
    sent_std: float
    freq: dict[str, float]  # 字 + bigram 归一化频率向量
```

三个 0-100 组件（越高越 AI，D6）：

| 组件 | 公式 | 锚点默认 |
|---|---|---|
| blacklist | `min(100, 命中密度(次/千字) / A_bl × 100)` | A_bl=3.0（千字 3 次满格） |
| sentence | `min(100, |mean(text) − μ| / σ / A_s × 100)` | A_s=2.0（2σ 满格）；无基准时 μ=35、σ=15（Z4，待回测校准） |
| freq | `min(100, (1 − cos(P, Q)) / A_f × 100)`，P/Q 为字 + bigram 频率向量 | A_f=0.3 |

- 总分 = 可用组件按 `ai_score.weights` 线性加权；**缺失组件的权重重归一**（D6）。
- 降级（A27）：基准语料总字数 < `min_baseline_chars`（默认 10000）-> freq 不可用、sentence 用内置默认基线，返回 `{"degraded": true}`；blacklist 未配置 -> 该组件不可用。
- 返回形状：`{"score": 62, "components": {"blacklist": 45, "sentence": 70, "freq": 55}, "degraded": false}`。
- 基准语料 = exemplar 目录全量（复用 `prompts._exemplar_files`，**不受 `EXEMPLAR_MAX_CHARS` 注入上限约束**，Z8）+ 人工正文目录（`settings.human_text_subpath`，默认 `正文/新`，env `NOVEL_HUMAN_TEXT`；1.5 的滚动注入属 style-loop，本 feature 只做统计消费）。
- 确定性：纯函数，同输入同输出（A25）。

### 3.2 reviewer schema 演进（A1-A3）

`prompts.reviewer_system`（`prompts.py:197-214`）重写：保留 6 既有维度原文，追加两维与新 schema：

```
7. 比喻密度：像/仿佛/宛如类标记词是否密集堆叠（5=克制自然，1=滥用）
8. 视角越界：叙述是否越出当前视角人物可知的范围（5=无越界）

只返回纯 JSON，格式如下，不要加任何其他文字、不要用 ```json 包裹：
{"pass": true/false, "reason": "总评（不超过30字）",
 "scores": {"人物一致性": 4, "文风一致性": 3, "剧情连贯性": 4, "时间线一致性": 5,
             "环境一致性": 4, "伏笔一致性": 5, "比喻密度": 4, "视角越界": 5},
 "issues": [{"quote": "原句逐字引用", "problem": "维度名：问题描述", "fix": "具体改法"}]}
不通过时必须把所有问题一次性列全，每个问题引用原句并给出改法。通过时 issues 留空数组。
```

- `pass`/`reason`/`issues` 三键保留（D4 兼容演进）；`scores` 缺失或维度缺失不报错（A6）。
- `issues` 仍容忍字符串数组（旧 schema），消费侧归一化（§3.3）。

### 3.3 parse_review_full（A5-A6）

`agent.py` 的四级 JSON 提取（`agent.py:57-82`）抽出为共享 `_extract_json(text) -> Optional[dict]`；`parse_review` 签名与语义零改动，新增：

```python
@dataclass
class ReviewResult:
    passed: Optional[bool]
    reason: str
    scores: dict   # 只收 1-5 整数，越界/非整数丢弃
    issues: list    # 字符串项归一为 {"quote": "", "problem": s, "fix": ""}
```

不可解析 -> None（`_confirm_unparseable` 既有路径不动）。`__all__` 增 `parse_review_full`。

### 3.4 state.py：新字段（A4/A24）

```python
scores: Dict[str, int] = field(default_factory=dict)  # reviewer 八维分
issues: List[dict] = field(default_factory=list)       # 结构化问题（checker/reviewer 同构）
```

`asdict` 自动进 run record 的 steps/final_state；replay 的 `.get` 容错已有先例（outline，`harness.py:47`），旧记录零崩（A37）。

### 3.5 fixer 与 _checker（agent.py，A8-A15）

`NovelAgent.__init__` 新增 `quality_rules: Optional[dict] = None`（注入模式同 `rules` 字符串；None = 无规则 = checker 直通）。

`_checker(state)`：

```python
issues = run_checks(state.polished, self.quality_rules) if self.quality_rules else []
if not issues or state.review_count >= self.max_reviews:
    # 通过；或达打回上限放行（log 留痕；强制定稿由 reviewer 逃生门统一收口，D7）
    state.next_agent = "reviewer"
    return
state.review_count += 1                    # 与 reviewer 共享预算（A14）
state.issues = issues
state.feedback = f"规则检查不通过（第{state.review_count}次）：{摘要}"
state.next_agent = "fixer"
```

`_fixer(state)`：

1. 修复对象 `state.polished`，消费 `state.issues`。
2. **定位**（A10）：`split_paragraphs(state.polished)`（`partial.py:58`）；issue.quote 非空且 `quote in text` -> 命中含 quote 的 para 块（首个）。段号排序去重合并相邻为 spans。**任一 issue 的 quote 为空或非原文子串 -> 整组直接走第 4 步整文降级**（D12：不做混合协议；reviewer 意见被改写、metaphor 全文属性 issue 均落此路径）。
3. **段落级修复**（A11 合并单次调用）：全部问题段 + 各自意见 + `build_context_pair` 上下文（`partial.py:158`）合成**一次** LLM 调用（writer_llm、max_tokens=4096、temperature=0.5，Z3）。输出协议（D11）：

   ```
   【第3段·修复后】
   <整段文本>
   【第7段·修复后】
   <整段文本>
   ```

   正则解析；**未返回的段保持原文**（保底不破坏）。逐段字数保护：`len(old) >= 50` 且 `len(new) < len(old) * 0.5` -> 该段保留原文 + log（沿用局部精修 D6 口径）。回填用 `apply_replacements`（`partial.py:176`），区间外逐字节不变。
4. **整文修复降级**（A12）：任一 quote 无法定位时（见第 2 步），单次 LLM 调用（fixer_system + 原稿全文 + 全部意见，要求保内容只改问题处）；输出剥围栏；整体字数保护 `len < 0.5 × 原` -> 不接受、保留原稿 + log（A15）。
5. 回写 `state.polished`，**清空 `state.issues`**（Z5，防陈旧意见重复触发），log 留痕，`next_agent = "checker"`。

prompts.py 新增：`fixer_system(novel_name, rules)`（修稿师 + 铁律：只改问题处；情节/人称/伏笔/其余表达不动；不加说明标题）、`fixer_user(spans_data)`、`fixer_whole_user(text, issues)`。

`_record` 的 config 增 `"quality_rules": self.quality_rules is not None`（Z6）。

### 3.6 门禁统一（cli.py，A30-A34）

`_do_write`（`cli.py:117-175`）重排：

```
agent.run -> save_run（先落 run record，弃而不失数据）
-> evaluate（从存盘后移到存盘前，评测报告照旧打印一次；豁免路径同样照跑留报告，仅跳过门禁判定）
-> 豁免判定：state.feedback 含「强制定稿」或「人工确认」（沿用 cli.py:192 既有字符串口径）-> 跳过门禁判定直存（D8）
-> 未豁免且 state.final_chapter 非空且 _gate_ok(score, rules) 为 False 时：
     _gate_confirm("低分（x < 阈值），存/弃") 应答弃 -> 不写章节文件，打印未保存
-> 通过（或豁免、或确认存）-> save_chapter -> rag.add_document -> 摘要/工作记忆（顺序不变）
```

```python
# cli 模块级确认缝（测试可替换，同 agent.review_confirm 的 0.1 模式）
def _gate_confirm(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "n"          # 保守弃

def _gate_ok(score, rules) -> bool:
    # rules None / eval_gate.enabled falsy -> True
    # score None 或无任何配权维度 -> True（A33：evaluate 被 monkeypatch 的测试缝）
    # 标题评分从 weights 硬排除（A32）
    # weighted = Σ w_k·score[k] / Σ w_k；return weighted >= threshold
```

`_refine_postprocess`（`cli.py:178-252`）：evaluate 从尾部提前到分支判定前（每命令仍恰好一次评委调用，调用量不变）；**仅 passed 自动存回分支过门禁**（D8），forced（is_better 判优，豁免口径同 _do_write：feedback 含「强制定稿」/「人工确认」即不进门禁）与未通过（不存回）分支不叠加；尾部重复调 evaluate 删除。

`状态` 命令（`cli.py:537`）：增「质量规则」一行（路径/词数/未配置提示）与「人工语料」一行（Z7）。

### 3.7 回测（A35）

harness 新增 `backtest_gate(settings, out=print, limit=None)` + cli 命令 `回测门禁`：

- 遍历 runs（limit 控条数），对每条 `final_chapter` 跑 evaluate（LLM 评委，顺序执行）；
- 按 `eval_gate.weights` 算各条加权分，输出分数分布 + 各候选阈值（3.0/3.5/4.0）的拦截面（run_id 清单）；
- 分数缓存 `.agent/gate_backtest.json`（Z10，按 run_id 增量，避免重复烧评委）；
- 「误伤」无自动 ground truth：拦截清单供人工核对（REPL 里人是标尺）。

### 3.8 harness 扩展

- `evaluate`（`harness.py:112-157`）：LLM 评分后追加 AI 味分打印（`ai_flavor_score`；规则与基准从 settings 加载）：

  ```
  AI 味浓度: 62/100（越高越AI） 组件：黑名单 45 · 句长 70 · 词频 55
  （降级：基准语料不足，词频组件未参与）
  ```

  返回 dict 增键 `"AI味浓度"`。
- `compare`（`harness.py:195-219`）：增「AI味浓度」行（双方现算）；「含风次数/含许风」两行改从规则文件读（forbidden/intent_words），未配置跳过（Z1）。
- `run_tests`（`harness.py:160-192`）：

  ```python
  rules = load_quality_rules(settings)
  cases = []
  if rules:
      for w in rules.get("naming_redlines", {}).get("forbidden", []):   # 铁律：不出现
          cases.append((f"称呼红线：不含'{w}'", w not in chapter, f"出现次数={chapter.count(w)}"))
      for w in rules.get("intent_words", []):                            # 意图：出现
          cases.append((f"意图：含'{w}'", w in chapter, f"出现次数={chapter.count(w)}"))
  cases.append(("流程正确性：审稿通过且 done", ..., ...))                  # 原样保留
  # rules 为 None -> 只剩流程断言（不误伤，A36/A23）
  ```

## 4. 不动清单（防漂移）

- `parse_review` 签名/语义/全部调用点（A5）。
- `partial.py` 全部函数与 `改` 命令交互（非目标 8）；fixer 只 import 复用。
- `_confirm_unparseable`、reviewer 逃生门（`agent.py:345-351`）、`max_rounds` 兜底、polisher 字数保护（`agent.py:303-308`）。
- `EVALUATOR_RUBRIC` 四维与 evaluate 的评委流程（只追加 AI 味输出）。
- LLM 配置面与既有调用点温度/max_tokens（宪法 §2/§4）；fixer 新调用按 §3.5。
- `py/`、Java 侧、RAG 检索策略与索引时机。
- run record 既有键（config 只增 `quality_rules`）。

## 5. env 变量表（新增两个，其余不动）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_QUALITY_RULES` | 质量规则文件（相对 novel_dir） | `质量规则.json` | str，空 = 禁用 |
| `NOVEL_HUMAN_TEXT` | 人工正文目录（AI 味基准语料，相对 novel_dir） | `正文/新` | str，空 = 不用人工语料 |

`.env copy.example` 追加对应注释段（含一句「无此文件 = checker 与门禁不启用」）。

## 6. 实现注意（坑位）

- **lru_cache 纪律**：`get_settings()` 带 `@lru_cache(maxsize=1)`，测试 setenv 后必须 `cache_clear()`，finally 再 clear（0.8 建立的模式）。
- **评测缝兼容是硬测试**：`test_cli_write.py` 把 `cli.evaluate` monkeypatch 为返回 None 的 lambda——`_gate_ok(None, ...)` 必须走跳过分支（A33）。
- **steps 计数变更（checker 无规则时也作为 no-op 步入 steps）**：`test_pipeline_happy_path` 断言 3 步 -> 4 步（writer/polisher/checker/reviewer）；`test_pipeline_review_reject_then_pass` 断言 6 步 -> 7 步（打回路径改为 ... -> fixer -> checker -> ... 新序列）；`test_refine_skips_writer` 断言 2 步 -> 3 步（polisher/checker/reviewer）；`test_refine_reject_goes_to_polisher` 随 `_reject_target` 删除而重写；`test_pipeline_max_reviews_cap` / `test_pipeline_max_reviews_forced_finalize_warns` 的 FakeLLM 打回脚本序列随 checker 步数同步调整。既有断言随行为同步更新（行为变更，非回归破坏）。
- **`_build_agent` 异常落点**：4 个调用点（`cli.py:124/268/304/359`）均在各命令的 try 块之外，非法质量规则 JSON 触发的 RuntimeError 会裸抛崩 REPL--命令层捕获 RuntimeError 打印后 return（不吞 KeyboardInterrupt）。
- **FakeLLM 脚本**：fixer 输出按 D11 标记协议构造；reviewer 新 schema 脚本构造 scores+issues；旧 schema 脚本保留用于 A6 兼容用例。
- checker 的 max_len 默认 80 偏保守：误伤优先级低于漏检，先上线后回测收紧。
- `load_baseline` 每次调用全量读语料：eval/compare 单次命令只调一次，秒级，可接受；不缓存避免陈旧。

## 7. 测试策略（全程不联网）

- **test_checker.py（新）**：五项检查各自命中/未命中/未配置跳过；`load_quality_rules` 三态（缺文件 None / 非法 JSON RuntimeError / 正常）；`split_sentences` 边界；`ai_flavor_score` 确定性（同输入两次调用相等）+ 区分度（构造 AI 味重稿 vs 仿人稿，前者显著更高）+ 降级（无基准 degraded=True 且 freq 不参与）+ 权重重归一。
- **test_agent.py**：`parse_review_full` 四态（新 schema 全字段 / 旧 schema 归一 / 不可解析 None / scores 越界丢弃）；happy path 4 步含 checker；checker 打回 -> fixer -> checker 复检序列（FakeLLM 脚本含修复输出）；reviewer 打回进 fixer（writer 不再二次写作）；review_count 共享预算（checker 连续打回达 max_reviews 后放行）；fixer 段落级其余段落逐字节不变；quote 不可定位走整文修复；字数保护触发保留原稿；record config 含 quality_rules；state.scores/issues 落盘。
- **test_cli_write.py**：门禁三路（低分+确认弃 -> 章节文件未写；低分+确认存 -> 写入；evaluate 返回 None -> 跳过门禁照常存）——monkeypatch `cli.evaluate` 与 `cli._gate_confirm`；规则未配置时门禁不生效。
- **test_harness.py**：run_tests 读规则文件（forbidden/intent_words 断言；规则缺失只剩流程断言）；evaluate 输出含 AI 味行（monkeypatch `checker.ai_flavor_score` 或构造 tmp 语料）；compare 含 AI 味行与规则行；旧记录（无新键）replay/compare 不崩（A37）。
- **回归命令**：`cli/` 下 `python -m pytest tests/ -q`；基线 3 存量失败（`test_strip_polisher_meta`/`test_runtime_dir_override`/`test_defaults`），零新增。

## 8. 决策表

### 8.1 用户已拍板（2026-08-29）

| # | 决策 | 选项 | 拍板 | 来源 |
|---|---|---|---|---|
| D1 | 打回机制 | 修复式（fixer 保稿只改问题处）vs 维持从零重写 | **修复式** | ROADMAP 1.1 待定项 |
| D2 | 词表/阈值载体 | 独立 JSON vs 并入写作铁律.md | **独立 JSON（质量规则.json）** | 开放问题 1 |
| D3 | 阶段 1 拆分 | 一个 feature vs 拆两个 | **拆两个：quality-gate（1.1-1.4）先行，style-loop（1.5/1.6）后行** | 开放问题 3 |

### 8.2 设计决策（本 design 拍板）

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D4 | reviewer schema 演进 | a) 破坏式新 schema；b) 兼容演进（保留 pass/reason，新增 scores/issues 对象，旧输出归一化） | **b** | FakeLLM 旧脚本、旧 run 语义、线上旧模型输出全部免改；A5/A6 由 b 直接满足 |
| D5 | 维度集与分向 | 6 既有 + 比喻密度 + 视角越界 = 8 维，全部 1-5、5=最好 | - | ROADMAP 1.1 点名后两维；分向与 EVALUATOR_RUBRIC 一致（run_tests 断言 1-5） |
| D6 | AI 味分语义 | 0-100 越高越 AI；三组件线性加权；缺失组件权重重归一 | - | 方向直觉无歧义；重归一保证降级后仍在有效区间 |
| D7 | 预算与逃生门 | checker 打回共享 review_count；checker 达上限放行（不强制定稿），由 reviewer 逃生门统一收口 | - | 单一强制定稿点防语义分裂；checker 放行必经 reviewer，最终仍被逃生门兜住 |
| D8 | 门禁覆盖面 | _do_write 全量 + _refine_postprocess 仅 passed 自动存回分支；豁免路径（强制定稿/人工确认，feedback 字符串命中）直存不进门禁判定 | - | forced 有 is_better 二次判优、未通过分支不存回、人工确认是人拍板（A34）；豁免直存 = 向量库/摘要照常、evaluate 照跑留报告、仅跳过门禁判定；避免多重拦截摩擦 |
| D9 | _reject_target 机制 | a) 泛化为可配目标；b) 删除，打回固定 fixer | **b** | 修复式打回下三入口目标一致，可配目标是无人消费的配置面；删机制优于留死参数（宪法 §5） |
| D10 | 称呼红线方向 | 仅 forbidden；required 不做机械断言 | - | 「必备称呼缺失」误伤不可控；「该出现」语义归 intent_words（run_tests） |
| D11 | fixer 输出协议 | a) 段落标记【第N段·修复后】+ 缺段回落原文；b) JSON | **a** | 长中文文本塞 JSON 转义错误率高；回落原文是保底语义（漏改好过改坏） |
| D12 | 部分可定位时的修复策略 | a) 任一 quote 不可定位（空或非子串）即整组走整文修复；b) 混合（可定位走段落级 + 不可定位走整文） | **a** | 单一协议实现简单、失败模式少；整文修复带全部意见 + 字数保护，正确性不损，只多花一次整文 LLM 调用 |

### 8.3 自主补充（用户未点名）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | run_tests/compare 的小说词硬编码改读规则文件 | A36 的自然延伸；compare 的含风/含许风行同违反 §1 精神，同模式顺手解耦 |
| Z2 | checker 打回的 feedback 附命中摘要（规则名+次数） | 复检失败时 REPL 可读；明细在 state.issues |
| Z3 | fixer 走 writer_llm、max_tokens=4096、temperature=0.5 | 修复是生成类（0.7 路由）；0.5 介于 polisher 0.6 与 reviewer 0.2 之间（改写要稳） |
| Z4 | 降级内置句长基线 μ=35、σ=15 | 中文短句小说经验值；待回测校准，锚点已可配 |
| Z5 | fixer 消费后清空 state.issues | 防陈旧意见在下一轮 checker 打回时重复注入 |
| Z6 | record config 增 quality_rules 布尔 | 可追溯该 run 是否带规则跑（回测筛样本）；门禁结果不进 record（评测本就不落盘，保持现状） |
| Z7 | 状态命令显示规则/语料状态 | 规则文件缺失时 feature 静默失效，必须可发现 |
| Z8 | 统计基准不受 EXEMPLAR_MAX_CHARS 限制 | 注入上限是 prompt 预算问题；统计要全量 |
| Z9 | 独白 = 连续非对话行（含任意引号对即算对话行） | 词法代理（ROADMAP 1.2 口径：机械可查的才进 checker） |
| Z10 | 回测分数缓存 .agent/gate_backtest.json | 评委调用是真实成本，缓存避免重复烧 |

## 9. 已知局限（接受，不修）

- checker 词法代理有漏检/误伤（视角越界、语义级比喻本就归 reviewer）；quote 定位依赖 LLM 忠实引用原文，不忠实时走整文降级。
- AI 味分的锚点与句长降级基线是经验值，回测校准后才可信；上线初期只展示不进门禁（A29）正是安全垫。
- eval 门禁依赖 LLM 评委，方差大：阈值默认保守（3.5），REPL 人工确认兜底；分维收紧等历史数据（非目标 7）。
- 低分确认弃时评委调用已烧（可接受：评委调用 ≪ writer 全链路）。
- 回测需真实 LLM 评委跑历史 runs（ROADMAP「零成本」前提不成立，Z10 缓解）。
- metaphor 双阈值（max_rate/max_adjacent_pairs）可能冗余，实跑后留一（P1 清理）。
