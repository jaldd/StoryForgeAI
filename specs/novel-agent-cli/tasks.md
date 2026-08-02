# 任务分解：Novel Agent CLI

> Feature: `novel-agent-cli`
> 对应 `requirements.md` / `design.md`。T1–T12 已完成。底部有未来迭代入口。

---

## P0（必须做）

- [x] **T1 清理 Java**：删 `cli/pom.xml` + `cli/src/` + `cli/target/`；根 `pom.xml` 移除 `<module>cli</module>` 与 dependencyManagement 中 cli 项。
- [x] **T2 项目骨架**：`pyproject.toml`、`novel_agent/` 包、`__main__`/`cli` 最小 REPL、`README`、`.env.example`；`pip install -e .` 后 `python -m novel_agent` 可启动。
- [x] **T3 config + prompts**：`config.py`（Settings）、`prompts.py`（铁律/EXEMPLAR/system prompt）。
- [x] **T4 llm.py**：`LLMClient` + `chat`（重试/清洗/可注入 client）。
- [x] **T5 rag.py**：`RAGStore`（惰性初始化，从 `py/rag_volcano.py` 迁移；修复 embedding data 格式）。
- [x] **T6 memory.py**：三层记忆（ShortTerm/WorkingMemory/LongTerm，从 `py/agent_memory_volcano.py` 迁移）。
- [x] **T7 state.py + agent.py**：`PipelineState` + director/writer/polisher/reviewer + `run()` 编排。
- [x] **T8 storage.py**：章节落盘 + run 日志 + 工作记忆持久化。

## P1（应该做）

- [x] **T9 harness.py**：replay/compare/evaluate/run_tests（从 `py/multiagent_novel.py` 迁移）。
- [x] **T10 cli.py 完整 REPL**：写章 / index / replay / eval / compare / test / 状态 / help / quit；写后生成剧情摘要存工作记忆。

## P2（可以做）

- [x] **T11 tests**：40 个单元测试（mock LLM，不联网）+ integration 冒烟（`@pytest.mark.integration`，默认 skip）。
- [x] **T12 端到端验证**：建索引、真实写 3 章（5/6/7）、replay/eval/compare 串一遍；修两个 bug（embedding data 格式、glm-5.2 max_tokens）。

---

## 验收结果

- **P0** ✅：写第5章 -> 草稿283字->润色340字->审稿通过->存文件->评分4/5/4。
- **P1** ✅：连写5/6/7章，工作记忆 5->6->7 跨进程延续，后章注入前章真实摘要；replay/eval 可用。
- **P2** ✅：compare 并排对比；run_tests 三维断言；状态命令；多章状态管理。
- **测试** ✅：40 passed，1 integration deselected。

---

## 未来迭代入口（新 feature 在 `specs/` 下新建目录）

> 每项做成独立 feature：`specs/<feature>/{requirements,design,tasks}.md`，遵循宪法。

候选：
- **角色弧光分析**：把 `docs/spec/technical-spec.md` 里的 CharacterArcPlanner 落地成 Python 工具，接进 agent。
- **增量索引**：写完一章自动把新章节 upsert 进 Chroma（当前需手动 `index rebuild`），让 RAG 检索到前几章 AI 正文。
- **伏笔自动追踪**：写完一章用 LLM 抽取埋下的伏笔，更新 `WorkingMemory.unresolved_foreshadowing`，并在后续章节提示回收。
- **流式输出**：writer/polisher 改流式（`stream=True`），边写边打印。
- **多模型 fallback**：接第二个模型做失败兜底（宪法 §2 当前单模型）。
- **Web/服务化**：把 cli 的 agent 层包成 SSE API（对齐 Java 宏愿景的 REST+SSE）。
