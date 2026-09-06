# 卷对齐落盘（volume-align）- 设计

> 对应需求：同目录 `requirements.md`（V1-V8）。
> 行号锚点基于 2026-09-05 代码（character-arc 完成态），实现时以函数名为准。

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| V1/V2 路径/命名/头行 | §3.1 save_chapter 对齐分支 |
| V3 覆盖语义 | §3.1（对齐分支不进后缀逻辑） |
| V4 番外回落 | §3.1（num 守卫） |
| V5 开关关闭零变化 | §3.1（分支前置条件） |
| V6 parse_chapter_file | §3.2 |
| V7 可发现性 | §2 + .env copy.example |
| V8 兼容 | §4 |

## 1. 总体设计

只动 `save_chapter` 一个落盘点 + `parse_chapter_file` 一个解析点 + 一个配置开关。
流水线/门禁/写后回路（伏笔/弧光/摘要/RAG 入库）全部零改动——它们消费
`save_chapter` 返回的路径，路径对了其余自然对。

```
写第38章：空
  └─ save_chapter（volume_align 开）
       ├─ 卷名 = Path(NOVEL_CHAPTER_SUBDIR).name        # 正文/第一卷 -> 第一卷
       ├─ 路径 = chapter_path / f"{卷名}-{num:02d}.md"   # 第一卷-38.md
       ├─ 头行 = f"## 第{cn_numeral(num)}章 {title}"      # ## 第三十八章 空
       └─ 直接覆盖（无 run_id 后缀）
```

## 2. 配置面（新增 1 个 env）

| 变量 | 作用 | 默认 | 解析 |
|---|---|---|---|
| `NOVEL_VOLUME_ALIGN` | 卷对齐落盘开关 | `0` | int，`!=0` 开（opt-in，现状零变化） |

前提（既有配置，不新增）：`NOVEL_CHAPTER_SUBDIR` 指到**当前卷目录**
（如 `正文/第一卷`），卷名从其末段派生——换卷只改这一处（与用户既有
`NOVEL_HUMAN_TEXT`「换卷时改这里」惯例同款）。

## 3. 详细设计

### 3.1 save_chapter 对齐分支（V1-V5）

```python
num, title = parse_chapter_task(task)
if num is not None and settings.volume_align:
    vol = Path(settings.chapter_subdir).name
    path = settings.chapter_path / f"{vol}-{num:02d}.md"
    try:
        cn = cn_numeral(num)
    except ValueError:
        cn = str(num)                    # >99 回落阿拉伯（V2）
    body = _strip_leading_title(final_chapter)   # 模型自带头行剥掉（含 ## + 中文数字形态）
    header = f"## 第{cn}章 {title}".rstrip() + "\n\n"
    写入 path（"w" 直接覆盖，V3）
    return path
# ---- 现状路径零改动（V5）----
```

- **覆盖语义**：对齐分支不进「同名加 run_id 后缀」逻辑；重写工作流里 git 是
  版本控制、run record 是第二份全文，双保险。
- **num=None 守卫**（V4）：番外类任务走不进分支，回落现状 run_id 命名。
- **头行剥重**：`_strip_leading_title` 的 `_CHAP_NUM` 已兼容中文数字 + `#`
  前缀（实测模型输出 `## 第三十八章 空` 被正确剥掉），落盘头行由本分支统一
  重写，格式唯一真源在代码。
- **cn_numeral 复用**：storage.py 内既有纯函数（1-99），零新依赖。

### 3.2 parse_chapter_file 卷模式（V6）

```python
_VOLUME_FILE_RE = re.compile(r"^(.+?)-(\d{1,4})$")   # 卷名-NN（懒匹配，锚定结尾）

def parse_chapter_file(path):
    stem = path.stem
    m = 既有「第N章-标题」正则.match(stem)
    if m: return (章号, 标题)          # 判定序在前：第05章-标题2 -> (5, "标题2")
    m = _VOLUME_FILE_RE.match(stem)
    if m: return (int(m.group(2)), "") # 第一卷-38 -> (38, "")
    return (None, stem)
```

- **判定序是关键**（D5）：既有格式先试，卷模式只兜不匹配的——「第05章-标题2」
  这类标题以数字结尾的文件名不会被卷模式误吃。
- 消费方 `_refresh_working_memory`（cli.py）只用章号，标题返回空串无影响；
  精修/重写卷文件存回后工作记忆刷新由此生效。

## 4. 已知局限与不动清单

**已知局限**（工作流约定或留 P1，不在本 feature 修）：

- **人工语料自我污染**：AI 章落进卷目录后，`NOVEL_HUMAN_TEXT` 指向该卷时，
  滚动文风注入与 AI 味基线会把 AI 文本当人工正文（自我强化）。**约定：重写
  第几卷，`NOVEL_HUMAN_TEXT` 就指向未重写的卷**（.env 注释写明）。
- **跨卷章号撞号**：伏笔/弧光/摘要按章号记账，卷一第 38 章与卷二第 38 章在
  系统里同号——换卷重写时同章覆盖清洗（F16/C15）会误抹上一卷条目。**约定：
  换卷时删 working_memory.json 重置**（重写工作流下伏笔本就卷内闭环）；
  卷前缀章号方案留 P1 视真实痛感再议。
- **`状态` 命令章节数含人工原稿**：chapter_path 指向卷目录后 glob 数出 60 个
  （含未重写原稿）。展示噪音，不改。
- **精修/重写/去AI 对卷文件的头行保真未验证**：这些命令读文件-处理-存回同
  路径，头行在内容里随 polisher 铁律（只改表达）应保留；真车用到时验证。

**不动清单**：流水线/门禁/写后回路；`NOVEL_CHAPTER_SUBDIR` 语义；批量连写
编排（消费 save_chapter 返回路径，自然继承）；`cn_numeral` 既有实现。

## 5. 测试策略（全程不联网）

- **test_storage.py**：对齐落盘（文件名/路径/头行/模型头行剥重）；覆盖（预置
  旧稿被替换、无后缀文件产生）；番外回落 run_id 命名；>99 回落阿拉伯头行；
  开关关 = 现状命名；parse_chapter_file 卷格式（(38, "")）、既有格式优先
  （标题2 不误判）、不匹配回落。
- **test_config.py**：默认 0；`NOVEL_VOLUME_ALIGN=1/0` 解析。
- **test_cli_write.py**：集成两例——对齐模式下 `_do_write` 落卷路径且头行
  正确；预置人工原稿被覆盖（同文件替换、目录内仅 1 个 md）。
- **回归**：`cli/` 下 `python -m pytest tests/ -q`，527 passed 基线零新增失败。

## 6. 决策表

| # | 决策 | 备选 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 卷名来源 | a) 独立 `NOVEL_VOLUME` 配置；b) subdir 末段派生 | **b** | 换卷只改一处；少一个旋钮；与 NOVEL_HUMAN_TEXT「换卷时改这里」惯例同款 |
| D2 | 覆盖语义 | a) 加 run_id 后缀；b) 直接覆盖 | **b** | 用户拍板：git diff 即比对是本 feature 的存在理由；git + run record 双保险 |
| D3 | 文件名带不带标题 | a) `第一卷-38-空.md`；b) `第一卷-38.md` | **b** | 对齐人工约定；重写换标题文件名不动，diff 干净 |
| D4 | 头行格式 | a) 沿用 `第38章 空`；b) `## 第三十八章 空` | **b** | 对齐人工约定（## + 中文数字）；cn_numeral 现成 |
| D5 | parse_chapter_file 判定序 | a) 卷模式先；b) 既有格式先 | **b** | 「第05章-标题2」类文件名会被卷模式误吃（标题数字结尾） |
| Z1 | 默认关（opt-in） | — | — | 现状零变化；卷结构是这本小说的约定不是通用默认 |
| Z2 | 自我污染/撞号用工作流约定，不改代码 | — | — | 代码级方案（git 状态感知/卷前缀章号）复杂度不成比例，先约定后视痛感 |
