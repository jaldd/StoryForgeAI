# 0.7 模型来源可换（chat provider 解耦 + 按角色路由）- 需求规格

## 1. 背景

当前全部 chat 调用锁死火山方舟单一来源：`Settings.base_url` 硬编码
`https://ark.cn-beijing.volces.com/api/coding/v3`，默认模型 `glm-5.2`，鉴权统一走
`require_api_key()`（读 `ARK_API_KEY`）。宪法 §2 把这个硬编码列为技术栈硬约束，即
「换模型来源」在当前是修宪级变更。且存在一个暴力 hack 都不通的死结：把 `ARK_API_KEY`
换成别家 key，写章时 RAG 的 embedding（同一个 key + 火山 embed_url）当场崩--chat 与
embedding 的鉴权必须解耦。

阶段 0.7 规划要求三层能力：

1. **provider 可换**：`LLM_BASE_URL` / `LLM_API_KEY` 接入 env（key 回落 `ARK_API_KEY`
   兼容现状），embedding 配置独立不动。SenseNova（`api.sensenova.cn/compatible-mode/v2`）
   与 Kimi 官方（`api.moonshot.cn/v1`）均 OpenAI 兼容，`LLMClient` 调用代码零改动。
2. **按角色路由**：`WRITER_BASE_URL` / `WRITER_API_KEY` / `WRITER_MODEL`（空=回落
   主配置）-> `NovelAgent` 增 `writer_llm` 注入；writer/polisher 走它，审稿/摘要/评分
   仍走主配置。写作是 token 大头，路由到免费模型收益最大。
3. **行为参数可调**：`NOVEL_TEMPERATURE`（仅覆盖生成类调用的温度；审稿/评测保持代码内
   固定值，因其要稳定出 JSON）、`NOVEL_LLM_EXTRA`（JSON 原样透传给 chat 请求体的额外
   参数；真实用例：Kimi-K3 顶层参数 `reasoning_effort` 调档，零代码改动）。

抽象形状（早期规划已定，不在本 feature 讨论范围）：**轻量策略层**。OpenAI 兼容协议本身
就是策略抽象（同一段代码不同参数=不同策略），不上 Provider 抽象基类/策略注册表/插件
机制。实体就两个：`llm.py` 内 `ModelProfile` dataclass + `load_profiles()`。

与阶段 4 的多模型 fallback 是两回事：那是故障兜底，这是成本路由。

## 2. 术语

| 术语 | 含义 |
|---|---|
| 主配置 / default profile | 未做角色覆盖时所有 chat 调用共用的 base_url/api_key/model |
| 角色配置 / writer profile | 仅 writer/polisher/局部精修使用的覆盖配置 |
| 生成类调用 | writer / polisher / partial_refine 三处 chat 调用（温度可被 NOVEL_TEMPERATURE 覆盖） |
| 审稿类调用 | _reviewer / summarize_chapter / is_better / harness.evaluate 等需稳定结构化输出的调用 |
| 思考块 | 深度思考模型在正文外返回的、由思考标签包裹的推理文本（不剥会进章节文件） |
| ModelProfile / load_profiles | llm.py 内新增的轻量策略层实体，见 design §3 |

## 3. 需求（EARS 验收标准）

### 3.1 provider 可换

**A1** 当环境变量 `LLM_BASE_URL` 被设置为任一 OpenAI 兼容端点 URL 时，系统应将该 URL
作为 chat 请求的 base_url，且 llm.py 的请求构造代码不因换端点而修改。

**A2** 当环境变量 `LLM_API_KEY` 被设置时，系统应使用它作为 chat 请求的鉴权 key；当其
未设置而 `ARK_API_KEY` 已设置时，系统应回落使用 `ARK_API_KEY`，行为与现状一致。

**A3** 当环境变量 `LLM_MODEL` 被设置时，系统应使用它作为默认 chat 模型；当其未设置时，
系统应回落 `CLAUDE_MODEL`（现状变量），仍未设置时回落内置默认 `glm-5.2`。

**A4** 当用户未设置任何 `LLM_*` / `WRITER_*` / `NOVEL_TEMPERATURE` / `NOVEL_LLM_EXTRA`
变量时，系统应保持与当前版本完全一致的行为（火山端点 + glm-5.2 + ARK_API_KEY 鉴权，
各调用点温度/max_tokens 现值不变）。

**A5** 当用户将 LLM_* 指向 SenseNova 或 Kimi 官方端点并配置对应 key 时，系统应能在不
修改任何 Python 代码的情况下完成「写一章」全流程（含审稿与评分）。

### 3.2 按角色路由

**A6** 当 `WRITER_BASE_URL` / `WRITER_API_KEY` / `WRITER_MODEL` 中任一被设置时，系统
应让 writer、polisher、partial_refine 三处 chat 调用使用对应覆盖值。

**A7** 当某 `WRITER_*` 变量未设置或为空时，系统应让该字段回落主配置同名字段（三个
变量各自独立回落，不要求同时配置）。

**A8** 当角色路由生效时，系统应保持审稿（_reviewer）、章节摘要（summarize_chapter）、
优劣判定（is_better）、评测（harness.evaluate）仍走主配置，不受 `WRITER_*` 影响。

**A9** 当 `NovelAgent` 以 `writer_llm=None` 构造时，系统应让所有角色共用注入的 `llm`
（沿用 0.8 的构造器注入回落模式），保证既有调用方与全部存量测试零改动。

### 3.3 行为参数可调

**A10** 当 `NOVEL_TEMPERATURE` 被设置为合法浮点数时，系统应以其覆盖生成类调用的温度
（现值：writer 0.8 / polisher 0.6 / partial_refine 0.6）。

**A11** 当 `NOVEL_TEMPERATURE` 未设置时，系统应保持各调用点现有硬编码温度不变。

**A12** 当 `NOVEL_TEMPERATURE` 被设置时，系统应不影响审稿/评测类调用的代码内固定温度
（0.2 / 0.3 等）。

**A13** 当 `NOVEL_LLM_EXTRA` 被设置为合法 JSON 对象时，系统应将其键值对原样合并进 chat
请求体（与内建参数同名时以 extra 为准），例如 Kimi-K3 的顶层参数
`{"reasoning_effort": "low"}`。

**A14** 当 `NOVEL_LLM_EXTRA` 被设置为非法 JSON（或非对象）时，系统应在配置加载阶段
抛出明确报错（错误信息包含变量名与原因），且不发起任何网络请求。

### 3.4 embedding 隔离

**A15** 当用户更换 chat provider（LLM_* / WRITER_* 任意组合）时，系统应保持 RAG
embedding 行为完全不变（embed_url / embed_model / ARK_API_KEY Bearer 鉴权，rag.py
不改动）。

### 3.5 run 记录

**A16** 当一次 run 完成时，run 记录的 config 应能看出各角色实际使用的模型（至少含
writer 所用模型），且 harness 的 replay/compare 无需修改即可展示新字段。

**A17** 当读取不含新字段的旧 run 记录时，系统应保持 replay/compare 行为与现状一致
（不崩、不误报）。

**A18** 系统不应将 api_key、base_url 明文写入 run 记录。

### 3.6 输出清洗

**A19** 当换用的模型在 chat 响应中返回思考块文本时，系统应在文本进入章节文件或被
JSON 解析前将其剥除（剥除位置与标签集合见 design 开放决策 D1）。

### 3.7 宪法修订与兼容

**A20** 当本 feature 实现合入时，宪法应同步修订落盘：§2 LLM 行改为「默认火山、多来源
可配」；§5 模块边界修正为 writer/polisher/reviewer 三角色；§4 按 D4 结论改写
（修订文本的完整 diff 见 design §7，评审通过后随实现一起落盘）。

**A21** 当实现完成后，存量测试套件应保持零新增失败（已知基线：test_strip_polisher_meta /
test_runtime_dir_override / test_defaults 共 3 个存量失败）。

## 4. 非目标

- 不引入 Provider 抽象基类 / 策略注册表 / 插件机制（早期规划已拍板轻量策略层）；
- 不改动 embedding 配置（embed_url / embed_model / 其鉴权，rag.py 零改动）；
- 不为各家 provider 的专有参数逐项建模配置（一切走 `NOVEL_LLM_EXTRA` 透传）；
- 不做分角色 extra 差异化（`WRITER_LLM_EXTRA` 留作未来逃生门，见 design §9）；
- 不做多 run 跨模型对比实验工具（属后续阶段范畴）；
- 不处理非 OpenAI 兼容协议的 provider（如 Anthropic 原生协议）；
- 不做多模型故障 fallback（那是阶段 4 的故障兜底，与本 feature 的成本路由是两回事）。

## 5. 宪法对齐

| 宪法条款 | 关系 | 说明 |
|---|---|---|
| §2 技术栈 LLM 行 | **修订** | base_url 硬编码改为「默认火山，LLM_BASE_URL 可换」；diff 见 design §7 |
| §2 默认模型行 | 衔接 | 默认仍 glm-5.2；经 LLM_MODEL/CLAUDE_MODEL 可换，须重新验证 §4 坑 |
| §4 glm-5.2 推理预算坑 | **修订** | 改写为「实测经验值 + 换模型须重测 + NOVEL_LLM_EXTRA 覆盖逃生门」；改写方式取决于 D4 |
| §5 模块边界 | **修订** | director 已于 0.8 退役，顺带修正为三角色表述，并补角色路由一行 |
| §5 依赖注入 | 遵循 | writer_llm 按构造器注入回落模式追加，不引模块级全局 |
| §5 联网边界 | 遵循 | load_profiles 为纯函数不联网；联网仍只在 llm/rag 边界 |
| §6 spec-kit | 遵循 | 宪法修订随本 feature 走，评审通过后随实现落盘并同步受影响 spec |
