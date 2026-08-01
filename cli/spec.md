# Novel Agent CLI - 规格说明

> 状态：草案待确认
> 最后更新：2026-08-01

---

## 1. 项目目标

做一个命令行小说创作 Agent，能真正用于写《修仙不如陪她看云》。

**不是学习练手，是可落地、可迭代的产品。**

### 核心价值
- 输入一句话需求，自动走"查设定 -> 写草稿 -> 润色 -> 审稿"流程
- 写完自动存文件，记得前文，能连续写多章
- 有质量检查（Harness），能回放、对比、打分

---

## 2. 用户故事

```
作为小说作者，我想：
1. 在命令行输入"写第5章：异乡风起"
   -> Agent 自动检索相关设定
   -> Writer 写草稿
   -> Polisher 润色
   -> Reviewer 审稿
   -> 通过后存到正文目录
   -> 打印评分

2. 输入"replay run_xxx"
   -> 回放某次写作过程

3. 输入"eval run_xxx"
   -> 对某次写作打分

4. 输入"compare run_a run_b"
   -> 对比两次写作效果

5. 输入"状态"
   -> 查看当前写到第几章、角色状态、未回收伏笔

6. 输入"quit"
   -> 退出
```

---

## 3. 功能列表

### P0（必须做）
- [ ] 交互式 CLI（while 循环，持续对话）
- [ ] MultiAgent 流程（director -> writer -> polisher -> reviewer）
- [ ] RAG 检索（复用 py/rag_volcano.py）
- [ ] 写完自动存文件到 docs/修仙不如陪她看云/正文/
- [ ] 运行日志（JSON，存 py/runs/）

### P1（应该做）
- [ ] Memory 三层（复用 py/agent_memory_volcano.py）
- [ ] 回放功能（replay）
- [ ] LLM 打分评测（eval）

### P2（可以做）
- [ ] A/B 对比（compare）
- [ ] 测试用例（test）
- [ ] 多章节连续写作（记住写到第几章）
- [ ] 状态查看命令

---

## 4. 架构设计

```
用户输入
   ↓
CLI 交互层（cli.py）       ← 解析命令，调度
   ↓
Agent 编排层（agent.py）    ← Director 路由，状态机
   ↓
   ├── Writer              ← 查 RAG + 调模型写草稿
   ├── Polisher            ← 润色
   └── Reviewer            ← 审稿，通过/打回
   ↓
Harness 层（harness.py）   ← 日志/回放/评测
   ↓
存储层
   ├── ChromaDB            ← 向量库（设定检索）
   ├── py/runs/*.json      ← 运行日志
   └── docs/.../正文/      ← 写好的章节
```

---

## 5. 目录结构

```
cli/
  spec.md                  # 本文件：规格说明
  tasks.md                 # 任务分解
  pyproject.toml           # Python 项目配置
  novel_agent/             # 主包
    __init__.py
    __main__.py            # 入口：python -m novel_agent
    cli.py                 # 交互式命令行
    agent.py               # MultiAgent 编排（director/writer/polisher/reviewer）
    rag.py                 # RAG 检索（从 py/rag_volcano.py 迁移）
    memory.py              # 三层记忆（从 py/agent_memory_volcano.py 迁移）
    harness.py             # 日志/回放/评测（从 py/multiagent_novel.py 迁移）
    config.py              # 配置（API Key、模型、路径）
  tests/
    test_agent.py
    test_rag.py
```

---

## 6. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | AI 生态最全，现有代码可复用 |
| LLM | 火山方舟（OpenAI 兼容网关） | 套餐内，不额外花钱 |
| Embedding | doubao-embedding-vision | 套餐内 |
| 向量库 | ChromaDB | 本地持久化，Python 原生 |
| CLI 交互 | 内置 input() + while | 简单够用，不引入额外依赖 |
| 配置 | 环境变量 + .env | API Key 不硬编码 |

---

## 7. 实现里程碑

### 里程碑 1：能跑（P0）
- 建 Python 项目结构
- 迁移现有代码到 novel_agent/ 包
- 加交互式 CLI
- 写完一章能存文件
- 验收：输入"写第5章：异乡风起"，产出并存文件

### 里程碑 2：有记忆（P1）
- 接入三层 Memory
- 能记住之前写的内容
- 加回放和评测
- 验收：连续写 3 章，第 3 章记得前 2 章内容

### 里程碑 3：可迭代（P2）
- A/B 对比
- 测试用例
- 多章节状态管理
- 验收：能对比不同配置效果，测试用例通过

---

## 8. 约束

- API Key 走环境变量，不硬编码
- 写完的章节存到 docs/修仙不像陪她看云/正文/ 下
- 运行日志存到 py/runs/ 下（保持和现有一致）
- 向量库存到 ./chroma_db（保持和现有一致）
- 不破坏现有 py/ 下的代码（学习成果保留）
