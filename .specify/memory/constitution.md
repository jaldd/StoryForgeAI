# 项目宪法（Constitution）

> 本文件是 StoryForgeAI 小说创作 Agent 的**最高约束**，所有 `specs/<feature>/` 下的需求与设计都不得违背。
> 跨 feature 长期生效；改这里要慎重，改了要同步所有相关 spec。

## 1. 项目身份

做一个**与具体小说解耦**的命令行小说创作 Agent。**不是学习练手，是可落地、可迭代的产品。**
一句话需求 -> 自动走「查设定 -> 写草稿 -> 润色 -> 审稿」流程，写完存文件、记前文、可回放可评测。

- 书名、小说目录**都不硬编码**，全走配置（`NOVEL_NAME` / `NOVEL_DIR`）。代码仓库里不得出现任何具体小说名。
- 小说内容与运行时都在**仓库外**的 `NOVEL_DIR` 下；代码仓库保持纯代码。
- 当前实现位于 `cli/novel_agent/`（Python）。仓库里另有 `docs/spec/technical-spec.md`（Java/LangChain4j 宏愿景）与 Python agent 是**两条线**，不互相约束。

## 2. 技术栈（硬约束）

| 组件 | 选型 | 约束 |
|------|------|------|
| 语言 | Python 3.11+ | 实际跑 3.13 |
| LLM | OpenAI 兼容网关，来源可换（0.7） | `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` 接线；不设回落火山 coding 网关 |
| 默认模型 | `glm-5.2` | **推理模型，见 §4**；`LLM_MODEL` -> `CLAUDE_MODEL` -> 默认 三级回落 |
| Embedding | `doubao-embedding-vision`（多模态） | 响应 `data` 是 **dict**（`{"embedding":[...]}`），不是 list |
| 向量库 | ChromaDB | 本地持久化 |
| CLI | 内置 `input()` + while | 不引入额外 CLI 框架 |
| 配置 | 环境变量 + `.env`（python-dotenv） | **API Key 不硬编码** |

## 3. 存储与路径约定（小说解耦）

小说内容与 Agent 运行时都在**仓库外**的 `NOVEL_DIR` 下：

```
<NOVEL_DIR>/                  # 仓库外，由 NOVEL_DIR 指向
  设定.md 文风基准/ 正文/   # 小说内容（RAG 索引源 + exemplar + 人工正文）
  正文/AI生成/                 # Agent 产出章节
  .agent/                      # 运行时（自动生成）
    runs/*.json  chroma_db/  working_memory.json
```

- `NOVEL_NAME`：prompt 里用的显示名（默认"本小说"，真实值在 gitignored `.env`）。
- `NOVEL_DIR`：小说内容根目录，**必填**（用到时 `require_novel_dir` 校验）。
- 章节产物 -> `<NOVEL_DIR>/正文/AI生成/`（`NOVEL_CHAPTER_SUBDIR` 可覆盖）。
- 文风金标准 -> `<NOVEL_DIR>/文风基准/1.txt`（`NOVEL_EXEMPLAR` 可覆盖；留空则不用范例）。
- run 日志 / 向量库 / 工作记忆 -> 默认 `<NOVEL_DIR>/.agent/`，可用 `NOVEL_RUNS_DIR`/`NOVEL_CHROMA_DIR` 覆盖到别处。
- **代码仓库不得出现** `py/runs`、`chroma_db`、`docs/<书名>` 等小说数据。
- **不修改 `py/`**（学习成果保留），只读取迁移。
- 写作铁律与文风金标准的**唯一真源**是 `NOVEL_DIR` 下的设定文档 + `prompts.py`；spec 不重复抄录，只引用。

## 4. glm-5.2 推理模型约束（踩过的坑；换模型须重实测）

`glm-5.2` 是推理模型：生成可见回答前先消耗 token 做内部推理，计入 `max_tokens` 预算。

- `max_tokens` 设小（≤512）会 `finish_reason="length"` 且 `content=""`（空回），重试也救不回来。
- **短输出调用（摘要/审稿 JSON/评测）`max_tokens` 至少 1024**；长输出（写作/润色）4096。
- `novel_agent/llm.py` 的 `chat()` 默认 `max_tokens=1024`。新加 LLM 调用处遵循此阈值。
- 以上经验值绑定 glm-5.2 + 火山网关；换模型/换商后必须重新实测，必要时用
  `NOVEL_LLM_EXTRA={"max_tokens": ...}` 透传覆盖（同名键 extra 赢）。

## 5. 模块边界

```
cli（REPL 调度）
  └─ agent（writer/polisher/reviewer 状态机；写作侧可注入独立 writer_llm）
       ├─ llm（LLMClient，可注入 fake client 测试）
       ├─ rag（RAGStore，惰性建 Chroma）
       └─ memory（ShortTerm / WorkingMemory / LongTerm）
  └─ storage（章节落盘 + run 日志 + 工作记忆持久化）
  └─ harness（replay / compare / evaluate / run_tests）
```

- 依赖**注入**，不用模块级全局；`rag_volcano` 在 import 时建 client/读 env 的反模式不复现。
- `PipelineState`（流水线状态）与 `WorkingMemory`（小说当前进度）是**两个东西**，不可混名。
- 联网只在 `llm`/`rag` 边界；其余模块纯函数化、可单测。测试 mock LLM，不联网。

## 6. 开发流程（spec-kit）

新功能/迭代走标准流程，每个 feature 一个目录：

1. `specs/<feature>/requirements.md` — 需求（用户故事、功能列表、EARS 验收标准）
2. `specs/<feature>/design.md` — 技术设计（架构、模块、数据流、取舍）
3. `specs/<feature>/tasks.md` — 任务分解（勾选项，实现逐项推进）

`.specify/memory/` 本文件作为跨 feature 的常驻约束。改宪法 -> 同步受影响 spec。

## 7. 验收纪律

- 阶段验收口径防漂移：P0 能跑、P1 有记忆、P2 可迭代，**严禁把后阶段指标当前阶段阻塞条件**。
- 任何新能力上线前，先过基线：不破写作铁律、不丢前文连续性、单测绿。

## 8. 开发环境与 token 纪律（2026-09-05 volume-align 踩坑记录）

**已知环境问题**：TRAE sandbox 下 `python -m pytest` 会**挂起**（`--version` 正常、
import 正常、未动过的测试文件也挂）——是沙箱进程问题，**不是代码问题**。

**根因定位（2026-09-05，planner 期间查明）**：分两层。
1. `import cli` 卡 = readline 顶部 import 在无 tty 环境无限阻塞——**已修**：
   readline 懒加载进 `main()`（cli.py），模块可在 sandbox/CI/管道环境安全 import。
2. `pytest` 启动卡 = pytest 框架自身 tty 探测，沙箱限制，**修不了**（非我们代码）。

**处置纪律（防 token 浪费）**：

1. **环境问题 ≠ 代码问题，先区分再动手**。判据：换一个从未动过的文件跑仍挂 → 环境问题。
2. **环境问题不重试、不自造工具绕路**。反复重试 pytest、自写临时测试 runner
   （fixture 空壳导致大量假 FAIL，既烧 token 又误导判断）都是已踩过的坑。
3. **正确姿势两步走**：
   - 一次最小验证脚本确认核心逻辑（如直接 import 被测函数 + assert，跑一次即收；
     验证脚本避免 import cli 之外的 tty 依赖）；
   - 权威全量回归**交给人跑**：让用户在 IDE 终端执行 `python -m pytest tests/ -q`
     （用户侧零 token），贴回结果再继续。
4. 与门禁哲学同构：**机器（沙箱）拿不准时交给人**，不要自己绕。
