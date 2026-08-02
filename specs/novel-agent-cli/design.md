# 技术设计：Novel Agent CLI

> Feature: `novel-agent-cli`
> 遵循 `.specify/memory/constitution.md`。本文描述**已落地**的架构，不是草案。

---

## 1. 架构

```
用户输入
   ↓
CLI 交互层（cli.py）       ← 解析命令，调度
   ↓
Agent 编排层（agent.py）    ← NovelAgent：director 路由，状态机
   ↓
├── Writer              ← 查 RAG + 工作记忆 + 调模型写草稿
├── Polisher            ← 润色
└── Reviewer            ← 审稿，通过/打回（最多 N 次，防死循环）
   ↓
Harness 层（harness.py）   ← replay / compare / evaluate / run_tests
   ↓
存储层（storage.py）          ← 全部落 <NOVEL_DIR> 下
├── ChromaDB            ← 向量库（设定检索，惰性）
├── .agent/runs/*.json  ← 运行日志
├── .agent/runs/working_memory.json  ← 工作记忆持久化
└── 正文/AI生成/         ← 写好的章节
```

---

## 2. 模块边界与职责

| 模块 | 职责 | 关键设计 |
|------|------|---------|
| `config.py` | Settings：.env+环境变量，小说名/路径/模型/key | **小说解耦**：`NOVEL_NAME`/`NOVEL_DIR` 驱动所有路径；`require_api_key`/`require_novel_dir` 延迟校验 |
| `prompts.py` | 写作铁律/EXEMPLAR/各 agent system prompt | 集中管理，不依赖 config；消除 py/ 下三处重复 |
| `llm.py` | LLMClient 封装火山网关 | 控制字符清洗 + 指数退避重试；client 可注入（测试 mock） |
| `rag.py` | RAGStore 设定检索 | **惰性**建 Chroma（去 py/ 模块级副作用）；embedding 响应 data 兼容 dict/list |
| `memory.py` | ShortTerm / WorkingMemory / LongTerm | LongTermMemory.summarize 用 LLMClient |
| `state.py` | PipelineState 流水线状态 | 原 `NovelState` 改名，避免和 WorkingMemory 撞 |
| `agent.py` | NovelAgent 状态机 + run() | 依赖全注入；WorkingMemory 注入 writer 上下文（P1 连续性） |
| `storage.py` | 章节落盘 + run 日志 + 工作记忆持久化 | 补 py/ 的 gap（原版没存章节文件）；存盘剥离 LLM 自带标题 |
| `harness.py` | replay/compare/evaluate/run_tests | 全部接收 settings + out，便于测试 |
| `cli.py` | 交互式 REPL | 写后自动生成剧情摘要存工作记忆 |

---

## 3. 关键设计决策

### 3.1 两个"状态"分清
- `PipelineState`（state.py）：一次写作任务的状态机（task/draft/polished/feedback/final_chapter/round/next_agent）。
- `WorkingMemory`（memory.py）：小说当前客观进度（current_chapter/character_states/foreshadowing/last_plot_point）。
- py/ 里两者都叫 NovelState，撞名。生产版拆开。

### 3.2 去模块级副作用
py/`rag_volcano.py` 在 import 时就 `os.environ["ARK_API_KEY"]` + 建 Chroma client（缺 key 即崩）。
生产版 `RAGStore` 惰性初始化，config 注入，缺 key 时延到真正调用才报错。

### 3.3 工作记忆跨进程持久化（P1 连续性）
- `<NOVEL_DIR>/.agent/runs/working_memory.json` 落盘 current_chapter + 真实剧情摘要。
- 每写完一章，`cli._do_write` 调 LLM 生成 1-2 句剧情摘要（`PLOT_SUMMARY_SYSTEM`）存入 WorkingMemory。
- 下一章 writer 的 system prompt 注入 `WorkingMemory.snapshot()`，记得前章。
- glm-5.2 是推理模型，摘要 `max_tokens=1024`（宪法 §4）。

### 3.4 章节落盘去重标题
LLM 常自带头部（`# 第五章 异乡风起`），storage 存盘时用 `_strip_leading_title` 剥离（兼容阿拉伯/中文数字），再统一加 `第N章 标题` 头。同名已存在则追加 run_id 后缀保留历史。

### 3.5 审稿防死循环
`max_reviews`（默认 2）打回上限，超过强制定稿；`max_rounds`（默认 10）总轮次上限。

### 3.6 小说解耦（不绑死某一本书）
- 书名（`NOVEL_NAME`）与小说目录（`NOVEL_DIR`）都走配置，代码里**不出现任何具体小说名**。
- 小说内容（设定/exemplar/正文）+ 运行时（runs/chroma/working_memory）都在仓库外的 `NOVEL_DIR` 下；代码仓库保持纯代码。
- `NOVEL_NAME` 注入各 system prompt（`writer_system`/`polisher_system`/`reviewer_system` 接 `novel_name` 参数）；默认"本小说"，真实值在 gitignored `.env`。
- 运行时默认 `<NOVEL_DIR>/.agent/`，可用 `NOVEL_RUNS_DIR`/`NOVEL_CHROMA_DIR` 覆盖（如想复用旧 `chroma_db`）。

---

## 4. 数据流（写一章）

```
cli._do_write(task)
  → NovelAgent.run(task)
      director → writer(RAG retrieve + WorkingMemory snapshot + LLM) 
               → polisher(LLM) → reviewer(LLM, JSON pass/fail)
               → 不通过则回 writer（≤max_reviews 次）
      返回 (state, record)
  → storage.save_run(record)            # <NOVEL_DIR>/.agent/runs/<run_id>.json
  → storage.save_chapter(final, task)   # <NOVEL_DIR>/正文/AI生成/第NN章-标题.md
  → LLM 生成剧情摘要 → WorkingMemory.update_after_write → storage.save_working_memory
  → harness.evaluate(run_id)            # LLM 评委三维打分
```

---

## 5. 目录结构

代码仓库（纯代码，无小说数据）：

```
cli/
  pyproject.toml          # 包元数据 + 依赖
  README.md
  novel_agent/
    __init__.py __main__.py
    config.py prompts.py llm.py rag.py memory.py
    state.py agent.py storage.py harness.py cli.py
  tests/
    conftest.py test_config.py test_rag.py test_state.py
    test_agent.py test_harness.py test_storage.py test_integration.py
specs/novel-agent-cli/    # spec-kit（本目录）
  requirements.md design.md tasks.md
.specify/memory/constitution.md
```

小说目录（仓库外，由 `NOVEL_DIR` 指向，不进代码仓库）：

```
<NOVEL_DIR>/
  总纲.md 人物.md 伏笔地图.md ...   # 设定
  文风基准/1.txt                     # exemplar
  正文/新/...                        # 人工正文
  正文/AI生成/...                    # Agent 产出
  .agent/{runs,chroma_db,working_memory.json}   # 运行时
```

---

## 6. 技术选型（宪法 §2 对齐）

| 组件 | 选型 | 理由 |
|------|------|------|
| LLM | 火山方舟 OpenAI 兼容 coding 网关 | 套餐内，OpenAI SDK 直连 |
| Embedding | doubao-embedding-vision | 套餐内，多模态网关 |
| 向量库 | ChromaDB | 本地持久化，Python 原生 |
| CLI | 内置 input()+while | 简单够用，不引入额外依赖 |
| 配置 | 环境变量 + .env | API Key 不硬编码 |
