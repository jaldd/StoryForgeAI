# 0.7 模型来源可换 - 技术设计

## 0. 需求映射

| 需求 | 设计落点 |
|---|---|
| A1-A5 provider 可换 | §2 env 全表、§3.1 Settings 接线、§3.2 LLMClient |
| A6-A9 按角色路由 | §1 ModelProfile/Profiles、§3.4 agent.py 注入、§3.5 cli._build_agent |
| A10-A12 温度覆盖 | §1（temperature 仅挂 writer profile）、§3.2 chat 覆盖逻辑 |
| A13-A14 extra 透传 | §2（fail-fast 接线）、§3.2（req.update 合并、extra 赢） |
| A15 embedding 隔离 | §4 不动清单（require_api_key 语义收窄为 embedding 专用） |
| A16-A18 run 记录 | §5 record 形状 |
| A19 思考块清洗 | §3.3 出口剥除 + 开放决策 D1 |
| A20 宪法修订 | §7 diff |
| A21 测试兼容 | §9 测试策略 |

## 1. 总体形状：轻量策略层

OpenAI 兼容协议本身就是策略抽象：同一段请求构造代码，喂不同 base_url/api_key/model
就是不同策略。「插拔模型」= 改 `.env` 一行角色指向。实体只有两个，都在 llm.py：

```python
# llm.py 新增（全部为纯函数/纯数据，不读 os.environ、不联网）
@dataclass(frozen=True)
class ModelProfile:
    base_url: str
    api_key: str
    model: str
    temperature: Optional[float] = None      # None = 不覆盖，用调用点现值
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Profiles:
    default: ModelProfile   # 审稿/摘要/评分等全部非生成调用
    writer: ModelProfile    # writer/polisher/partial_refine

def load_profiles(settings: Optional[Settings] = None) -> Profiles:
    s = settings or get_settings()
    default = ModelProfile(
        base_url=s.base_url,
        api_key=s.llm_api_key or s.ark_api_key,
        model=s.model,
        temperature=None,                    # 主配置永不带温度覆盖（A12 由构造保证）
        extra=dict(s.llm_extra),
    )
    writer = ModelProfile(
        base_url=s.writer_base_url or default.base_url,
        api_key=s.writer_api_key or default.api_key,
        model=s.writer_model or default.model,
        temperature=s.llm_temperature,       # NOVEL_TEMPERATURE 只挂 writer（A10-A12）
        extra=dict(s.llm_extra),
    )
    return Profiles(default=default, writer=writer)
```

设计要点：

- **纯函数**：load_profiles 只吃 Settings，不读 env、不联网。测试直构 Settings 即可
  断言回落链，不需要 monkeypatch、不需要 `get_settings.cache_clear()`。
- **温度覆盖用 None 哨兵**：`profile.temperature is None` 表示「不覆盖」，chat() 用
  调用点传入的温度现值。主配置 profile 的 temperature 恒为 None，意味着
  NOVEL_TEMPERATURE 物理上无法影响审稿/评分调用（A12 由构造保证，而非靠调用点自觉）。
- **空字符串回落**：`or` 语义天然满足早期规划的「空=回落主配置」，且三个 WRITER_*
  变量各自独立回落（A7），配了 URL 不配 key 是合法形态。
- **extra 同值进两个 profile**：NOVEL_LLM_EXTRA 语义是「全局 chat 层行为参数」。
  分角色差异化（WRITER_LLM_EXTRA）是已知局限，见 §12。

## 2. env 变量全表（含回落链）

| 变量 | 作用 | 回落链（从左到右） | 解析 |
|---|---|---|---|
| `LLM_BASE_URL` | chat 主配置端点 | 未设 -> 火山 `https://ark.cn-beijing.volces.com/api/coding/v3` | str，空串视同未设 |
| `LLM_API_KEY` | chat 主配置鉴权 | 未设 -> `ARK_API_KEY` | str |
| `LLM_MODEL` | chat 主配置模型 | 未设 -> `CLAUDE_MODEL` -> `glm-5.2` | str |
| `WRITER_BASE_URL` | writer/polisher/局部精修端点 | 空 -> LLM_BASE_URL 的解析值 | str |
| `WRITER_API_KEY` | 同上鉴权 | 空 -> LLM_API_KEY 的解析值 | str |
| `WRITER_MODEL` | 同上模型 | 空 -> LLM_MODEL 的解析值 | str |
| `NOVEL_TEMPERATURE` | 生成类调用温度覆盖 | 未设 -> 调用点现值（0.8/0.6/0.6） | float，非法值 fail-fast |
| `NOVEL_LLM_EXTRA` | chat 请求体额外参数 | 未设 -> `{}` | JSON 对象，非法/非对象 fail-fast |
| `ARK_API_KEY` | 既有：embedding 鉴权（兼 chat key 回落） | **无变化** | str |
| `CLAUDE_MODEL` | 既有：模型回落 | 仅 LLM_MODEL 未设时生效 | str |
| `NOVEL_DIR` 等其余 | 既有配置 | **无变化** | - |

注意回落是**两段式**的：第一段（env -> Settings 字段）发生在 get_settings；第二段
（WRITER_* 字段 -> default profile）发生在 load_profiles。WRITER_* 回落的是 LLM_* 的
**解析值**而非原始 env（例：只配 `ARK_API_KEY` + `WRITER_MODEL=kimi-k3`，writer 的
api_key 回落到 ARK key）。

`LLM_MODEL` 是本设计自主引入的变量（早期规划只点名 LLM_BASE_URL/LLM_API_KEY）：换
provider 不换模型名几乎不可能成立（火山网关模型名与 Kimi/SenseNova 各不相同），不接
env 则 provider 可换是残缺配置面。`CLAUDE_MODEL` 保留为回落以兼容现状。此项可否决，
见 §11。

## 3. 模块改动清单

### 3.1 config.py：字段 + 接线

Settings 新增字段（llm.py 的 load_profiles 消费）：

```python
# 新增
llm_api_key: str = ""            # LLM_API_KEY
writer_base_url: str = ""        # WRITER_BASE_URL
writer_api_key: str = ""         # WRITER_API_KEY
writer_model: str = ""           # WRITER_MODEL
llm_temperature: Optional[float] = None   # NOVEL_TEMPERATURE
llm_extra: Dict[str, Any] = field(default_factory=dict)  # NOVEL_LLM_EXTRA

# model/base_url 接线改造（现状：model 只读 CLAUDE_MODEL）
model=os.environ.get("LLM_MODEL", "") or os.environ.get("CLAUDE_MODEL", "") or "glm-5.2",
base_url=os.environ.get("LLM_BASE_URL", "") or "https://ark.cn-beijing.volces.com/api/coding/v3",
```

模块级 helper（非法值 fail-fast，同 0.8 D5 的 int() 直转先例，报错信息含变量名）：

```python
def _env_float(name: str) -> Optional[float]:   # None = 未设置
    raw = os.environ.get(name, "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"{name} 必须是数字，当前值: {raw!r}")

def _env_json_object(name: str) -> Dict[str, Any]:
    raw = os.environ.get(name, "")
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{name} 必须是合法 JSON: {e}")
    if not isinstance(val, dict):
        raise RuntimeError(f"{name} 必须是 JSON 对象（如 {{\"reasoning_effort\": \"low\"}}）")
    return val
```

`require_api_key()`（config.py:125）**不动**：语义收窄为 embedding 专用（rag.py:100 的
Bearer 鉴权继续用它），报错文案继续提 ARK_API_KEY（embedding 仍锁火山，A15）。
`get_settings()` 的 `@lru_cache(maxsize=1)` 不动，坑的纪律见 §9。

### 3.2 llm.py：LLMClient 改造

```python
class LLMClient:
    def __init__(self, settings: Optional[Settings] = None,
                 client: Optional[OpenAI] = None,
                 profile: Optional[ModelProfile] = None):
        self.settings = settings or get_settings()
        self._client = client
        # None -> 主配置；writer 注入见 cli._build_agent
        self.profile = profile if profile is not None else load_profiles(self.settings).default

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.profile.api_key:
                raise RuntimeError("chat 调用缺 API key：设置 LLM_API_KEY（或 ARK_API_KEY）")
            self._client = OpenAI(api_key=self.profile.api_key,
                                  base_url=self.profile.base_url)
        return self._client

    def chat(self, system, user, *, max_tokens=1024, temperature=0.9, max_retries=5):
        # temperature 覆盖：profile 配了温度则压掉调用点现值（仅 writer profile 可能配）
        effective = temperature if self.profile.temperature is None else self.profile.temperature
        req = {
            "model": self.profile.model,          # 原来读 settings.model
            "max_tokens": max_tokens,
            "temperature": effective,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req.update(self.profile.extra)            # extra 赢：透传的字面语义
        resp = self._create_with_retry(req, max_retries=max_retries)
        # ... 现有指数退避 / 空回处理不变 ...
        return _strip_think_blocks(resp)           # A19，见下
```

关键决策：

- **client property 不再用 `settings.require_api_key()`**，改用 `profile.api_key`。
  这是 chat key 与 embedding key 解耦的落点：换商后 ARK key 只服务 embedding。
- **`req.update(self.profile.extra)` 在内建 kwargs 之后**：同名键 extra 赢。这是透传的
  字面语义，同时天然提供 `max_tokens` 的零代码逃生门（`NOVEL_LLM_EXTRA={"max_tokens":
  8192}` 可覆盖任何调用点的预算，支撑 D4 的推荐结论）。
- **缺 key 报错**从「提 ARK_API_KEY」改为「提 LLM_API_KEY（或 ARK_API_KEY）」；只在
  真正惰性建 client 时触发（直构 agent 不联网、不报错，测试不受影响）。
- 模型/温度/max_tokens 以外的现有行为（重试 5 次、空回返回 ""）不变。

### 3.3 llm.py：思考块清洗（A19；D1 已拍板 a：chat() 出口统一剥）

```python
_THINK_OPEN = "<" + "think" + ">"      # 拼接写法：源码不出现完整标签序列
_THINK_CLOSE = "</" + "think" + ">"
_THINK_BLOCK_RE = re.compile(
    _THINK_OPEN + r".*?" + _THINK_CLOSE + r"\s*", re.DOTALL
)


def _strip_think_blocks(text: str) -> str:
    """剥思考块：完整对（DOTALL 非贪婪）+ 未闭合前缀（从标签处剥到结尾）。"""
    if not text:
        return text
    out = _THINK_BLOCK_RE.sub("", text)
    idx = out.find(_THINK_OPEN)
    if idx != -1 and _THINK_CLOSE not in out:
        out = out[:idx]
    return out
```

- 接线点：§3.2 代码末行 `return _strip_think_blocks(resp)`（替换现有 `return
  content`）。出口统一，agent 六个调用点与 harness.evaluate 自建 client 全部
  免费受益，顺带保护 reviewer 的 JSON 解析（思考块混进 JSON 会导致解析失败）。
- **未闭合前缀是 A19 要防的事故形态**：流式截断/模型只吐半段思考时，完整对正则
  匹配不到，残留会把思考当正文写进章节；此时从标签开头整段丢弃（含未闭合）。
- 标签集刻意只收一种（Kimi/GLM 实际返回形态）；`<reasoning>` 等新标签等实测
  遇到再加，不盲扫误伤正文（D1 拍板）。
- 与 `_strip_code_fence`（agent.py，仅挂 partial_refine）职责不同：一个剥 markdown
  围栏、一个剥协议层思考块，互不替代也不合并。

### 3.4 agent.py：writer_llm 注入 + 调用点路由（A6-A9）

`__init__` 加一个参数（模式与 0.8 的 max_reviews/target_words 完全同款）：

```python
def __init__(self, llm, ..., rules: str = "",
             writer_llm: Optional[LLMClient] = None):
    ...
    self.writer_llm = writer_llm if writer_llm is not None else llm
```

- **None 回落 self.llm**：存量构造（全部测试的 FakeLLM 直注 llm）零改动（A9）。
- **调用点路由**（生成类 -> writer_llm；审稿/摘要/评分类不动；温度实参一律不动，D5）：
  - `_writer`（温度 0.8）/ `_polisher`（0.6）/ `partial_refine`（0.6）-> `self.writer_llm.chat`
  - `_reviewer`（0.2）/ `summarize_chapter`（0.3）/ `is_better`（0.2）保持 `self.llm.chat`
- `_record` 的 config 增键见 §5；从 load_profiles 重算而非读注入对象（Z5）。

### 3.5 cli.py：_build_agent 双 client 装配（A1-A8）

```python
def _build_agent(settings: Settings):
    ...
    profiles = load_profiles(settings)          # 一次解析，两个 profile
    agent = NovelAgent(
        llm=LLMClient(settings=settings, profile=profiles.default),
        writer_llm=LLMClient(settings=settings, profile=profiles.writer),
        rag=RAGStore(settings=settings),
        ...                                      # 其余装配不动
    )
```

- 同一份 settings 建两个 LLMClient，差异全在 profile；未配 WRITER_* 时两 profile
  逐字段相等，行为与现状完全一致（回归保险，A9）。
- harness.evaluate 自建的 LLMClient 不动：profile=None 自动落 default（§3.2）。

## 4. 不动清单（防漂移）

- **embedding 路径零改动（A15）**：`rag.py` 的 embedding 调用、`config.py` 的
  `require_api_key()`（读 ARK_API_KEY，报错文案不动）与 embedding 相关字段全部
  不动。换商后 ARK key 只服务 embedding。
- **调用点温度实参不动**：agent.py 六处现值（writer 0.8 / polisher 0.6 / reviewer
  0.2 / summarize 0.3 / is_better 0.2 / partial_refine 0.6）原样保留；主 profile
  恒 temperature=None，未配 NOVEL_TEMPERATURE 时哨兵回落到这些值（D5）。
- **重试与空回语义不动**：5 次重试、指数退避、空回返回 "" 不变；纯思考块输入剥完
  为空串时自然落现有空回路径。
- **`_record` 既有键不动**：run_id / task / timestamp / config 既有五键 /
  initial_state / steps / final_state 全保留，只增不改（A16）。
- **CLI 表面不动**：REPL 命令、参数、提示语零变化；`.env copy.example` 只追加注释段。
- **`py/` 与 Java 侧不动**：宪法 §3 既定边界。

## 5. run 记录 config 形状（D3 已拍板 a：扁平键）

`_record`（agent.py）改造后 config 部分（其余键不动）：

```python
profiles = load_profiles(self.settings)     # Z5：重算，不读注入对象
...
"config": {
    "model": profiles.default.model,                  # 改源：settings.model -> 同源重算
    "temperature": temperature,                       # 既有键不动（run 级遗留语义）
    "writer_model": profiles.writer.model,             # 新增（D3-a）
    "llm_temperature": profiles.writer.temperature,    # 新增（Z3；未配为 None）
    "max_rounds": self.max_rounds,
    "max_reviews": self.max_reviews,
    "target_words": self.target_words,
},
```

- **api_key / base_url 不进 record**：密钥绝不落盘。
- replay 整字典打印 config（harness.py L34），新键自动展示零改动；compare 显式读
  temperature 键（harness.py L209），新增 sibling 键零影响；旧记录（无新键）
  replay/compare 不崩（T6 验证项）。

## 6. `.env copy.example` 追加段（D2 已拍板 a：示例进 .env 注释）

在现有 LLM 段（`ARK_API_KEY` / `CLAUDE_MODEL`）之后追加：

```dotenv
# ---- LLM 来源可换（0.7；全不设 = 现状，回落链见注释）----
# LLM_BASE_URL=            # 未设 -> 火山 https://ark.cn-beijing.volces.com/api/coding/v3
# LLM_API_KEY=             # 未设 -> ARK_API_KEY
# LLM_MODEL=               # 未设 -> CLAUDE_MODEL -> glm-5.2
# ---- 写作侧独立（writer/polisher/局部精修；空 = 回落主配置对应解析值）----
# WRITER_BASE_URL=
# WRITER_API_KEY=
# WRITER_MODEL=
# ---- 生成类温度覆盖（只作用写作侧；未设 = 调用点现值 0.8/0.6/0.6，零漂移）----
# NOVEL_TEMPERATURE=0.7
# ---- chat 请求体透传（合法 JSON 对象；与内建参数同名时此值赢，兼作 max_tokens 逃生门）----
# NOVEL_LLM_EXTRA={"max_tokens": 8192}
# Kimi-K3 推理调档示例（仅 Kimi-K3 有效；其他模型勿用）：
# NOVEL_LLM_EXTRA={"reasoning_effort": "high"}
```

- 换商三件套示例（SenseNova / Kimi 端点成对注释块）随 T8 实现时补全。
- 注释回落链须与 §2 env 全表逐行一致（T8 验证项）；示例 JSON 须能通过
  `_env_json_object` 合法校验（本地手工跑一次）。

## 7. 宪法修订 diff（A20；T9 执行，评审已定稿）

`.specify/memory/constitution.md` 三处：

**§2 表：LLM 行 + 默认模型行**

```diff
-| LLM | 火山方舟 OpenAI 兼容 coding 网关 | `base_url=https://ark.cn-beijing.volces.com/api/coding/v3` |
+| LLM | OpenAI 兼容网关，来源可换（0.7） | `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` 接线；不设回落火山 coding 网关 |
-| 默认模型 | `glm-5.2` | **推理模型，见 §4** |
+| 默认模型 | `glm-5.2` | **推理模型，见 §4**；`LLM_MODEL` -> `CLAUDE_MODEL` -> 默认 三级回落 |
```

**§4：标题改写 + 末尾增补（D4）**

```diff
-## 4. glm-5.2 推理模型约束（踩过的坑）
+## 4. glm-5.2 推理模型约束（踩过的坑；换模型须重实测）
```

§4 末尾（`novel_agent/llm.py` 默认值那条之后）追加：

```diff
+- 以上经验值绑定 glm-5.2 + 火山网关；换模型/换商后必须重新实测，必要时用
+  `NOVEL_LLM_EXTRA={"max_tokens": ...}` 透传覆盖（同名键 extra 赢）。
```

**§5：agent 行修正（director 已退役是 0.8 遗留表述，顺带修）**

```diff
-  └─ agent（director/writer/polisher/reviewer 状态机）
+  └─ agent（writer/polisher/reviewer 状态机；写作侧可注入独立 writer_llm）
```

- §2 的 Embedding 行不动（仍锁火山，A15）；§4 前三条经验值原文不动。
- 改完按宪法 §6 自查其他 spec 有无火山硬编码表述（T9：全仓 grep 复核）。

## 8. 实现注意（坑位）

- **lru_cache 纪律**：`get_settings()` 带 `@lru_cache(maxsize=1)`，测试 setenv 后必须
  `get_settings.cache_clear()`，finally 再 clear（0.8 建立的模式；T1 每用例都要求）。
- **load_profiles 纯函数可测**：直构 Settings 断言回落链，不依赖 monkeypatch（T2）。
- **agent.py 注入只用既有模式**：writer_llm 与 max_reviews/target_words 同款；不动
  既有参数顺序与默认值。
- **测试环境**：沙箱拦 site-packages 时用 `pip install --target .deps` +
  `PYTHONPATH=.deps` 跑 pytest（.gitignore 已覆盖 .deps）。
- **验收口径**：3 个存量失败（test_strip_polisher_meta / test_runtime_dir_override /
  test_defaults）零新增失败（A21）。

## 9. 测试策略（全程不联网，A21）

- **test_config.py（T1）**：两级 key 回落 / 三级 model 回落 / WRITER_* 空串回落 /
  NOVEL_TEMPERATURE 非法 fail-fast（报错含变量名）/ NOVEL_LLM_EXTRA 非法 JSON 与
  非对象 fail-fast；每用例 setenv 后 cache_clear、finally 再 clear。
- **test_llm.py**：
  - T2：load_profiles 四态（全空 == 现状形状 / 只配 WRITER_MODEL 部分覆盖 / 全配
    writer 完整独立 / llm_temperature=None 时 writer.temperature 为 None）。
  - T3：SpyClient（伪造 client 记录 create kwargs）断言 model 来自 profile / 温度
    哨兵回落与设值覆盖 / extra 合并且同名赢（含 max_tokens 覆盖用例）/ 缺 key 报错
    文案含两个变量名 / profile=None 注入回落 default。
  - T4：_strip_think_blocks 四态（完整对剥除 / 未闭合剥到开头 / 无标签原样 /
    纯思考块 -> 空串，落现有空回路径）。
- **test_agent.py**：T5 双 FakeLLM（llm / writer_llm 各一）断言生成类消费 writer_llm
  的 script、审稿类消费 llm 的 script、writer_llm=None 时全走 llm；T6 新键配/不配
  两态 + 存量 `record["config"]["model"] == "glm-5.2"` 断言保持绿。
- **test_harness.py**：T6 旧记录（无新键）replay/compare 不崩；T10（P1，做否按 D3）。
- **回归命令**：`cli/` 下 `python -m pytest tests/ -q`；基线 3 存量失败，零新增。

## 10. 开放决策（评审会话已逐条拍板：D1-D5 全按推荐倾向）

> 注：原 §3.3 代码尾与 §3.4-§10、D1 行首因起草阶段的文档管道事故丢失（思考块标签
> 字面量被工具链误吃）；本节起由评审会话按拍板结果重写，拍板结论与起草倾向一致。

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 思考块清洗位置与范围 | a) llm.py chat() 出口统一剥（完整对 + 未闭合前缀，含未闭合）；b) 各调用点自行剥；c) 扩大标签集（`<reasoning>` 等） | **a** | 调用点模式已被 `_strip_code_fence` 仅挂 partial_refine 证明有漏网；思考块是协议层产物应在出口剥（顺带保护 reviewer 的 JSON 解析）；标签集先只收思考块标签（Kimi/GLM 实际返回形态），遇到新标签再加，避免盲扫误伤正文。c 的完整清单建议实测 SenseNova/Kimi 后定 |
| D2 | Kimi K3 reasoning_effort 调档示例放哪 | a) `.env copy.example` 注释；b) 操作手册 | **a** | 项目当前没有操作手册载体；早期规划定位它是 env 级调教实验参数，用户找配置第一眼看 .env copy.example；给一行注释掉的示例并标注「仅 Kimi-K3」即可 |
| D3 | run 记录 config 怎么体现各角色模型 | a) 扁平键（model + writer_model + llm_temperature）；b) 嵌套 config["llm"]={...} | **a** | replay 整字典打印自动展示新键、compare 显式读键零改动；扁平是 0.8 的先例（target_words 直进 config）；嵌套会让旧工具读不到 sibling 键。形状见 §5 |
| D4 | max_tokens 是否按 profile 可配 + 宪法 §4 怎么改写 | a) 不建字段，代码内固定值不变，需要时 NOVEL_LLM_EXTRA 透传覆盖；b) ModelProfile 加 max_tokens 字段 | **a** | b 会引入「profile 配了 max_tokens 时调用点预算失效」的双轨语义；a 用 extra 赢的既有机制零成本覆盖（`{"max_tokens": 8192}`），且 §4 改写为「经验值 + 换模型须实测 + 透传逃生门」与早期规划「max_tokens 语义必须实测」的口径一致 |
| D5 | ModelProfile 不配温度时回落什么 | a) 回落调用点现值（0.8/0.6/0.6）；b) 各角色内置统一默认 | **a** | A4/A11 要求未配置时行为与现状完全一致，b 必然改变现值；a 用 temperature=None 哨兵实现，主配置 profile 恒 None 顺带物理保证 A12 |

## 11. 自主补充决策（用户未点名；评审会话已全部采纳）

| # | 决策 | 理由 |
|---|---|---|
| Z1 | 引入 `LLM_MODEL` env（早期规划未点名） | 换 provider 必换模型名，不接 env 则 provider 可换残缺；CLAUDE_MODEL 保留为回落兼容现状 |
| Z2 | extra 与内建参数同名时 extra 赢（req.update 顺序） | 透传的字面语义；同时构成 max_tokens 覆盖的零代码逃生门（支撑 D4-a） |
| Z3 | record 新增 `llm_temperature` 键（早期规划只要求模型可见） | NOVEL_TEMPERATURE 本就为配 compare 做 A/B 而生，温度不进记录则 A/B 无法归因 |
| Z4 | NOVEL_LLM_EXTRA 同值进 default 与 writer 两个 profile | 早期规划的 Kimi 用例是整 provider 切换（三处生成 + 审稿同商）；分角色差异化列为非目标（WRITER_LLM_EXTRA 逃生门，§12） |
| Z5 | `_record` 从 load_profiles(settings) 重算而非读注入对象 | FakeLLM 注入无 profile 属性；直构 Settings 测试确定性；生产路径两者同源 |

## 12. 已知局限（接受，不修）

- **extra 不分角色**：default 与 writer 共用 NOVEL_LLM_EXTRA（Z4）。「审稿走 A 商 + 写作
  走 B 商 + 各带不同 extra」的组合暂不支持，未来加 `WRITER_LLM_EXTRA` 单变量即可，接口
  形状已预留（ModelProfile.extra 是独立字段）。
- **record 可能与注入不一致**：直构注入与 settings 推导不一致的 writer_llm 时，
  _record 记的是 settings 侧（Z5 取舍）。
- **思考块标签集有限**：只剥 ``<`+`think`+`>``（D1-a），新模型新标签需补正则。
- **extra 覆盖核心键无防护**：NOVEL_LLM_EXTRA 写进 messages/model 会原样生效，属用户
  自担（fail-fast 只管 JSON 合法性，不做键白名单）。
