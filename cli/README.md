# Novel Agent CLI

命令行小说创作 Agent，用于写《修仙不如陪她看云》。

一句话需求 -> 自动走「查设定 → 写草稿 → 润色 → 审稿」流程，写完存文件、记前文、可回放可评测。

## 安装

依赖 Python 3.11+。在 `cli/` 下安装（可编辑模式）：

```bash
cd cli
pip install -e .
```

## 配置

在仓库根目录建 `.env`（参考 `cli/.env.example`），至少填：

```
ARK_API_KEY=你的火山密钥
```

模型默认 `glm-5.2`，可用 `CLAUDE_MODEL` 覆盖。

## 运行

在**仓库根目录**执行（设定/正文/向量库路径都是相对仓库根的）：

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
| `状态` | 查看当前写到第几章、角色状态、未回收伏笔 |
| `help` | 帮助 |
| `quit` | 退出 |

## 测试

```bash
cd cli
pytest                       # 单元测试（不联网）
INTEGRATION_TEST=1 pytest -m integration   # 真实 API 冒烟（花钱）
```

## 目录

见 `spec.md`（规格说明）与 `tasks.md`（任务分解）。
