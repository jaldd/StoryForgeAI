# 功能需求规格说明书

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 功能模块总览

```
StoryForgeAI
├── 核心对话模块
│   ├── 意图识别
│   ├── 对话管理
│   └── 流式输出
├── 记忆管理模块
│   ├── 短期记忆
│   ├── 长期记忆
│   └── 工作记忆
├── 工具调用模块
│   ├── CharacterArcPlanner
│   ├── PlotGapDetector
│   └── StyleTransfer
├── 模型网关模块
│   ├── 模型路由
│   ├── Fallback 机制
│   └── 成本追踪
└── MCP 服务模块
    ├── MCP Server
    └── 工具暴露
```

---

## 2. 核心对话模块

### 2.1 意图识别

#### 功能描述

识别用户输入的意图类型，为后续处理提供决策依据。

#### 功能规格

**输入**:
```json
{
  "text": "帮我分析张伟是否扁平",
  "projectId": "novel_123",
  "context": {}
}
```

**输出**:
```json
{
  "intent": "ANALYZE",
  "confidence": 0.85,
  "entities": {
    "characterName": "张伟"
  }
}
```

**业务规则**:

| 意图类型 | 触发关键词 | 置信度阈值 | 后续动作 |
|---------|-----------|-----------|---------|
| BRAINSTORM | 构思、世界观、设定、角色、创建、设计 | 0.7 | 无需检索，直接生成 |
| POLISH | 润色、改写、优化文风、修饰 | 0.7 | 提取待润色文本 |
| ANALYZE | 分析、是否扁平、关系、伏笔、漏洞 | 0.8 | 检索相关内容 + 工具调用 |
| CONTINUE | 续写、下一章、第三章、接着写 | 0.8 | 加载工作记忆 + 检索前文 |
| GENERAL_CHAT | 其他所有输入 | 0.5 | 直接对话 |

**实现方式**:

阶段一（MVP）:
- 基于规则的关键词匹配
- 使用正则表达式匹配触发关键词

阶段二（优化）:
- 使用 GLM-4-Flash 进行意图分类
- 输出意图类型 + 置信度 + 实体提取

**验收标准**:
- [ ] 能正确识别 5 种意图类型
- [ ] 准确率 > 80%（人工测试 50 个样本）
- [ ] 响应时间 < 100ms（规则匹配）

---

### 2.2 对话管理

#### 功能描述

管理用户与 Agent 的多轮对话，维护对话上下文。

#### 功能规格

**对话流程**:
```
用户输入 → 意图识别 → 上下文构建 → 工具调用（可选） → 模型生成 → 流式输出 → 状态持久化
```

**上下文构建**:
```java
ContextBundle buildContext(String projectId, String userInput) {
    // 1. 短期记忆：最近 10 轮对话
    List<Turn> shortTermMemory = redisStore.getWindow(projectId, 10);
    
    // 2. 长期记忆：向量检索相关片段
    List<DocChunk> relevantChunks = vectorStore.search(projectId, userInput, 5);
    
    // 3. 工作记忆：当前小说状态
    WorkingState workingState = stateStore.get(projectId);
    
    return new ContextBundle(shortTermMemory, relevantChunks, workingState);
}
```

**对话状态**:
- **会话状态**: 当前会话的对话历史
- **项目状态**: 当前小说的工作记忆
- **用户状态**: 用户偏好、历史项目

**验收标准**:
- [ ] 能维护至少 10 轮对话上下文
- [ ] 能正确加载工作记忆
- [ ] 能正确持久化对话记录

---

### 2.3 流式输出

#### 功能描述

通过 SSE（Server-Sent Events）实现流式输出，提升用户体验。

#### 功能规格

**SSE 协议**:
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"type":"token","content":"根据"}

data: {"type":"token","content":"分析"}

data: {"type":"done"}
```

**数据格式**:
```json
{
  "type": "token",
  "content": "根据",
  "timestamp": "2026-04-02T10:30:00Z"
}
```

**错误处理**:
```json
{
  "type": "error",
  "code": "MODEL_TIMEOUT",
  "message": "模型调用超时",
  "timestamp": "2026-04-02T10:30:05Z"
}
```

**验收标准**:
- [ ] 首token延迟 < 3秒
- [ ] 流式输出无卡顿
- [ ] 错误信息友好提示

---

## 3. 记忆管理模块

### 3.1 短期记忆

#### 功能描述

存储最近 N 轮对话，维护对话上下文连贯性。

#### 功能规格

**存储结构**:
```json
{
  "projectId": "novel_123",
  "turns": [
    {
      "turnId": "turn_001",
      "role": "user",
      "content": "帮我分析张伟是否扁平",
      "timestamp": "2026-04-02T10:30:00Z"
    },
    {
      "turnId": "turn_002",
      "role": "assistant",
      "content": "根据分析...",
      "timestamp": "2026-04-02T10:30:05Z",
      "metadata": {
        "modelUsed": "glm-4-flash",
        "tokenCount": 150,
        "toolsCalled": ["character_arc_planner"]
      }
    }
  ]
}
```

**滑动窗口策略**:
- 默认保留最近 10 轮对话
- Token 预算: 3000 tokens
- 超出时，将旧对话压缩为摘要

**摘要生成**:
```java
String summarizeOldTurns(List<Turn> oldTurns) {
    String prompt = "请将以下对话压缩为摘要：\n" + formatTurns(oldTurns);
    return modelGateway.chatOnce(prompt);
}
```

**验收标准**:
- [ ] 能存储最近 10 轮对话
- [ ] 滑动窗口正常工作
- [ ] 摘要生成质量可接受

---

### 3.2 长期记忆

#### 功能描述

存储小说章节的向量表示，支持语义检索。

#### 功能规格

**分块策略**:

按**场景**分块，每个场景包含：
- 时间
- 地点
- 人物
- 事件

**场景识别**:
```java
List<Scene> detectScenes(String chapterContent) {
    // 规则：时间/地点变化 = 新场景
    // 模型：使用 GLM-4-Flash 识别场景边界
}
```

**Embedding 生成**:
- 模型: 智谱 embedding-2
- 维度: 1024
- 批量大小: 10

**索引结构**:
```json
{
  "id": "chunk_001",
  "projectId": "novel_123",
  "chapterId": "chapter_3",
  "sceneId": "scene_005",
  "text": "张伟站在北京街头，望着远方的霓虹灯...",
  "embedding": [0.123, 0.456, ...],
  "metadata": {
    "characters": ["张伟"],
    "location": "北京",
    "timestamp": "2026-04-01T20:00:00Z",
    "eventType": "reflection"
  }
}
```

**检索策略**:
```java
List<DocChunk> retrieve(String projectId, String query, int topK) {
    // 1. 生成查询向量
    float[] queryVec = embeddingClient.embed(query);
    
    // 2. 向量检索
    List<DocChunk> chunks = vectorStore.search(projectId, queryVec, topK);
    
    // 3. 过滤低相似度结果
    return chunks.stream()
        .filter(c -> c.similarity() > 0.7)
        .collect(Collectors.toList());
}
```

**验收标准**:
- [ ] 能正确识别场景边界
- [ ] Embedding 生成正常
- [ ] 检索结果相关性 > 0.7
- [ ] 检索延迟 < 500ms

---

### 3.3 工作记忆

#### 功能描述

存储当前小说的状态，包括角色位置、伏笔、冲突等。

#### 功能规格

**状态结构**:
```json
{
  "projectId": "novel_123",
  "currentChapter": 3,
  "chapterGoal": "张伟发现真相",
  "characterLocations": {
    "张伟": "北京",
    "李明": "上海"
  },
  "foreshadowings": [
    {
      "id": "fs_001",
      "description": "张伟收到的神秘信件",
      "plantedChapter": 1,
      "resolved": false
    }
  ],
  "activeConflicts": [
    {
      "type": "interpersonal",
      "parties": ["张伟", "李明"],
      "status": "escalating",
      "sinceChapter": 2
    }
  ],
  "timeline": [
    {
      "event": "张伟到达北京",
      "chapter": 1,
      "timestamp": "2026-04-01T10:00:00Z"
    }
  ]
}
```

**状态更新**:
```java
void updateState(String projectId, Chapter newChapter) {
    WorkingState state = stateStore.get(projectId);
    
    // 1. 更新角色位置
    state.updateCharacterLocations(extractLocations(newChapter));
    
    // 2. 添加新伏笔
    state.addForeshadowings(detectForeshadowings(newChapter));
    
    // 3. 更新冲突状态
    state.updateConflicts(analyzeConflicts(newChapter));
    
    // 4. 添加时间线事件
    state.addTimelineEvents(extractEvents(newChapter));
    
    stateStore.save(projectId, state);
}
```

**验收标准**:
- [ ] 能正确提取角色位置
- [ ] 能识别新伏笔
- [ ] 能更新冲突状态
- [ ] 状态持久化正常

---

## 4. 工具调用模块

### 4.1 CharacterArcPlanner（角色弧光规划器）

#### 功能描述

分析角色的成长轨迹，规划起点-转折-终点弧光。

#### 功能规格

**输入参数**:
```json
{
  "characterName": "张伟",
  "chapters": [
    {
      "chapterId": "chapter_1",
      "content": "第1章内容..."
    },
    {
      "chapterId": "chapter_2",
      "content": "第2章内容..."
    }
  ],
  "analysisDepth": "detailed"
}
```

**输出结果**:
```json
{
  "characterName": "张伟",
  "arcScore": 0.65,
  "stages": [
    {
      "chapter": "第1章",
      "goal": "生存",
      "conflict": "失业危机",
      "belief": "金钱至上",
      "evidence": "张伟盯着银行卡余额，叹了口气"
    },
    {
      "chapter": "第5章",
      "goal": "自我实现",
      "conflict": "道德困境",
      "belief": "价值重估",
      "evidence": "张伟拒绝了高薪offer，选择创业"
    }
  ],
  "suggestions": [
    {
      "type": "TURNING_POINT",
      "description": "建议在第3章增加一个转折事件",
      "reason": "当前信念转变缺乏铺垫"
    }
  ]
}
```

**分析维度**:
1. **目标变化**: 角色的目标如何演变
2. **冲突升级**: 角色面临的冲突如何升级
3. **信念转变**: 角色的核心价值观如何变化
4. **行为一致性**: 角色的行为是否符合性格

**评分算法**:
```java
double calculateArcScore(List<Stage> stages) {
    double goalClarity = evaluateGoalClarity(stages);
    double conflictIntensity = evaluateConflictIntensity(stages);
    double beliefTransformation = evaluateBeliefTransformation(stages);
    double consistency = evaluateConsistency(stages);
    
    return (goalClarity + conflictIntensity + beliefTransformation + consistency) / 4.0;
}
```

**验收标准**:
- [ ] 能正确识别角色目标、冲突、信念
- [ ] 弧光评分合理（人工验证）
- [ ] 建议具有可操作性
- [ ] 执行时间 < 5秒

---

### 4.2 PlotGapDetector（情节漏洞检测器）

#### 功能描述

检测情节因果断裂、动机缺失、时间线冲突。

#### 功能规格

**输入参数**:
```json
{
  "chapters": [
    {
      "chapterId": "chapter_3",
      "events": [
        {
          "event": "张伟站在北京街头",
          "characters": ["张伟"],
          "location": "北京",
          "timestamp": "2026-04-01T20:00:00Z"
        }
      ]
    },
    {
      "chapterId": "chapter_4",
      "events": [
        {
          "event": "张伟推开上海的家门",
          "characters": ["张伟"],
          "location": "上海",
          "timestamp": "2026-04-01T21:00:00Z"
        }
      ]
    }
  ],
  "focusType": "all"
}
```

**输出结果**:
```json
{
  "gaps": [
    {
      "type": "CHARACTER_TELEPORT",
      "severity": "high",
      "description": "张伟在第3章结尾在北京，第4章开头突然在上海",
      "location": {
        "chapter": "第3-4章",
        "evidence": [
          "第3章: 张伟站在北京街头，望着远方的霓虹灯",
          "第4章: 张伟推开上海的家门，疲惫地坐在沙发上"
        ]
      },
      "suggestion": "增加过渡场景或说明交通方式"
    }
  ],
  "summary": {
    "totalGaps": 1,
    "highSeverity": 1,
    "mediumSeverity": 0,
    "lowSeverity": 0
  }
}
```

**检测类型**:

| 漏洞类型 | 描述 | 严重程度 |
|---------|------|---------|
| CHARACTER_TELEPORT | 角色瞬移 | high |
| MOTIVATION_MISSING | 动机缺失 | medium |
| TIMELINE_CONFLICT | 时间线冲突 | high |
| CAUSALITY_BREAK | 因果断裂 | high |
| FORESHADOWING_UNRESOLVED | 伏笔未回收 | low |

**检测算法**:
```java
List<Gap> detectGaps(List<Chapter> chapters) {
    List<Gap> gaps = new ArrayList<>();
    
    // 1. 检测角色瞬移
    gaps.addAll(detectCharacterTeleport(chapters));
    
    // 2. 检测动机缺失
    gaps.addAll(detectMotivationMissing(chapters));
    
    // 3. 检测时间线冲突
    gaps.addAll(detectTimelineConflict(chapters));
    
    // 4. 检测因果断裂
    gaps.addAll(detectCausalityBreak(chapters));
    
    return gaps;
}
```

**验收标准**:
- [ ] 能检测角色瞬移（准确率 > 90%）
- [ ] 能检测动机缺失（准确率 > 70%）
- [ ] 能检测时间线冲突（准确率 > 80%）
- [ ] 建议具有可操作性
- [ ] 执行时间 < 5秒

---

### 4.3 StyleTransfer（风格迁移）

#### 功能描述

按目标文风进行可控改写。

#### 功能规格

**输入参数**:
```json
{
  "text": "他说：'我不想去了。'",
  "targetStyle": "古风",
  "constraints": {
    "preserveKeywords": ["不想"],
    "sentenceLengthRange": {
      "min": 5,
      "max": 20
    },
    "forbiddenWords": ["现代词汇"]
  }
}
```

**输出结果**:
```json
{
  "rewrittenText": "他沉声道：'吾心已倦，不愿前行。'",
  "styleScore": 0.82,
  "changes": [
    {
      "original": "他说",
      "rewritten": "他沉声道",
      "reason": "增强古风语气"
    },
    {
      "original": "我不想去了",
      "rewritten": "吾心已倦，不愿前行",
      "reason": "使用古风表达"
    }
  ]
}
```

**支持的风格**:
- 古风
- 现代
- 科幻
- 悬疑
- 幽默

**约束处理**:
```java
String applyConstraints(String text, Constraints constraints) {
    // 1. 保留关键词
    text = preserveKeywords(text, constraints.getPreserveKeywords());
    
    // 2. 调整句长
    text = adjustSentenceLength(text, constraints.getSentenceLengthRange());
    
    // 3. 移除禁止词
    text = removeForbiddenWords(text, constraints.getForbiddenWords());
    
    return text;
}
```

**验收标准**:
- [ ] 能正确改写为指定风格
- [ ] 风格评分 > 0.7
- [ ] 约束条件满足
- [ ] 执行时间 < 5秒

---

## 5. 模型网关模块

### 5.1 模型路由

#### 功能描述

根据请求类型和成本策略，选择合适的模型。

#### 功能规格

**路由策略**:
```yaml
routing:
  rules:
    - intent: ANALYZE
      model: glm-4-flash
      reason: "分析任务需要高质量输出"
    
    - intent: CONTINUE
      model: glm-4-flash
      reason: "续写任务需要创造力"
    
    - intent: GENERAL_CHAT
      model: glm-4-flash
      reason: "对话任务成本敏感"
```

**Fallback 策略**:
```java
Flux<ModelChunk> chatStream(ModelRequest request, RoutingPolicy policy) {
    List<ModelAdapter> adapters = getAvailableAdapters(policy);
    
    for (ModelAdapter adapter : adapters) {
        try {
            return adapter.chatStream(request);
        } catch (Exception e) {
            log.warn("Model {} failed, trying next", adapter.name());
        }
    }
    
    return Flux.error(new NoModelAvailableException());
}
```

**验收标准**:
- [ ] 能根据意图选择模型
- [ ] Fallback 机制正常工作
- [ ] 成本追踪准确

---

### 5.2 成本追踪

#### 功能描述

记录每次模型调用的 token 数和预估费用。

#### 功能规格

**成本计算**:
```java
BigDecimal calculateCost(String modelName, int tokenCount) {
    BigDecimal costPer1kTokens = getModelCost(modelName);
    return costPer1kTokens.multiply(BigDecimal.valueOf(tokenCount / 1000.0));
}
```

**日志格式**:
```
[traceId=abc123] Model call: model=glm-4-flash, tokens=150, cost=$0.000015
```

**预算控制**:
```java
void checkBudget(String projectId) {
    BigDecimal todayCost = costTracker.getTodayCost(projectId);
    BigDecimal limit = new BigDecimal("1.0");
    
    if (todayCost.compareTo(limit) >= 0) {
        throw new BudgetExceededException("Daily budget exceeded");
    }
}
```

**验收标准**:
- [ ] Token 统计准确
- [ ] 成本计算准确
- [ ] 预算限制生效

---

## 6. MCP 服务模块

### 6.1 MCP Server

#### 功能描述

通过 JSON-RPC over stdio 暴露工具能力。

#### 功能规格

**协议**: JSON-RPC 2.0 over stdio

**支持的方法**:

| 方法 | 说明 |
|------|------|
| `tools/list` | 列出所有可用工具 |
| `tools/call` | 调用指定工具 |

**请求示例**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/call",
  "params": {
    "name": "character_arc_planner",
    "arguments": {
      "characterName": "张伟",
      "chapters": [...]
    }
  }
}
```

**响应示例**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "characterName": "张伟",
    "arcScore": 0.65,
    ...
  }
}
```

**验收标准**:
- [ ] 能正确处理 JSON-RPC 请求
- [ ] 能暴露所有工具
- [ ] 错误响应符合规范

---

## 7. 非功能性需求

### 7.1 性能需求

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| 首token延迟 | < 3秒 | 从请求到第一个token返回 |
| 工具执行时间 | < 5秒 | 单个工具调用耗时 |
| 向量检索延迟 | < 500ms | Milvus 查询耗时 |
| 总响应时间 | < 30秒 | 包含所有工具调用和模型生成 |

### 7.2 可用性需求

| 指标 | 目标值 |
|------|--------|
| 系统可用性 | > 95% |
| 错误恢复时间 | < 1分钟 |
| 数据持久性 | 100% |

### 7.3 可扩展性需求

- 支持新增工具（通过 MCP）
- 支持新增模型（通过 ModelGateway）
- 支持新增向量库（通过 VectorStore 接口）

---

## 8. 验收标准总览

### 8.1 功能验收

- [ ] 用户能通过命令行与 Agent 对话，完成至少 3 轮交互
- [ ] Agent 能正确识别 5 种意图（准确率 > 80%）
- [ ] Agent 能调用 CharacterArcPlanner 并输出弧光分析
- [ ] Agent 能检测到"角色瞬移"类逻辑漏洞
- [ ] Agent 能根据上次续写内容，自动更新角色位置和伏笔列表
- [ ] 流式输出正常，无卡顿
- [ ] 日志中包含 traceId 和每次模型调用的 token 费用

### 8.2 性能验收

- [ ] 首token延迟 < 3秒（P95）
- [ ] 单次请求总耗时 < 30秒（P95）
- [ ] 向量检索延迟 < 500ms（P95）

### 8.3 成本验收

- [ ] 成本追踪功能正常
- [ ] 每日预算限制生效
- [ ] 成本超限告警正常
