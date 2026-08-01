# Novel Agent CLI - 任务分解

> 对应 `spec.md`。每任务一次 commit。

## P0（必须做）

- [x] **T1 清理 Java**：删 `cli/pom.xml` + `cli/src/`；根 `pom.xml` 移除 cli 模块。
- [x] **T2 项目骨架**：`pyproject.toml`、`novel_agent/` 包、最小 REPL、README、`.env.example`。
- [ ] **T3 config + prompts**：`config.py`（Settings）、`prompts.py`（铁律/EXEMPLAR/system prompt）。
- [ ] **T4 llm.py**：`LLMClient` + `call_model`（重试/清洗/可注入）。
- [ ] **T5 rag.py**：`RAGStore`（惰性初始化，从 `py/rag_volcano.py` 迁移）。
- [ ] **T6 memory.py**：三层记忆（从 `py/agent_memory_volcano.py` 迁移）。
- [ ] **T7 state.py + agent.py**：`PipelineState` + director/writer/polisher/reviewer + `run()`。
- [ ] **T8 storage.py**：章节落盘 + run 日志落盘。

## P1（应该做）

- [ ] **T9 harness.py**：replay/compare/evaluate/run_tests（从 `py/multiagent_novel.py` 迁移）。
- [ ] **T10 cli.py 完整 REPL**：写章 / replay / eval / compare / 状态 / index / help / quit。

## P2（可以做）

- [ ] **T11 tests**：单元测试（mock LLM）+ integration 冒烟。
- [ ] **T12 端到端验证**：建索引、跑一章、replay/eval/compare 串一遍。

## 验收标准

- **P0**：输入「写第5章：异乡风起」→ 检索→草稿→润色→审稿→存文件→打印评分。
- **P1**：连续写 3 章，第 3 章记得前 2 章；replay/eval 可用。
- **P2**：compare 对比两 run；run_tests 规则断言；状态命令；多章状态管理。
