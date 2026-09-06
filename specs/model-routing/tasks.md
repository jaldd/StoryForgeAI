# 0.7 模型来源可换 - 任务分解

前置：design.md 已评审通过（含 D1-D5 拍板结论与本文件对拍板结果的落实口径）。
约定：每个任务单文件单职责，完成后即跑「验证」栏；全程测试不联网。
全量回归命令（在 `cli/` 下）：`python -m pytest tests/ -q`。
基线：test_strip_polisher_meta / test_runtime_dir_override / test_defaults 共 3 个存量
失败，验收口径为**零新增失败**。

## P0（实现主干）

- [x] **T1 config.py：Settings 新字段 + env 接线改造**
  改动：新增 `llm_api_key / writer_base_url / writer_api_key / writer_model /
  llm_temperature / llm_extra` 六字段；`model` 接线改为 `LLM_MODEL -> CLAUDE_MODEL ->
  glm-5.2` 三级回落，`base_url` 接 `LLM_BASE_URL`（空串回落火山 URL）；新增模块级
  `_env_float` / `_env_json_object` helper（非法值 RuntimeError，报错含变量名）。
  `require_api_key` 与 embedding 相关字段不动。
  验证：test_config.py 新增用例（两级 key 回落 / 三级 model 回落 / WRITER_* 空串回落 /
  NOVEL_TEMPERATURE 非法 fail-fast / NOVEL_LLM_EXTRA 非法 JSON 与非对象 fail-fast），
  每个用例 setenv 后 `get_settings.cache_clear()`、finally 再 clear（0.8 纪律）；
  A1-A4、A10、A14、A21。

- [x] **T2 llm.py：ModelProfile / Profiles / load_profiles（纯函数）**
  改动：新增两个 frozen dataclass 与 `load_profiles(settings=None)`，回落逻辑全在
  函数内（WRITER_* 空 -> default 同名字段；default api_key = llm_api_key or
  ark_api_key；temperature 只挂 writer；extra 同值进两 profile）。
  验证：test_llm.py 新增纯函数用例，直构 Settings（无 monkeypatch、无 cache_clear）：
  全空 == 现状形状；只配 WRITER_MODEL 时部分覆盖；全配时 writer 完整独立；
  llm_temperature=None 时 writer.temperature 为 None。A6、A7、A10。

- [x] **T3 llm.py：LLMClient 接 profile + chat 请求体组装**
  改动：`__init__` 加 `profile` 参数（None -> load_profiles().default）；client
  property 改用 `profile.api_key / profile.base_url`（不再用 require_api_key），缺
  key 报错文案提 `LLM_API_KEY（或 ARK_API_KEY）`；chat() 的 model/temperature 从
  profile 取（温度 None 哨兵回落调用点现值），`req.update(profile.extra)` 在内建
  kwargs 之后（extra 赢）。重试/空回逻辑不动。
  验证：test_llm.py 用 SpyClient（伪造 client 记录 create kwargs）断言：model 来自
  profile；profile.temperature=None 时用调用点温度、设值时覆盖；extra 合并且同名
  赢（含 max_tokens 覆盖用例）；缺 key 且 client 惰性触发时报错含两个变量名；
  profile=None 注入回落 default。A1-A3、A10-A13、A15（不碰 rag 路径）。

- [x] **T4 llm.py：`_strip_think_blocks` 输出清洗（按 D1 拍板结论实施）**
  改动：新增模块级纯函数剥除思考块（标签集按 D1 结论；推荐方案为
  `…` 完整对 + 未闭合前缀），接在 chat() 返回出口。
  验证：test_llm.py 纯函数用例：完整对剥除 / 未闭合剥到开头 / 无标签原样 /
  纯思考块 -> 空串（落现有空回路径）；已有 `_strip_code_fence` 相关测试不受影响。
  A19。

- [x] **T5 agent.py：writer_llm 注入 + 三处调用点路由**
  改动：`__init__` 加 `writer_llm: Optional[LLMClient] = None`（None 回落 self.llm，
  与 max_reviews/target_words 同一 0.8 注入模式）；`_writer` / `_polisher` /
  `partial_refine` 的 `self.llm.chat` 改为 `self.writer_llm.chat`；
  `_reviewer` / `summarize_chapter` / `is_better` 不动。
  验证：test_agent.py 注入两个 FakeLLM（llm / writer_llm 各一）断言生成类调用消费
  writer_llm 的 script、审稿类消费 llm 的 script；writer_llm=None 时全部走 llm
  （A9，存量构造零改动）；既有全量测试不新增失败。A6-A9。

- [x] **T6 agent.py：`_record` 的 config 新键（形状按 D3 拍板结论）**
  改动：config dict 新增 `writer_model`（= load_profiles(settings).writer.model）与
  `llm_temperature`（= writer.temperature，未设为 None）；`model` 键改为同源
  `load_profiles(settings).default.model`；既有 `temperature`（run 级遗留）与其余
  键不动；api_key / base_url 不进 record。
  验证：test_agent.py 断言新键（配/不配两态）+ 既有
  `record["config"]["model"] == "glm-5.2"` 断言保持绿；harness 对旧记录（无新键）
  replay/compare 用例不崩。A16-A18。

- [x] **T7 cli.py：`_build_agent` 双 client 注入**
  改动：`load_profiles(settings)` 一次解析，`llm=LLMClient(settings, profile=
  profiles.default)`、`writer_llm=LLMClient(settings, profile=profiles.writer)`，
  其余装配不动；harness.evaluate 的自建 LLMClient 不动（profile=None 自动落
  default）。
  验证：冒烟（FakeLLM 夹具下 CLI 构造路径可用）+ 全量回归零新增失败。A1-A8、A16。

- [x] **T8 `.env copy.example`：新增配置注释段（示例位置按 D2 拍板结论）**
  改动：追加 LLM_* / WRITER_* / NOVEL_TEMPERATURE / NOVEL_LLM_EXTRA 段落，含回落链
  一览、SenseNova / Kimi 端点示例；reasoning_effort 调档示例按 D2 结论（推荐：一行
  注释掉的示例 + 「仅 Kimi-K3」标注）。
  验证：人工核对注释与 §2 env 全表逐行一致；其中出现的 JSON 示例能通过
  `_env_json_object` 的合法校验（本地手工跑一次解析）。A5。

- [x] **T9 宪法落盘（评审通过后执行）**
  改动：按 design §7 diff 修订 `.specify/memory/constitution.md` §2（LLM 行 + 默认模型
  行）、§4（标题与增补行，按 D4 结论）、§5（三角色表述 + 角色路由一行）；按宪法 §6
  检查并同步受影响的其他 spec（至少确认 pipeline-dataflow spec 无火山硬编码引用）。
  验证：`git diff .specify/memory/constitution.md` 与 design §7 diff 一致；全仓 grep
  确认代码/宪法不再有「base_url 硬编码且不可配」的表述。A20。

## P1（可选增强，非阻塞）

- [x] **T10 harness.py：compare 输出增模型维度行（按 D3 拍板结论决定做否）**
  改动：`compare` 在温度行之外增打印 `model` / `writer_model`（旧记录缺键时跳过该行）。
  验证：test_harness 用例--新旧记录混排对比不崩、新记录展示两行模型。A16、A17。

## 验收对照表

| 验收项 | 承载任务 |
|---|---|
| A1-A5 provider 可换 | T1、T3、T7、T8 |
| A6-A9 按角色路由 | T2、T5、T7 |
| A10-A12 温度覆盖 | T1、T2、T3 |
| A13-A14 extra 透传 | T1、T3、T8 |
| A15 embedding 隔离 | T3（不碰 require_api_key/rag）+ 人工验收 |
| A16-A18 run 记录 | T6（+P1 T10） |
| A19 思考块清洗 | T4 |
| A20 宪法修订 | T9 |
| A21 零新增测试失败 | 全部任务的全量回归 |

## 人工验收（对齐阶段 0.7 规划验收口径）

1. `.env` 配 SenseNova 或 Kimi 端点 + key（WRITER_MODEL 指向其写作模型），跑「写一章」
   成功，正文无思考块残留（T4 效果）；
2. 该次 run 记录的 config 能看出 writer 用了新模型（writer_model != model 时一目了然）；
3. 同次运行审稿/评分仍走火山（主配置未动），RAG embedding 检索正常（查设定步骤不报错）；
4. 清空 LLM_* / WRITER_* 后复跑，行为与改造前一致（回归保险）。
