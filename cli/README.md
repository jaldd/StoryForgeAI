# Novel Agent CLI

命令行小说创作 Agent。**与具体小说解耦**：书名和小说目录都走配置，代码里不绑死任何一本书。

一句话需求 -> 自动走「查设定 -> 写草稿 -> 润色 -> 审稿」流程，写完存文件、记前文、可回放可评测。

## 安装

依赖 Python 3.11+。在 `cli/` 下安装（可编辑模式）：

```bash
cd cli
pip install -e .
```

## 配置

Agent 不知道你要写哪本小说，靠 `.env`（仓库根，已 gitignore）告诉它。参考 `cli/.env.example`：

```
ARK_API_KEY=你的火山密钥
NOVEL_NAME=你的小说名            # prompt 里用的显示名
NOVEL_DIR=/path/to/your/novel    # 小说内容根目录（仓库外）
```

`NOVEL_DIR` 指向的小说目录结构（小说不在代码仓库里）：

```
<NOVEL_DIR>/
  总纲.md 人物.md ...          # 设定（RAG 索引源）
  文风基准/1.txt                # 文风金标准
  正文/新/...                   # 人工正文
  正文/AI生成/...               # Agent 产出
  .agent/                      # 运行时（自动生成，跟小说走）
    runs/  chroma_db/  working_memory.json
```

模型默认 `glm-5.2`（`CLAUDE_MODEL` 可覆盖）。运行时默认放 `<NOVEL_DIR>/.agent/`，可用 `NOVEL_RUNS_DIR`/`NOVEL_CHROMA_DIR` 覆盖到别处。

## 运行

```bash
python -m novel_agent
```

进入交互式 REPL 后：

| 命令 | 作用 |
|------|------|
| `写第5章：异乡风起` | 走完整流程写一章，存文件并打分 |
| `index` | 把小说设定向量化建库（首次必做） |
| `replay run_xxx` | 回放某次写作过程 |
| `eval run_xxx` | 对某次写作打分 |
| `compare run_a run_b` | 对比两次写作效果 |
| `test run_xxx` | 规则断言测试 |
| `状态` | 查看当前写到第几章、角色状态、未回收伏笔 |
| `help / quit` | 帮助 / 退出 |

## 测试

```bash
cd cli
pytest                                          # 单元测试（不联网）
INTEGRATION_TEST=1 NOVEL_DIR=/path/to/novel pytest -m integration   # 真实 API 冒烟
```

## 规格与迭代

spec-kit 结构（仓库根）：

- `.specify/memory/constitution.md` - 项目宪法（跨 feature 的硬约束）
- `specs/novel-agent-cli/` - 本 feature 的 `requirements.md` / `design.md` / `tasks.md`

加新能力时，在 `specs/` 下新建 `<feature>/` 目录，走 requirements -> design -> tasks。
