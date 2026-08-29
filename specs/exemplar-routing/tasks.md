# 任务分解：文风基准按章路由（exemplar-routing）

> Feature: `exemplar-routing`
> 对应 `requirements.md` / `design.md`。按序实施，每项完成即勾选。
> 宪法合规：依赖注入可测（§5）、路径随小说走（§3）、零小说名（§1）、路由 LLM max_tokens≥1024（§4）。

---

## T1 标签解析纯函数（routing.py 新模块）

- [x] 新建 `cli/novel_agent/routing.py`：`parse_tag_lines(text) -> list[(文件名, 描述)]`
- [x] 解析规则：`^[-*]\s+(文件名):\s*(描述)`；文件名 token 口径同 `_MANIFEST_LINE_RE`；无冒号行跳过
- [x] `RouteResult` dataclass（files: list[str], reason: str）
- [x] 单测：正常多行 / 无冒号行跳过 / 空文本 / 只有标题说明
- **验证**：`pytest tests/test_routing.py -k parse_tag` 全绿

## T2 路由调用与解析（routing.py）

- [x] `route_exemplars(llm, task, tags) -> RouteResult | None`
- [x] 调用：`llm.chat(EXEMPLAR_ROUTER_SYSTEM, exemplar_router_user(...), max_tokens=1024, temperature=0.2)`
- [x] JSON 解析容错链：直读 -> 剥围栏 -> 抓首 `{...}`；全败 None
- [x] files 过滤：不在标签文件名集合的丢弃；全空 -> None
- [x] prompts.py 加 `EXEMPLAR_ROUTER_SYSTEM` / `exemplar_router_user`（纯函数）
- [x] 单测四分支：成功 / JSON 坏 / 编造文件名被滤 / 全滤空（FakeLLM script）
- **验证**：`pytest tests/test_routing.py` 全绿（10 passed）

## T3 load_exemplar 增 only_files 参（prompts.py）

- [x] `load_exemplar(path, max_chars, progress, only_files=None)`
- [x] only_files 非 None：说明全文 + 按 only_files 顺序取文件（与 _exemplar_corpus 返回清单求交，保序）
- [x] 选中文件不存在/不在目录内：跳过 + progress 提示；结果为空文件集时仍返回说明全文
- [x] 截断逻辑不动（超限按序截断 + 日志）
- [x] 单测：过滤保序 / 与截断叠加 / only_files 含不存在名
- [x] 实施中发现并修复：`样文标签.md` 在文风基准目录内会被当样文全量注入 -> `_exemplar_corpus` 排除（`EXEMPLAR_TAGS_FILENAME` 常量），补 `test_tags_file_not_a_sample`
- **验证**：`pytest tests/test_prompts_exemplar.py` 全绿（含存量）

## T4 config 接线

- [x] `config.py`：`exemplar_tags_subpath` 字段（默认 `文风基准/样文标签.md`）+ `exemplar_tags_full` 属性 + env `NOVEL_EXEMPLAR_TAGS`（空=禁用）
- [x] `.env copy.example` 补条目注释
- [x] 单测：路径解析 / 显式留空禁用
- **验证**：`pytest tests/test_config.py`（存量 failed 不新增）

## T5 cli 接线（_build_agent 内路由）

- [x] `_build_agent`：读标签文件 -> 有标签则先用 default profile LLMClient 路由 -> 成功打印 `🧭 样文路由：...（reason）` + `load_exemplar(only_files=...)`；失败/禁用现状加载 + 一行提示
- [x] 路由 LLM 异常捕获：任何 Exception -> 回落现状，不阻断
- [x] `_do_write`：record 增补 `exemplar_route` 键（files/reason）再落盘
- [x] `_do_status`：标签启用时显示「样文路由：启用（N 条标签）」
- [x] `改`/`精修`/`重写` 路径确认零改动受益（路由以 task 为查询，task 不同自然各选各的）
- [x] 单测（test_cli_write.py）：路由成功 -> writer prompt 只含选中样文（A2）；record 含 exemplar_route（A5）；标签缺失 -> prompt 与现状一致（A1）
- **验证**：`pytest tests/test_cli_write.py` 全绿

## T6 replay 可见（A5）

- [x] `harness.replay` 打印 run 记录中的 `exemplar_route`（存在时一行：选中文件 + reason）
- [x] 单测：含 exemplar_route 的 run 文件 replay 输出含路由行
- **验证**：`pytest tests/test_harness*.py` 相关用例绿

## T7 全量回归与文档

- [x] `cd cli && python -m pytest` 全量：**246 passed, 2 failed**（存量 `test_strip_polisher_meta` / `test_defaults`，与本 feature 无关）；新增用例全绿
- [x] `grep 云依 cli/` 零命中
- [x] `操作手册.md`：第 3 节补「样文标签.md」说明（格式、留空禁用、路由回落行为）+ 第 9 节配置表补 `NOVEL_EXEMPLAR_TAGS`
- [x] `cli/README.md` 目录结构补 `样文标签.md` 一行

## 留给人工（真实环境）

- [ ] 编写真实 `样文标签.md`（14 篇各一行；可让 LLM 读全文代打初稿后人工修订），真实写一章验证路由选择合理性与 token 降幅
