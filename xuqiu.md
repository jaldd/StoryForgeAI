# 写小说 Agent 项目规划与开发提示词

> 用一个"写小说 Agent"项目，把 Agent 所有知识点练一遍
> 边做边学，做完即掌握
> 每个阶段配 AI 开发提示词，复制给 Claude Code / Cursor 让 AI 边写边教

---

## 一、项目设计思路

### 为什么选写小说

1. **知识点全覆盖**——能练到 Agent/MultiAgent/RAG/Memory/Tools/Prompt 所有点
2. **不依赖业务数据**——纯个人项目，不用公司数据
3. **产出可见**——小说本身是产出，有成就感
4. **场景直观**——小说创作过程容易理解，不复杂



### 版本演进（4 个版本，每个用上不同知识点）

| 版本             | 重点知识点                                    | 产出                 |
| ---------------- | --------------------------------------------- | -------------------- |
| V1 单 Agent      | Agent 核心、Chain、Memory、Tools、Prompt      | 一个能写小说的 Agent |
| V2 RAG 版        | RAG、Embedding、向量库、Hybrid Search、Rerank | 能查设定的 Agent     |
| V3 MultiAgent    | LangGraph、MultiAgent、Supervisor 模式        | 多 Agent 协作写小说  |
| V4 Agent Runtime | Agent Harness、FastAPI、评测、可回放          | 工程化的 Agent 系统  |

### 技术栈

- **Python**（必学，岗位要求）
- **LangChain**（Agent 框架）
- **LangGraph**（MultiAgent 编排）
- **Chroma**（向量数据库，轻量易上手）
- **FastAPI**（Web 框架）
- **OpenAI / 通义千问**（LLM，用国内模型便宜）

---

## 二、和工地智能体的关系对照（重要！）

| 写小说 Agent                | 工地智能体                     | 共同知识点                            |
| --------------------------- | ------------------------------ | ------------------------------------- |
| Director Agent（导演）      | 工地调度 Agent                 | MultiAgent Supervisor 协调            |
| Writer Agent（写手）        | 施工执行 Agent                 | Agent 核心能力                        |
| Character Agent（角色扮演） | 工地角色（工长/安全员/质量员） | 角色化 Agent                          |
| Editor Agent（编辑）        | 质量校验 Agent                 | 评估反馈机制                          |
| RAG（人物设定库）           | RAG（工地规范/图纸/方案）      | 向量检索 + Rerank                     |
| Memory（前情提要）          | Memory（工地状态历史）         | 长期记忆                              |
| Agent Runtime               | Agent Runtime                  | 工程化（可测试/可评估/可回放/可比较） |
| Prompt（角色设定）          | Prompt（Agent 角色定义）       | 提示词工程                            |
| Tools（查设定/生成章节）    | Tools（查规范/调设备/下单）    | 工具调用                              |
| 小说质量评分                | 施工方案合理性评分             | Agent 评估                            |

**关键认知**：学写小说 Agent 时，脑内对照工地智能体——Director = 调度，Writer = 执行，Editor = 校验，RAG = 规范检索。**知识点完全可迁移**。

---

## 三、环境准备

### 提示词（复制给 AI 让它帮你搭环境）

```
我要学习 AI Agent 开发，请帮我准备 Python 开发环境：

1. 安装 Python 3.11+，确认版本
2. 创建虚拟环境 venv
3. 安装依赖：langchain langchain-openai langgraph chromadb fastapi uvicorn pydantic python-dotenv
4. 配置 .env 文件（LLM API key 等）
5. 创建项目结构：
   novel_agent/
     ├── .env
     ├── requirements.txt
     ├── main.py
     ├── agents/
     ├── tools/
     ├── memory/
     ├── rag/
     └── prompts/

请一步步教我做，每步解释为什么这么做。我是 Java 开发者转 Python，请对比 Java 解释 Python 特性。
```

---

## 四、V1 单 Agent 版本

### 学习目标

- 理解 Agent 核心组件（Chain/Agent/Memory/Tools）
- 掌握 LangChain 基础
- 实现 Function Calling
- 掌握 Prompt 工程

### 架构

```
用户："写一章主角出差遇到问题的剧情"
  ↓
Writer Agent（LangChain Agent）
  ├── Tools:
  │   ├── search_character(keyword)  # 查人物设定
  │   ├── search_scene(keyword)      # 查场景设定
  │   └── write_chapter(content)     # 写章节
  ├── Memory: ConversationBufferMemory
  └── Prompt: 角色设定 + 任务描述 + ReAct
  ↓
输出章节内容
```

### 开发步骤

#### Step 1: 定义 Tools

**提示词**：

```
我在学习 LangChain Agent 开发。请帮我创建一个写小说的 Agent，先实现工具定义。

需求：
1. 工具1: search_character(keyword) - 查人物设定（先用假数据，返回人物信息）
2. 工具2: search_scene(keyword) - 查场景设定（先用假数据）
3. 工具3: write_chapter(content) - 写章节（打印并返回内容）

技术要求：
- 用 LangChain 的 Tool 类
- 用 Python typing 做类型注解
- 每个工具有清晰的 description（告诉 LLM 什么时候用）

请：
1. 写完整代码
2. 解释每个工具的 description 怎么写、为什么这么写
3. 对比 Java 注解，解释 Python 的装饰器 @tool
4. 解释 LangChain Tool 的结构（name/description/func）
5. 教我怎么跑、怎么测

我是 Java 开发者，请对比 Java 解释 Python 特性。
```

**验收标准**：

- [ ] 3 个工具能定义出来
- [ ] 能讲清楚 Tool 的 name/description/func 三要素
- [ ] 能讲清楚 description 为什么要有语义引导（对应你的 Hint 机制）

#### Step 2: 定义 Memory 和 Prompt

**提示词**：

```
继续写小说 Agent。现在加 Memory 和 Prompt。

需求：
1. Memory: 用 ConversationBufferMemory，记住对话历史
2. Prompt: 定义 Writer Agent 的角色设定
   - 角色：小说家
   - 任务：根据用户要求写章节
   - 约束：保持人物设定一致、剧情连贯
   - ReAct 模式：先思考再行动

技术要求：
- 用 LangChain 的 PromptTemplate
- 用 ConversationBufferMemory
- 解释 ReAct 模式的 Thought/Action/Observation

请：
1. 写完整代码
2. 解释 Prompt 模板怎么设计
3. 解释 Memory 的作用（短期 vs 长期）
4. 解释 ReAct 模式（对比你之前讲过的 Thought-Action-Observation）
5. 教我怎么跑、怎么测

请对比 Java Spring 的 Service/Repository，解释 LangChain 的 Chain/Memory 概念。
```

**验收标准**：

- [ ] Memory 能记住对话历史
- [ ] Prompt 包含角色/任务/约束
- [ ] 能讲清楚 ReAct 模式
- [ ] 能讲清楚 Memory 的作用

#### Step 3: 组装 Agent 并运行

**提示词**：

```
最后组装 Writer Agent 并运行。

需求：
1. 用 LangChain 的 create_react_agent 创建 Agent
2. 用 AgentExecutor 包装，加 Memory
3. 配置 LLM（用通义千问或 OpenAI）
4. 实现主循环：用户输入 → Agent 执行 → 输出章节

请：
1. 写完整代码 main.py
2. 解释 AgentExecutor 的作用（管理 ReAct 循环）
3. 解释 LangChain 的 LLM 抽象（对比 JDBC）
4. 跑一个 demo：让 Agent 写一章"主角李明出差遇到航班延误"
5. 解释 Agent 执行过程（Thought → Action → Observation → ...）

请对比 Java 的依赖注入，解释 LangChain 的组件组装方式。
```

**验收标准**：

- [ ] Agent 能跑通
- [ ] 能看到 Agent 的 Thought/Action/Observation 过程
- [ ] 能讲清楚 AgentExecutor 的作用
- [ ] 能讲清楚 Agent 和 Chain 的区别

### V1 学到的知识点

- ✅ Agent 核心组件（Chain/Agent/Memory/Tools）
- ✅ Function Calling（LangChain Tool）
- ✅ Prompt 工程（角色/任务/约束/ReAct）
- ✅ LangChain 基础（Tool/Prompt/Memory/AgentExecutor）
- ✅ Python 基础（typing/装饰器/class）

---

## 五、V2 RAG 版本

### 学习目标

- 掌握 RAG 架构
- 掌握 Embedding 和向量数据库
- 掌握检索优化（Chunking/Hybrid Search/Rerank）
- 把 V1 的假数据工具换成 RAG 检索

### 架构

```
人物设定文档（txt）
  ↓ Chunking（分块）
  ↓ Embedding（转向量）
向量数据库 Chroma
  ↓
Writer Agent 写作时
  ├── search_character: 向量检索人物设定
  ├── search_scene: 向量检索场景设定
  └── Hybrid Search: 向量 + 关键词
  ↓ Rerank（重排）
  ↓ Top-K 相关设定
  ↓
LLM 生成章节
```

### 开发步骤

#### Step 1: 准备知识库

**提示词**：

```
我在学 RAG。请帮我建一个小说知识库。

需求：
1. 创建几个文档：
   - 人物设定（主角李明、配角王芳等）
   - 场景设定（办公室、机场、酒店等）
   - 剧情大纲（前几章摘要）
2. 用 Chroma 建向量库
3. 把文档 Chunking 后 Embedding 存入

技术要求：
- 用 Chroma（轻量，本地文件）
- 用 OpenAI embedding 或 BGE embedding
- Chunking 策略：按句子分，每块 200-500 字

请：
1. 写完整代码
2. 解释 Embedding 是什么（把文本转向量）
3. 解释 Chunking 为什么需要、怎么分块
4. 解释 Chroma 的用法（对比 MySQL 表）
5. 教我怎么验证向量库建好了

请对比 ES 的倒排索引，解释向量检索和关键词检索的区别。
```

**验收标准**：

- [ ] 向量库能建起来
- [ ] 能讲清楚 Embedding 原理
- [ ] 能讲清楚 Chunking 策略
- [ ] 能讲清楚向量检索 vs 关键词检索

#### Step 2: 实现检索工具

**提示词**：

```
继续。把 V1 的 search_character 改成 RAG 检索。

需求：
1. search_character: 向量检索人物设定
2. search_scene: 向量检索场景设定
3. 加 Rerank：用 BGE Reranker 或简单按 score 排序
4. 加 Hybrid Search: 向量 + BM25 关键词（用 Chroma 的 where 过滤模拟）

请：
1. 写完整代码
2. 解释 RAG 检索流程（Embedding → 检索 → Rerank）
3. 解释 Rerank 为什么需要（向量检索快但不准，Rerank 精排）
4. 解释 Hybrid Search（向量 + 关键词结合）
5. 对比 ES + BM25 经验，讲解向量检索的优劣

请用代码展示检索效果，让我看到 Top-K 结果和 score。
```

**验收标准**：

- [ ] 检索工具能查到设定
- [ ] 能讲清楚 RAG 流程
- [ ] 能讲清楚 Rerank 原理
- [ ] 能讲清楚 Hybrid Search

#### Step 3: 集成到 Agent

**提示词**：

```
把 RAG 检索集成到 Writer Agent。

需求：
1. Writer Agent 的 search_character/search_scene 改用 RAG
2. Agent 写作前先检索相关设定
3. Memory 记住前情提要

请：
1. 完整代码 main.py
2. 跑 demo：让 Agent 写"李明在机场遇到王芳"
   - Agent 应该先 search_character("李明") 和 ("王芳")
   - 再 search_scene("机场")
   - 然后基于检索结果写章节
3. 展示 Agent 的 Thought/Action/Observation
4. 对比 V1（假数据）和 V2（RAG）的区别

请解释 RAG 怎么解决 Agent 的"幻觉"问题（基于设定生成而不是编造）。
```

**验收标准**：

- [ ] Agent 能调用 RAG 检索
- [ ] 生成的章节基于设定（不编造）
- [ ] 能讲清楚 RAG 的价值（解决幻觉）

### V2 学到的知识点

- ✅ RAG 架构（Embedding → 检索 → Rerank → 生成）
- ✅ Embedding 原理
- ✅ 向量数据库 Chroma
- ✅ Chunking 策略
- ✅ Hybrid Search（向量 + 关键词）
- ✅ Rerank（重排）
- ✅ RAG 解决幻觉

---

## 六、V3 MultiAgent 版本

### 学习目标

- 掌握 LangGraph
- 掌握 MultiAgent 协作（Supervisor 模式）
- 实现多 Agent 协作写小说

### 架构

```
用户："写一章主角出差遇到问题的剧情"
  ↓
Director Agent（Supervisor，导演）
  ├── 决策：先让 Writer 写草稿
  ↓
Writer Agent（写手）
  ├── 查设定（RAG）
  ├── 写草稿
  ↓
Director Agent
  ├── 决策：让 Character 润色对话
  ↓
Character Agent（角色扮演）
  ├── 润色对话，让角色更生动
  ↓
Director Agent
  ├── 决策：让 Editor 审稿
  ↓
Editor Agent（编辑）
  ├── 审稿，提修改意见
  ↓
Director Agent
  ├── 决策：通过，输出最终章节
  ↓
输出最终章节
```

### 开发步骤

#### Step 1: 定义 4 个 Agent

**提示词**：

```
我在学 LangGraph MultiAgent。请帮我建一个写小说的 MultiAgent 系统。

需求：4 个 Agent
1. Director Agent（导演）：Supervisor，决定下一步让谁做
2. Writer Agent（写手）：写章节草稿
3. Character Agent（角色扮演）：润色对话
4. Editor Agent（编辑）：审稿提意见

技术要求：
- 用 LangGraph 的 StateGraph
- 共享 State（task/draft/dialogue/feedback）
- Director 用 conditional_edges 决策路由

请：
1. 写 4 个 Agent 的定义
2. 解释 LangGraph 的 State/Node/Edge 概念
3. 解释 Supervisor 模式（Director 调度其他）
4. 对比 LangChain 单 Agent，解释 MultiAgent 的优势
5. 教我怎么跑

我是 Java 开发者，请对比 Spring 的 Service 编排，解释 LangGraph 的图编排。
```

**验收标准**：

- [ ] 4 个 Agent 定义出来
- [ ] 能讲清楚 LangGraph 的 State/Node/Edge
- [ ] 能讲清楚 Supervisor 模式
- [ ] 能讲清楚 MultiAgent vs 单 Agent 的优势

#### Step 2: 构建 Graph 并运行

**提示词**：

```
构建 LangGraph 图并运行。

需求：
1. 定义 State（TypedDict）：task/draft/dialogue/feedback/final
2. 构建 Graph：
   - Node: director/writer/character/editor
   - Edge: director → conditional → writer/character/editor → director → END
3. Director 根据 State 决定下一步：
   - 没 draft → writer
   - 有 draft 没 dialogue → character
   - 有 dialogue 没 feedback → editor
   - feedback 好 → END
   - feedback 差 → writer 重写

请：
1. 完整代码
2. 解释 conditional_edges 怎么实现路由
3. 跑 demo：写一章"李明出差遇到航班延误"
4. 展示 MultiAgent 协作过程
5. 对比工地智能体场景：Director = 调度 Agent，Writer = 执行 Agent，Editor = 校验 Agent
```

**验收标准**：

- [ ] Graph 能跑通
- [ ] 能看到 MultiAgent 协作过程
- [ ] 能讲清楚 conditional_edges 路由
- [ ] 能对应到工地智能体场景

### V3 学到的知识点

- ✅ LangGraph 框架
- ✅ MultiAgent 协作（Supervisor 模式）
- ✅ State/Node/Edge 图编排
- ✅ conditional_edges 路由
- ✅ MultiAgent vs 单 Agent 的优劣

---

## 七、V4 Agent Runtime 版本

### 学习目标

- 掌握 Agent Runtime / Harness 概念
- 实现可测试/可评估/可回放/可比较
- 用 FastAPI 暴露 API
- 建立评测体系

### 架构

```
FastAPI
  ↓ /write 接口
Agent Runtime
  ├── 运行日志（每次运行全记录）
  ├── 状态管理（Memory 持久化）
  ├── 工具调用记录
  ├── 错误处理（重试/降级）
  ↓
MultiAgent 系统（V3）
  ↓
评测模块
  ├── 质量评分（LLM 打分）
  ├── 可回放（日志重放）
  └── 可比较（A/B 对比）
```

### 开发步骤

#### Step 1: 加 FastAPI 接口

**提示词**：

```
给小说 Agent 加 FastAPI 接口。

需求：
1. POST /write：写章节，参数 {prompt}，返回 {chapter}
2. POST /chat：多轮对话，参数 {message}，返回 {reply}
3. GET /health：健康检查
4. 用 Pydantic 做请求/响应校验

技术要求：
- FastAPI + async/await
- Pydantic Model 校验
- 依赖注入（用 Depends）

请：
1. 完整代码
2. 解释 FastAPI 的路由、Pydantic 校验、依赖注入
3. 对比 Spring Boot 的 @RequestMapping/@RequestBody/@Autowired
4. 跑 demo：curl 调 /write 接口
5. 教我怎么调试

请对比 Spring Boot，解释 FastAPI 的异步特性（async/await）。
```

**验收标准**：

- [ ] API 能跑通
- [ ] 能讲清楚 FastAPI 的路由/校验/注入
- [ ] 能对比 Spring Boot 讲清异步

#### Step 2: 实现 Agent Harness

**提示词**：

```
给 Agent 加 Harness：可测试/可评估/可回放/可比较。

需求：
1. 可测试：定义测试用例，验证 Agent 输出
2. 可评估：用 LLM 给章节打分（连贯性/人物一致性/剧情合理性）
3. 可回放：记录每次运行的完整日志（输入/Thought/Action/Observation/输出）
4. 可比较：跑同一 prompt 多次，对比不同配置（如不同模型/不同 prompt）的效果

技术要求：
- 运行日志存 JSON 文件
- 评测用 LLM 打分
- 回放：从日志重建运行
- 比较：A/B 对比

请：
1. 完整代码
2. 解释 Agent Harness 的 4 个能力
3. 对比我之前讲过的 OpenSpec（可测试/可评估/可回放/可比较）
4. 跑 demo：同一 prompt 跑两次，对比效果
5. 教我怎么加评测指标

请对比 OpenSpec 的 Git diff 校验，解释 Agent Harness 的可测试/可回放。
```

**验收标准**：

- [ ] 能记录运行日志
- [ ] 能 LLM 打分
- [ ] 能回放
- [ ] 能 A/B 对比
- [ ] **能对应到你的 OpenSpec 经验**（这是面试加分点！）

### V4 学到的知识点

- ✅ Agent Runtime（执行环境/状态/工具/会话/错误）
- ✅ Agent Harness（可测试/可评估/可回放/可比较）
- ✅ FastAPI（路由/校验/注入/异步）
- ✅ 评测体系（质量评分/A/B 对比）
- ✅ Pydantic（数据校验）

---

## 八、整体知识点对照表

### 做完 4 个版本，你掌握的所有知识点

| 知识点                      | 在哪个版本学 | 岗位要求        | 你的掌握度 |
| --------------------------- | ------------ | --------------- | ---------- |
| Agent 核心组件              | V1           | Agent 核心理解  | ✅          |
| Chain/Agent 区别            | V1           | Agent 核心理解  | ✅          |
| Memory（短期/长期）         | V1           | Agent 核心理解  | ✅          |
| Tools/Function Calling      | V1           | Agent 核心理解  | ✅          |
| ReAct 模式                  | V1           | Agent 核心理解  | ✅          |
| Prompt 工程                 | V1           | 提示词工程      | ✅          |
| LangChain 框架              | V1           | LangChain       | ✅          |
| RAG 架构                    | V2           | 知识库工程      | ✅          |
| Embedding                   | V2           | 知识库工程      | ✅          |
| 向量数据库                  | V2           | 知识库工程      | ✅          |
| Chunking                    | V2           | 知识库工程      | ✅          |
| Hybrid Search               | V2           | RAG 加分项      | ✅          |
| Rerank                      | V2           | RAG 加分项      | ✅          |
| LangGraph                   | V3           | LangGraph       | ✅          |
| MultiAgent                  | V3           | MultiAgent 系统 | ✅          |
| Supervisor 模式             | V3           | MultiAgent 系统 | ✅          |
| Agent Runtime               | V4           | Agent Runtime   | ✅          |
| Agent Harness               | V4           | Agent Harness   | ✅          |
| 可测试/可评估/可回放/可比较 | V4           | Agent Harness   | ✅          |
| FastAPI                     | V4           | Python Web      | ✅          |
| 评测体系                    | V4           | RAG 评测        | ✅          |
| Python 基础                 | 全程         | Python          | ✅          |

### 没覆盖的（需要额外补）

| 知识点             | 怎么补                      |
| ------------------ | --------------------------- |
| 长期任务与状态恢复 | 看 LangChain 的长期任务示例 |
| 任务队列与调度     | 看Celery 或 RQ              |
| 增量更新（RAG）    | 看 Chroma 的 upsert         |
| RAG 可观测性       | 看 LangSmith                |

---

## 九、面试讲述模板

做完项目后，面试时这样讲：

### "你做过 Agent 项目吗？"

> A：做过。我自己做了一个"写小说 Agent"项目，端到端从 0 到 1 实现了一个 MultiAgent 系统：
>
> 1. V1 单 Agent 版本：用 LangChain 实现 Writer Agent，支持工具调用（查人物设定/场景设定）、Memory（对话历史）、ReAct 推理；
> 2. V2 RAG 版本：用 Chroma 建向量库存人物设定，实现了 Hybrid Search（向量+BM25）和 Rerank，解决 Agent 幻觉问题；
> 3. V3 MultiAgent 版本：用 LangGraph 实现 Supervisor 模式——Director 调度 Writer/Character/Editor 三个 Agent 协作；
> 4. V4 Agent Runtime：用 FastAPI 暴露 API，实现了 Agent Harness（可测试/可评估/可回放/可比较）。
>
> 这个项目让我掌握了 Agent 全栈技术，从 ReAct 到 MultiAgent 到 RAG 到工程化。

### "你之前的工作和 Agent 有什么关系？"

> A：我之前在广联达做过 aipipeline 项目，本质就是 Agent 工程化落地：
>
> - MCP Server = Agent 的工具协议层（16 个 Tools）
> - Agent Skills = Agent 的核心链路
> - OpenSpec = Agent Harness（可测试/可评估/可回放/可比较）
> - Session-Start Hook = Agent Runtime 的会话管理
>
> 我做的是生产级 Agent 工程化，写小说 Agent 是我把 Agent 全栈技术补全。

### "MultiAgent 怎么协作？"

> A：我用 Supervisor 模式——Director Agent 是主管，根据 State 决定调哪个 Agent：
>
> - 没 draft → Writer 写草稿
> - 有 draft 没 dialogue → Character 润色
> - 有 dialogue 没 feedback → Editor 审稿
> - feedback 好 → 输出，差 → Writer 重写
>
> 这种模式对应到工地智能体：Director = 工地调度 Agent，Writer = 施工执行 Agent，Editor = 质量校验 Agent。

---

## 十、时间规划建议

### 如果有 4 周

| 周      | 任务                                | 产出            |
| ------- | ----------------------------------- | --------------- |
| 第 1 周 | 补理论（04 文档）+ Python 基础 + V1 | 单 Agent 跑通   |
| 第 2 周 | V2 RAG                              | RAG 版本跑通    |
| 第 3 周 | V3 MultiAgent                       | MultiAgent 跑通 |
| 第 4 周 | V4 Runtime + 面试准备               | 完整项目 + 面试 |

### 如果只有 2 周（紧）

| 周      | 任务             | 产出                  |
| ------- | ---------------- | --------------------- |
| 第 1 周 | 补理论 + V1 + V2 | 单 Agent + RAG        |
| 第 2 周 | V3 + 面试准备    | MultiAgent（V4 可省） |

### 如果只有 1 周（应急）

- 重点：V1 + V3（理解概念即可，不用跑通所有）
- 背 04 文档的知识点
- 准备面试话术

---

## 十一、注意事项

### 1. 不要追求小说质量

重点是学知识点，不是写好小说。Agent 能跑通、能讲清楚原理就行。

### 2. 重点理解概念

每个版本做完，能讲清楚：

- 用了什么技术
- 解决什么问题
- 原理是什么
- 和工地智能体怎么对应

### 3. 边做边记录

每完成一个版本，记录：

- 踩了什么坑
- 怎么解决的
- 学到什么

这些是面试的素材！

### 4. 和你已有经验建立连接

每个知识点都对照你已有的 MCP/Agent Skills/OpenSpec 经验。**你的工程化经验是最大优势**，学新概念时要建立连接。

### 5. 用国内模型省钱

- 通义千问 / 文心一言 / DeepSeek 都行
- 不用 OpenAI（贵+网络）
- Embedding 用 BGE（中文好+开源）

---

## 十二、最后提醒

1. **这个项目是学习工具，不是简历项目**——简历还是用 aipipeline，这个项目是为了面试能答上来
2. **重点是能讲清楚原理**——不用追求代码完美
3. **和你已有经验建立连接**——你的 MCP/Agent Skills/OpenSpec 经验是最大优势
4. **边做边对照工地智能体**——Director=调度，Writer=执行，Editor=校验，RAG=规范检索
5. **做不完也没关系**——V1+V3 能跑通，能讲清楚，就够面试用了

**加油！你有机会的！**