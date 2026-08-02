# 需求规格：Novel Agent CLI

> Feature: `novel-agent-cli`
> 状态：P0+P1+P2 已实现并端到端验证通过（2026-08-02）
> 遵循 `.specify/memory/constitution.md`。

---

## 1. 项目目标

做一个**与具体小说解耦**的命令行小说创作 Agent，可落地用于长篇创作（书名/目录配置驱动，不绑死某一本书）。

### 核心价值
- 输入一句话需求，自动走「查设定 -> 写草稿 -> 润色 -> 审稿」流程
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

2. 输入"replay run_xxx"   -> 回放某次写作过程
3. 输入"eval run_xxx"      -> 对某次写作打分
4. 输入"compare run_a run_b" -> 对比两次写作效果
5. 输入"状态"             -> 查看当前写到第几章、角色状态、未回收伏笔
6. 输入"quit"             -> 退出
```

---

## 3. 功能列表

### P0（必须做）
- [x] 交互式 CLI（while 循环，持续对话）
- [x] MultiAgent 流程（director -> writer -> polisher -> reviewer）
- [x] RAG 检索（复用 `py/rag_volcano.py`，生产化为 `RAGStore`）
- [x] 写完自动存文件到 `<NOVEL_DIR>/正文/AI生成/`
- [x] 运行日志（JSON，存 `py/runs/`）

### P1（应该做）
- [x] Memory 三层（复用 `py/agent_memory_volcano.py`）
- [x] 回放功能（replay）
- [x] LLM 打分评测（eval）
- [x] 工作记忆跨进程持久化（连续写多章记得前文）

### P2（可以做）
- [x] A/B 对比（compare）
- [x] 测试用例（test，规则断言）
- [x] 多章节连续写作（记住写到第几章）
- [x] 状态查看命令

---

## 4. 验收标准

### P0（里程碑 1：能跑）
- 输入「写第5章：异乡风起」-> 检索 -> 草稿 -> 润色 -> 审稿 -> 存文件 -> 打印评分。
- **已验收**：草稿 283 字 -> 润色 340 字 -> 审稿通过 -> 存 `第05章-异乡风起.md` -> 评分 4/5/4。

### P1（里程碑 2：有记忆）
- 连续写 3 章，第 3 章记得前 2 章；replay/eval 可用。
- **已验收**：第5/6/7 章连写，工作记忆 `current_chapter` 5->6->7 跨进程延续，后章 writer 注入前章**真实剧情摘要**；replay/eval 均可用。

### P2（里程碑 3：可迭代）
- compare 对比两 run；run_tests 规则断言；状态命令；多章状态管理。
- **已验收**：compare 并排对比 temperature/字数/铁律；run_tests 三维断言；状态命令显示进度+伏笔。

---

## 5. 约束（来自宪法 §2-3）

- API Key 走环境变量（`ARK_API_KEY`），不硬编码。
- **书名与小说目录不硬编码**：走 `NOVEL_NAME`/`NOVEL_DIR` 配置；代码仓库不得出现具体小说名。
- 小说内容与运行时都在仓库外的 `NOVEL_DIR` 下（章节存 `<NOVEL_DIR>/正文/AI生成/`，运行时存 `<NOVEL_DIR>/.agent/`）。
- 不破坏 `py/` 下的代码（学习成果保留）。
- glm-5.2 短输出调用 `max_tokens` ≥ 1024（宪法 §4）。
