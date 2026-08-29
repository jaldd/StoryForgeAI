# Novel Agent CLI 迭代路线图

> 状态：**执行中**（2026-08-28 规划，同日代码复核修订一轮；2026-08-29 阶段 0 完成，同日阶段 1 开工：`quality-gate` spec 三件套已建、实现未开工）
> 开工规则：每个阶段按 spec-kit 流程在 `specs/` 下新建 `<feature>/{requirements,design,tasks}.md`，遵循 `.specify/memory/constitution.md`。
> 排序原则：**产出质量优先于产出速度**。AI 味重、审核不可信的产出，写得再快也是废品产能。
> 门禁总原则：**机器拿不准时交给人；无人可交时才 fail-closed**。REPL 里人是兜底；批量/API 模式没有人，必须 fail-closed。

---

## 总览

| 阶段 | 主题 | 一句话 | 状态 |
|------|------|--------|------|
| 0 | 修硬伤+快赢 | 修三个地基问题 + 局部精修/接线/清理/模型可换/流水线补漏 | 完成（0.1-0.8；0.7 真实环境人工验收待做） |
| 1 | 质量闭环 | 审核维度化 + 学人味 + 去 AI 味，质量能被度量、被门禁 | 进行中（1.1-1.4 `quality-gate` spec 就绪；1.5-1.6 `style-loop` 后行） |
| 2 | 吞吐 | 流式输出 + 批量连写 | 未开工 |
| 3 | 长线记忆 | 伏笔追踪 + 角色弧光 + planner 回归 | 未开工 |
| 4 | 远期 | 多模型 fallback（Java 外壳化已暂缓） | 未开工 |

**横切约束（全阶段适用）**

- **token 预算意识**：当前一章约 5-6 次 LLM 调用。阶段 1 的去 AI pass、阶段 2 的批量连写都会乘上去；预算按 token 算不按次数算（writer 每次都带全套检索+exemplar+工作记忆的大输入）。1.6 的重写只传问题句，不传整章。
- **解耦原则延续**：凡随小说走的配置（铁律/词表/阈值）一律放 `NOVEL_DIR`，代码仓库零小说名。

**已有可复用资产**：`.claude/skills/novel-style-check/SKILL.md` 手工定义了 6 个文风检查维度 + 8 条硬规则 + 体检报告格式。阶段 1 把它生产化进 CLI 并去小说耦合。注意其 8 条硬规则要分家：**称呼红线/词黑名单/句长/独白行数/比喻词密度是机械可查的；语义级比喻判断、视角越界只有 LLM 能做**（归 1.1 的维度）。

---

## 阶段 0：修硬伤（快速清账，不起新 feature）

### 0.1 审稿解析失败静默放行 -> 交给人

- **现状**：`parse_review` 四级解析全部失败时返回 `True`（`agent.py` 兜底分支）。审稿人返回一段散文或被截断的 JSON 时，稿件**静默过审**--审稿在最坏情况下不存在。
- **做完后**：解析失败不再默认通过。REPL 模式：显著警告 + 人工确认存/弃（人是兜底）。强制定稿逃生门保留（防死循环），但必须带警告 + run 日志留痕。无人模式（未来批量/API）：fail-closed 不存盘。
- **与 1.4 是同一门禁哲学的两端，设计时一起定接口**。
- **动哪里**：`agent.py` 的 `parse_review` / `_reviewer`；`tests/test_agent.py` 补用例。
- **验收**：mock 构造"审稿返回非 JSON"场景，稿件不会静默过审，日志可见。

### 0.2 铁律硬编码 -> 抽到 NOVEL_DIR

- **现状**：`prompts.py` 的 `RULES` 写死了具体小说的铁律（男主不取名/女主叫云依/天气线…），polisher/reviewer 的 system prompt 里也硬编码"男主始终用他、女主叫云依"。换一本书这套铁律全是错的。违反宪法 §2"小说解耦"。
- **做完后**：`NOVEL_DIR` 下放一个铁律文件（如 `写作铁律.md`，路径可配），CLI 启动时读入，注入 writer/polisher/reviewer 的 system prompt。代码仓库里 grep 不到"云依"。
- **动哪里**：`prompts.py`（RULES 从常量变为参数）、`config.py`（新增铁律文件路径）、`cli.py` 的 `_build_agent`（加载注入）、`agent.py`（writer 指令里散落的小说硬规则一并收编，如"不要解释风代表什么"）。
- **验收**：新建一个只含铁律文件的空小说目录，写一章，prompt 中铁律内容来自文件而非代码。

### 0.3 写完自动入库（增量索引第一块）

- **现状**：`_do_write` 存章节后不进 Chroma；只有精修/重写命令会 `rag.add_document`。writer 的"前文参考"检索永远只有手动 `index add` 的内容，AI 写的章节互相看不见。
- **已排除的伪问题**：与 `index rebuild` 的 id **不冲突**--rebuild 用 `c0..cN` 连续 id，`add_document` 用 `{文件名}_{i}`，rebuild 不会清掉章节块，两通道天然共存。
- **真问题（反向）**：rebuild 从不删除陈旧块--设定文档删了，旧块还留在库里。属数据卫生问题，可与本项解耦延后处理（见开放问题 1）。
- **做完后**：写完存盘后自动把该章 upsert 进向量库，第 N+1 章的"前文参考"能检索到第 N 章真实正文。
- **动哪里**：`cli.py` 的 `_do_write`；`rag.py` 的 `add_document`（确认章节元数据 type=chapter）。
- **验收**：写第 N 章后向量库块数 +1；写第 N+1 章时检索能命中第 N 章；rebuild 后章节块仍在、仍可检索。

### 0.4 局部精修（快赢）

- **现状**：`精修`/`重写` 都作用于整章。只想改一小段时也得整章过流水线--好段落陪着返工、有被润坏的风险（字数保护只看长度不看内容），token 也按整章付。
- **做完后**：新命令 `改 <文件>`：列出段落编号（空行切块，`---` 与章节头跳过编号但保留）-> 选段（如 `3` / `3-5` / `3,7`）-> 只送选区 + 前后各一段上下文给 polisher，要求只返回选区 -> 按段落**区间**整块回填（其余部分逐字节不变）-> 回填前 diff + y/n 确认 -> 存回后该文件重新入索引。选区级 token，单次调用。
- **局部模式跳过 reviewer**：人选段 + diff + 确认，人就是门禁（符合门禁总原则）。
- **复用**：产出"选区+上下文 -> 改写 -> 回填"工具，1.6 的去 AI pass（自动版：checker 找问题句）直接复用这套管线。
- **动哪里**：`cli.py`（新命令 + 段落列表/选择解析）、`agent.py` 或新 helper（选区润色）、`rag.add_document`（回填后）。
- **验收**：改 3-5 段后其余段落逐字节不变；`---` 与章节头保留；差异展示只含选区。

### 0.5 exemplar 语料接线（从 1.3 前置任务提前）

- **现状**：SKILL.md 显示文风基准有 `1.txt~14.txt` 十四个文件，但 `cli.py` 只接**单个** exemplar 路径（`settings.exemplar_full`）。若 `NOVEL_DIR` 实有多文件，则其余金标准从未参与--当前所有产出的文风锚定单样本。（注：README 目录示例只写了 `1.txt`，14 个是 SKILL.md 旧路径时代的说法，实情待查。）
- **做完后**：先查清实情（文件数/体积，5 分钟）。若多文件：加载器升级为目录级，**注入带 token 上限**（超限按顺序截断或抽样，全量塞 writer 会爆）；语料清单进 `状态` 命令。若仅 1 个文件：确认无遗漏即可，1.3 走降级策略。
- **动哪里**：`config.py`（exemplar 目录化）、`prompts.load_exemplar`、`cli._build_agent`、`_do_status`。
- **验收**：`状态` 显示基准文件数与总字数；writer 的 exemplar 注入有 token 上限控制。

### 0.6 rebuild 陈块清理（从开放问题提前，定性为 bug）

- **现状**：rebuild 只 upsert `c0..cN` 不清旧块。设定文档**删除/改名/缩块**后陈块残留且仍可检索--RAG 会返回已不存在的设定，属数据正确性 bug，污染随 rebuild 累积且难回溯。
- **修法（不是全清）**：rebuild 维护 manifest（记录本次写入的 id 清单），下次 rebuild 先精确删这份清单再 upsert--覆盖删除/改名/缩块三种陈化。**不得清掉章节块**（0.3 自动入库与手动 add 的块不受影响）。可加 source 文件存在性扫描兜底手动 add 的陈块。
- **动哪里**：`rag.build_index`（manifest 读写 + 清理）。
- **验收**：删一个设定文件后 rebuild，该文件 source 的块数为 0；章节块数不变。

### 0.7 模型来源可换（chat provider 解耦 + 按角色路由）

- **现状**：chat 全链路锁死火山单一来源。`base_url` 是写死的默认值且 `get_settings()` 不读任何环境变量（换商必须改代码）；一个 `LLMClient` 伺候 writer/polisher/reviewer/摘要/评分全部角色。连暴力 hack 都不通：把 `ARK_API_KEY` 换成别家 key，写章时 RAG 的 embedding（同一个 key + 火山 embed_url）当场崩。
- **做完后**：三层。
  1. **provider 可换**：`LLM_BASE_URL`/`LLM_API_KEY` 接 env（key 默认回落 `ARK_API_KEY` 兼容现状）；embedding 配置独立不动（火山）。SenseNova（`api.sensenova.cn/compatible-mode/v2`）与 Kimi 官方（`api.moonshot.cn/v1`）均 OpenAI 兼容，`LLMClient` 调用代码零改动。
  2. **按角色路由**：`WRITER_BASE_URL`/`WRITER_API_KEY`/`WRITER_MODEL`（空=回落主配置）-> `NovelAgent` 增 `writer_llm` 注入，writer/polisher 走它，审稿/摘要/评分仍走主配置。写作是 token 大头，路由到免费模型收益最大。
  3. **行为参数可调**（调教实验用，配 `compare` 做 A/B）：
     - `NOVEL_TEMPERATURE`：仅覆盖**生成类**调用（writer/polisher/局部精修）的温度；审稿/评测保持代码内固定值（审稿要稳定出 JSON，调飘了实验全是噪音）；
     - `NOVEL_LLM_EXTRA`：JSON 原样透传给 chat 请求体的额外参数（各家特有参数直接写进去，代码不需要认识它）。真实用例：Kimi-K3 顶层参数 `reasoning_effort`（low/high/max 三档，**默认开深度推理且默认 max**）-> 配 `NOVEL_LLM_EXTRA={"reasoning_effort": "low"}` 即调档，零代码改动。**不逐项建配置**--各家参数名不同，透传一条路通吃，换 DeepSeek 或任何新厂家（凡 OpenAI 兼容）都不改代码。
- **抽象形状（轻量策略层）**：OpenAI 兼容协议本身就是策略抽象（同一段代码不同参数=不同策略），**不上** Provider 抽象基类/策略注册表/插件机制那套。实体就两个：`llm.py` 内 `ModelProfile` dataclass（base_url/api_key/model/temperature/extra）+ `load_profiles()`（env 解析出 default + 角色覆盖）。“插拔模型”= 改 `.env` 一行角色指向。
- **前置：修宪**。宪法 §2 技术栈为硬约束，LLM 行锁了火山 base_url；引入第二来源（哪怕只给写作角色）需先改 §2 并同步相关 spec。与阶段 4 的多模型 fallback 是两回事：那是故障兜底，这是成本路由。
- **换模型的坑**：宪法 §4 的 glm-5.2 推理预算坑要按新模型重新验证（Kimi K3 亦为推理型，**默认 max 档深度推理，写小说场景通常应降 low 档**，max 档思考 token 会挤占输出预算，`max_tokens` 语义必须实测）；**开深度思考后部分模型返回带思考块文本（思考标签包裹的内容），输出清洗要多剥一层**（参考现有 `_strip_code_fence` 的做法），不剥会直接进章节文件；免费额度与模型名以 SenseNova / Kimi 控制台实际为准。
- **动哪里**：`config.py`（env 接线 + 字段）、`agent.py`（`writer_llm`）、`cli._build_agent`、`.env copy.example`、宪法 §2、run 记录的 config（体现各角色所用模型）。
- **验收**：`.env` 配 SenseNova/Kimi 端点 + key，写一章成功且 run 记录能看出 writer 用了新模型；审稿/评分仍走火山；RAG embedding 不受影响。

### 0.8 流水线数据流补漏（四断点 + director 退役）

- **现状**：四 agent 名不副实 + 四个数据流断点。
  - director 是空壳（只转发任务零决策），refine/rewrite 早已绕开它；
  - writer 的构思按 `===` split 后被丢弃--polisher 盲润、reviewer 无验收基准、replay 看不到当时意图；
  - reviewer `with_prior=False` 且不注入 WorkingMemory，却要审伏笔/时间线一致性（审它看不见的东西）；
  - 长度控制三处打架：writer 写死"约200字"（测试残留）、`polisher_system` 的 `target_words=1500` 是死参数（未进 prompt）、实际产出 ~300 字；
  - 第 5/6 个 agent 藏在 cli 层（plot summary / eval 裸调），且 refine/rewrite 路径不更新工作记忆。
- **做完后**：
  - 删 director，流水线三角色（writer/polisher/reviewer）；planner 作为新角色留待阶段 3 回归（见 3.3）；
  - 构思进 `PipelineState` 并传递：喂 polisher（保意图）、喂 reviewer（作验收基准）、进 run 日志（replay 可见）；
  - reviewer 注入 `_working_context()`（伏笔/时间线维度有数据可查）；
  - 长度目标从任务/配置传入 writer 与 polisher prompt（删写死的"约200字"，接活 `target_words`）；
  - plot summary / eval 收编出 cli 裸调；refine/rewrite 后同步更新工作记忆。
- **动哪里**：`agent.py`（删 director、构思传递、reviewer 注入、长度）、`state.py`（构思字段）、`prompts.py`（`target_words` 接活）、`cli.py`（LLM 角色归位）、`storage.py`/`harness.py`（run 记录含构思）。
- **验收**：run 日志含 writer 构思；reviewer 的伏笔维度能引用前文；同一任务可配出 2000+ 字章节；精修后工作记忆摘要刷新。

---

## 阶段 1：质量闭环（拆两个 feature：`quality-gate` -> `style-loop`）

前置依赖：阶段 0 完成（有洞的地基上建审核等于白建）。
拆分拍板（2026-08-29，开放问题 3 关闭）：先 `quality-gate`（1.1-1.4：审核维度化 + 规则硬 gate + AI 味量化 + 门禁统一，spec 见 `specs/quality-gate/`），后 `style-loop`（1.5-1.6：学人味 + 去 AI）。

### 1.1 审核维度化

- **现状**：reviewer 只返回 `{"pass": bool, "reason", "issues"}`。六个审查维度全靠模型自觉混在一个结论里，没有分维度分数；打回意见是一坨文字，writer 不知道优先修哪个。
- **做完后**：reviewer 返回分维度分数（人物一致/文风/连贯/伏笔/剧情 + **语义级比喻密度** + **视角越界**--这两项是机械检查做不到、只有 LLM 能做的），每个问题**引用原文句子 + 给出改法**。
- **打回路由：不做**。打回目标统一为 fixer（单一目标），feedback 里带维度信息指路（如"文风/AI 味问题=只改表达不动剧情"）。按维度路由到不同 agent 收益存疑（writer 重写后本来就会重过 polisher），先不做，等数据说话。
- **打回机制已拍板（2026-08-29）**：修复式打回--保住 draft、按意见只改问题处，不再从零重写。新增 fixer 角色按 quote 定位问题段落、复用 0.4 回填管线，`_reject_target` 机制随之退役。详见 `specs/quality-gate/design.md`。
- **动哪里**：`prompts.reviewer_system`（结构化 schema）、`agent._reviewer`、`state.py`（存维度分）、`harness.run_tests`（断言维度字段）。
- **验收**：打回意见包含原文引用；run_tests 断言维度分存在且在 1-5 范围。

### 1.2 规则硬 gate（机械检查，不烧 LLM）

- **现状**：无任何确定性检查。SKILL.md 的 8 条硬规则只在手工用 Claude 时执行，且引用路径已随小说外迁失效。
- **做完后**：polisher 之后先跑一轮**纯代码检查**，收窄为确定性可做的五项：AI 高频词黑名单（一丝/不禁/眼眸/嘴角勾起一抹弧度…）+ 称呼红线 + 句长分布 + 独白行数 + **比喻词密度**（像/仿佛/宛如/如同等标记词的相邻句命中率--词法代理，不是语义级比喻检测）。命中即打回并指出具体词句，零 LLM 调用。词表放 `NOVEL_DIR`。
- **明确不做**：语义级判断（这句话是不是比喻、视角是否越界）不进机械检查，归 1.1。
- **动哪里**：新模块 `checker.py`；`agent.py` 流水线在 reviewer 前插入。
- **验收**：含黑名单词的稿件被拦截并指出位置；正常稿件无误伤。

### 1.3 AI 味量化

- **前置任务（已提前到 0.5）**：全部基准语料的接线与实情确认见 0.5；1.3 直接消费其产出的语料清单。
- **用途分家**：统计基准 = 全部基准文件 + 人工正文滚动样本（见 1.5）；prompt 注入 = 精选（全量塞 writer 会爆 token）。
- **做完后**：产出"AI 味浓度"分数--高频 AI 词命中率 + 句长分布偏移 + 词频偏移，均以基准语料为基线。语料不足则降级为只用黑名单+句长。`eval` 输出多一维，`compare` 能对比谁更"像人写的"。是 1.6 的验收标尺。
- **动哪里**：`checker.py`（统计部分）；`harness.evaluate` / `compare`。
- **验收**：明显 AI 味重的稿和基准语料各测一次，分数显著区分开。

### 1.4 门禁统一（与 0.1 合并设计）

- **现状**：两套脱节--`parse_review` 失败 fail-open 静默放行（0.1）；四维评分（EVALUATOR_RUBRIC）只打印不 gate，低分章节照常存盘覆盖。
- **做完后**：单一门禁。审稿不可解析 -> 不自动存盘，REPL 提示人工决定存/弃。评分门禁默认用**整体加权分**（各维权重可配），**不默认"任一维 < 3"**--LLM 自评分方差大、维度间尺度不可比（伏笔维的 3 分≠文风维的 3 分），且标题维**不参与门禁**（坏标题事后可改，rubric 已有"建议标题"机制）。分维阈值待历史数据校准后再收紧。
- **阈值校准**：默认阈值先在既有 run 记录上回测误伤率再上线（注：评委分数不在 run 日志里，回测需真实评委调用、非零成本，按 run_id 缓存缓解，见 quality-gate design 已知局限）；阶段 2 批量开闸前复核一次。
- **批量模式推论**：2.2 的 `--auto` 模式没有人确认，必须先定义低分章去向--隔离到待审清单后继续，还是中断。这是 2.2 的前置设计题。
- **动哪里**：`cli._do_write` / `_refine_postprocess`；`config.py`（阈值）。
- **验收**：模拟低分 run，章节文件未自动写入。

### 1.5 动态文风注入（学人味）

- **现状**：只有"去 AI 味"的治疗思路，没有"学人味"的预防思路。`正文/新/` 下的人工正文随写作增长，是比静态 exemplar 丰富得多、且动态的文风样本，目前完全没被用（`index rebuild` 排除整个正文目录）。
- **做完后**：writer 的文风输入 = 静态 exemplar（精选）+ **滚动最近 N 章人工正文**（捕捉文风漂移）。
- **机制**：不用语义检索选段（主题相似≠文风相似），用滚动窗口 + 固定精选，简单确定。
- **动哪里**：`cli._build_agent`、`config.py`（人工正文目录与 N 可配）。
- **验收**：写第 N 章时 writer prompt 含最近 2-3 章人工正文片段。

### 1.6 去 AI 润色 pass

- **现状**：polisher 只管"流畅有文采"，不知道 AI 味为何物，有时反而往 AI 味方向润。
- **做完后**：针对 1.2/1.3 检出的问题句，专门一轮"人味重写"--情节不动只改表达；**只传问题句及上下文，不传整章**（token 预算；回填管线复用 0.4）。重写后复检，AI 味分必须下降才接受。
- **动哪里**：`prompts.py` 新增 de-AI prompt；`agent.py` 增加 refine 变体。
- **验收**：重写后 AI 味分下降；run_tests 断言关键情节要素未变。

---

## 阶段 2：吞吐（feature：`throughput`）

### 2.1 流式输出
- **现状**：writer/polisher 各一次完整调用（约 30 秒/次），全程只看 spinner。
- **做完后**：`llm.chat` 支持 `stream=True`，REPL 边写边打印，便于中途发现跑偏直接打断。
- **动哪里**：`llm.py`、`agent.py`、`cli.py`。

### 2.2 批量连写
- **现状**：只能一章一章手敲命令。
- **做完后**：`写第5-10章：...`，章间自动更新工作记忆 + 入库。**默认每章过目确认再继续**（防跑偏累积，且人在环 = 1.4 门禁的天然兜底）；`--auto` 跳过确认，但必须先按 1.4 推论定义低分章去向。
- **动哪里**：`cli.py` 新命令解析、循环编排。
- **验收**：一条命令连写 3 章，工作记忆 current_chapter 连续递增，每章入库。

---

## 阶段 3：长线记忆（feature：`long-memory`）

### 3.1 伏笔自动追踪
- **现状**：`WorkingMemory.unresolved_foreshadowing` 存在但没有自动更新通道，伏笔全靠人脑记。
- **掂量**：共写模式下这是**结构性刚需**--伏笔丢失是结构问题，AI 味是表面问题，结构烂了表面再好也没用。字段已在，缺的只是抽取回路，可提前为独立小 feature（见开放问题 5）。
- **做完后**：每写完一章，LLM 抽取本章埋下的伏笔更新 unresolved 列表；writer prompt 注入"待回收伏笔"提示；回收了则自动出列。
- **动哪里**：`memory.py`、`agent.py`/`cli.py`（写后处理）、新 prompt。

### 3.2 角色弧光分析
- **现状**：`docs/spec/technical-spec.md` 里的 CharacterArcPlanner 未落地（domain 层已有 Java 版 `CharacterArcAnalyzer` 可参考逻辑）。
- **做完后**：分析已有正文的角色状态变化曲线，写新章前提示"该角色当前弧光阶段"，防人设漂移。
- **动哪里**：新分析模块 + writer 上下文注入。

### 3.3 planner 角色（director 的回归形态）

- **背景**：0.8 删除空壳 director 后，编排入口以 planner 回归--不是恢复转发器，而是真决策角色。
- **做完后**：汇合 3.1 伏笔、3.2 弧光与长度目标，产出章节节拍（先于 writer）；writer 按节拍写，reviewer 拿节拍当验收基准。构思（0.8 已保留传递）从 writer 前移到 planner，一次生成、处处消费的数据流闭环。
- **动哪里**：`agent.py` 新角色 + `state.py`（节拍字段）。

---

## 阶段 4：远期

- **多模型 fallback**：单模型挂了/降智时兜底。若 0.7 已修宪放开多来源，这里只剩加故障切换逻辑。
- **Java 外壳化**（暂缓，2026-08-28 确认先不做）：定位备忘--Python agent 是大脑（创作能力），Java 四层是外壳（项目管理/REST/SSE），方向是 Java 调 Python 而非重写；届时需先定跨语言契约（流式协议、run 记录 schema）。

---

## 开工前待确认的开放问题

1. **词表格式**（已关闭，2026-08-29）：用独立 JSON（`质量规则.json`，与 0.2 的写作铁律.md 分开），承载词表/阈值/AI 味锚点/门禁权重。见 `specs/quality-gate/design.md` §2。
2. **批量连写默认节奏**：默认每章过目（推荐）还是默认全自动？
3. **阶段 1 拆分**（已关闭，2026-08-29）：拆两个--`quality-gate`（1.1-1.4）先行，`style-loop`（1.5-1.6）后行。
4. **伏笔追踪是否提前**：作为独立小 feature 插在阶段 1 之前/之后，还是维持阶段 3 不动（见 3.1）？
