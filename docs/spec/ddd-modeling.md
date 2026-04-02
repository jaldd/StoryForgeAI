# DDD 领域建模与详细设计

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 领域分析

### 1.1 问题域

**核心问题**: 如何通过 AI Agent 技术辅助小说作者进行创作，确保长篇小说的一致性和质量？

**子域划分**:

```
小说创作域
├── 核心子域（Core Domain）
│   ├── 创作辅助
│   │   ├── 角色弧光分析
│   │   ├── 情节漏洞检测
│   │   └── 风格迁移
│   └── 智能续写
│       ├── 上下文构建
│       └── 状态追踪
├── 支撑子域（Supporting Domain）
│   ├── 记忆管理
│   │   ├── 短期记忆
│   │   ├── 长期记忆
│   │   └── 工作记忆
│   └── 意图识别
└── 通用子域（Generic Domain）
    ├── 模型网关
    ├── 工具调用
    └── MCP 服务
```

---

## 2. 限界上下文（Bounded Context）

### 2.1 上下文映射图

```
┌─────────────────────────────────────────────────────────┐
│                  创作辅助上下文                            │
│  (Writing Assistance Context)                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Aggregate: NovelProject                         │   │
│  │  - Chapter                                       │   │
│  │  - Character                                     │   │
│  │  - Scene                                        │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
          ↓ (U)                    ↓ (U)
┌─────────────────────┐  ┌──────────────────────────────┐
│  记忆管理上下文      │  │    工具调用上下文              │
│  (Memory Context)   │  │  (Tool Context)              │
│  ┌───────────────┐  │  │  ┌────────────────────────┐ │
│  │ ShortTermMem  │  │  │  │ ToolRegistry           │ │
│  │ LongTermMem   │  │  │  │ ToolExecutor           │ │
│  │ WorkingState  │  │  │  │ McpClient              │ │
│  └───────────────┘  │  │  └────────────────────────┘ │
└─────────────────────┘  └──────────────────────────────┘
          ↓ (D)                    ↓ (D)
┌─────────────────────────────────────────────────────────┐
│                  模型网关上下文                            │
│  (Model Gateway Context)                                │
│  ┌─────────────────────────────────────────────────┐   │
│  │  ModelGateway                                    │   │
│  │  ModelAdapter                                    │   │
│  │  CostTracker                                     │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

图例:
U = Upstream（上游）
D = Downstream（下游）
```

### 2.2 上下文定义

#### 2.2.1 创作辅助上下文

**职责**: 管理小说项目的核心业务逻辑

**聚合**:
- NovelProject（小说项目）
- Chapter（章节）
- Character（角色）

**领域服务**:
- CharacterArcAnalyzer（角色弧光分析）
- PlotGapAnalyzer（情节漏洞分析）
- StyleTransformer（风格迁移）

---

#### 2.2.2 记忆管理上下文

**职责**: 管理三层记忆系统

**实体**:
- ShortTermMemory（短期记忆）
- WorkingState（工作记忆）

**值对象**:
- MemoryChunk（记忆块）
- Foreshadowing（伏笔）
- Conflict（冲突）

**领域服务**:
- ContextBuilder（上下文构建器）
- StateUpdater（状态更新器）

---

#### 2.2.3 工具调用上下文

**职责**: 管理工具注册和执行

**实体**:
- Tool（工具）

**值对象**:
- ToolCall（工具调用）
- ToolResult（工具结果）

**领域服务**:
- ToolExecutor（工具执行器）

---

#### 2.2.4 模型网关上下文

**职责**: 管理模型调用和成本追踪

**实体**:
- ModelAdapter（模型适配器）

**值对象**:
- ModelRequest（模型请求）
- ModelResponse（模型响应）
- CostRecord（成本记录）

**领域服务**:
- ModelRouter（模型路由器）
- CostCalculator（成本计算器）

---

## 3. 聚合设计

### 3.1 NovelProject 聚合

**聚合根**: NovelProject

**边界**: 一个小说项目及其所有章节、角色、场景

```java
public class NovelProject {
    private NovelProjectId projectId;
    private String title;
    private String author;
    private List<Chapter> chapters;
    private List<Character> characters;
    private WorkingState workingState;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    
    public void addChapter(Chapter chapter) {
        chapters.add(chapter);
        workingState.updateFromChapter(chapter);
        this.updatedAt = LocalDateTime.now();
    }
    
    public void updateWorkingState(WorkingState newState) {
        this.workingState = newState;
        this.updatedAt = LocalDateTime.now();
    }
    
    public List<Scene> getAllScenes() {
        return chapters.stream()
            .flatMap(chapter -> chapter.getScenes().stream())
            .collect(Collectors.toList());
    }
}
```

**不变性约束**:
1. 一个项目至少有一个章节
2. 章节编号必须唯一且连续
3. 工作状态必须与最新章节同步

---

### 3.2 Chapter 聚合

**聚合根**: Chapter

**边界**: 一个章节及其所有场景

```java
public class Chapter {
    private ChapterId chapterId;
    private NovelProjectId projectId;
    private int chapterNumber;
    private String title;
    private String content;
    private List<Scene> scenes;
    private List<String> characterNames;
    private LocalDateTime createdAt;
    
    public void addScene(Scene scene) {
        scenes.add(scene);
        characterNames.addAll(scene.getCharacterNames());
    }
    
    public List<String> extractCharacterNames() {
        return scenes.stream()
            .flatMap(scene -> scene.getCharacterNames().stream())
            .distinct()
            .collect(Collectors.toList());
    }
}
```

**不变性约束**:
1. 章节编号必须 > 0
2. 至少有一个场景
3. 内容不能为空

---

### 3.3 Character 聚合

**聚合根**: Character

**边界**: 一个角色及其弧光轨迹

```java
public class Character {
    private CharacterId characterId;
    private NovelProjectId projectId;
    private String name;
    private String description;
    private List<CharacterArcStage> arcStages;
    private LocalDateTime createdAt;
    
    public void addArcStage(CharacterArcStage stage) {
        arcStages.add(stage);
    }
    
    public double calculateArcScore() {
        if (arcStages.size() < 2) {
            return 0.0;
        }
        
        double goalClarity = evaluateGoalClarity();
        double conflictIntensity = evaluateConflictIntensity();
        double beliefTransformation = evaluateBeliefTransformation();
        
        return (goalClarity + conflictIntensity + beliefTransformation) / 3.0;
    }
}
```

**不变性约束**:
1. 角色名称在项目内唯一
2. 弧光阶段按章节顺序排列

---

## 4. 实体与值对象

### 4.1 实体（Entity）

#### 4.1.1 NovelProject

```java
public class NovelProject {
    private NovelProjectId projectId;  // 唯一标识
    private String title;
    private String author;
    private List<Chapter> chapters;
    private List<Character> characters;
    private WorkingState workingState;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
```

#### 4.1.2 Chapter

```java
public class Chapter {
    private ChapterId chapterId;  // 唯一标识
    private NovelProjectId projectId;
    private int chapterNumber;
    private String title;
    private String content;
    private List<Scene> scenes;
    private List<String> characterNames;
    private LocalDateTime createdAt;
}
```

#### 4.1.3 Character

```java
public class Character {
    private CharacterId characterId;  // 唯一标识
    private NovelProjectId projectId;
    private String name;
    private String description;
    private List<CharacterArcStage> arcStages;
    private LocalDateTime createdAt;
}
```

#### 4.1.4 ShortTermMemory

```java
public class ShortTermMemory {
    private MemoryId memoryId;  // 唯一标识
    private NovelProjectId projectId;
    private List<Turn> turns;
    private int windowSize;
    private LocalDateTime updatedAt;
}
```

#### 4.1.5 WorkingState

```java
public class WorkingState {
    private StateId stateId;  // 唯一标识
    private NovelProjectId projectId;
    private int currentChapter;
    private String chapterGoal;
    private Map<String, String> characterLocations;
    private List<Foreshadowing> foreshadowings;
    private List<Conflict> activeConflicts;
    private List<TimelineEvent> timeline;
    private LocalDateTime updatedAt;
}
```

---

### 4.2 值对象（Value Object）

#### 4.2.1 NovelProjectId

```java
public record NovelProjectId(String value) {
    public NovelProjectId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Project ID cannot be null or blank");
        }
    }
}
```

#### 4.2.2 ChapterId

```java
public record ChapterId(String value) {
    public ChapterId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Chapter ID cannot be null or blank");
        }
    }
}
```

#### 4.2.3 CharacterId

```java
public record CharacterId(String value) {
    public CharacterId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Character ID cannot be null or blank");
        }
    }
}
```

#### 4.2.4 Scene

```java
public record Scene(
    String sceneId,
    String text,
    List<String> characterNames,
    String location,
    LocalDateTime timestamp,
    String eventType
) {
    public Scene {
        if (text == null || text.isBlank()) {
            throw new IllegalArgumentException("Scene text cannot be null or blank");
        }
    }
}
```

#### 4.2.5 CharacterArcStage

```java
public record CharacterArcStage(
    int chapter,
    String goal,
    String conflict,
    String belief,
    String evidence
) {
    public CharacterArcStage {
        if (chapter <= 0) {
            throw new IllegalArgumentException("Chapter must be positive");
        }
    }
}
```

#### 4.2.6 Foreshadowing

```java
public record Foreshadowing(
    String id,
    String description,
    int plantedChapter,
    boolean resolved
) {
    public Foreshadowing {
        if (plantedChapter <= 0) {
            throw new IllegalArgumentException("Planted chapter must be positive");
        }
    }
}
```

#### 4.2.7 Conflict

```java
public record Conflict(
    String type,
    List<String> parties,
    String status,
    int sinceChapter
) {
    public Conflict {
        if (parties == null || parties.isEmpty()) {
            throw new IllegalArgumentException("Conflict must have at least one party");
        }
    }
}
```

#### 4.2.8 TimelineEvent

```java
public record TimelineEvent(
    String event,
    int chapter,
    LocalDateTime timestamp
) {
    public TimelineEvent {
        if (event == null || event.isBlank()) {
            throw new IllegalArgumentException("Event cannot be null or blank");
        }
    }
}
```

#### 4.2.9 Turn

```java
public record Turn(
    String turnId,
    String role,
    String content,
    LocalDateTime timestamp,
    Map<String, Object> metadata
) {
    public Turn {
        if (role == null || (!role.equals("user") && !role.equals("assistant"))) {
            throw new IllegalArgumentException("Role must be 'user' or 'assistant'");
        }
    }
}
```

#### 4.2.10 MemoryChunk

```java
public record MemoryChunk(
    String chunkId,
    NovelProjectId projectId,
    ChapterId chapterId,
    String text,
    float[] embedding,
    Map<String, Object> metadata
) {
    public MemoryChunk {
        if (embedding == null || embedding.length == 0) {
            throw new IllegalArgumentException("Embedding cannot be null or empty");
        }
    }
}
```

#### 4.2.11 ToolCall

```java
public record ToolCall(
    String toolName,
    Map<String, Object> arguments,
    boolean viaMcp
) {
    public ToolCall {
        if (toolName == null || toolName.isBlank()) {
            throw new IllegalArgumentException("Tool name cannot be null or blank");
        }
    }
}
```

#### 4.2.12 ToolResult

```java
public record ToolResult(
    String toolName,
    boolean success,
    Object output,
    String errorCode,
    String errorMessage
) {
    public static ToolResult success(String toolName, Object output) {
        return new ToolResult(toolName, true, output, null, null);
    }
    
    public static ToolResult failure(String toolName, String errorCode, String errorMessage) {
        return new ToolResult(toolName, false, null, errorCode, errorMessage);
    }
}
```

#### 4.2.13 ModelRequest

```java
public record ModelRequest(
    String prompt,
    Map<String, Object> parameters,
    int estimatedTokens
) {
    public ModelRequest {
        if (prompt == null || prompt.isBlank()) {
            throw new IllegalArgumentException("Prompt cannot be null or blank");
        }
    }
}
```

#### 4.2.14 ModelResponse

```java
public record ModelResponse(
    String content,
    int tokenCount,
    BigDecimal cost,
    String modelName
) {
    public ModelResponse {
        if (content == null) {
            throw new IllegalArgumentException("Content cannot be null");
        }
    }
}
```

---

## 5. 领域服务

### 5.1 CharacterArcAnalyzer

**职责**: 分析角色弧光，计算弧光评分

```java
public interface CharacterArcAnalyzer {
    CharacterArcAnalysis analyze(Character character, List<Chapter> chapters);
    double calculateArcScore(List<CharacterArcStage> stages);
    List<ArcSuggestion> generateSuggestions(CharacterArcAnalysis analysis);
}
```

**实现**:
```java
public class CharacterArcAnalyzerImpl implements CharacterArcAnalyzer {
    
    @Override
    public CharacterArcAnalysis analyze(Character character, List<Chapter> chapters) {
        List<CharacterArcStage> stages = extractStages(character, chapters);
        double score = calculateArcScore(stages);
        List<ArcSuggestion> suggestions = generateSuggestions(new CharacterArcAnalysis(stages, score));
        
        return new CharacterArcAnalysis(character.getName(), stages, score, suggestions);
    }
    
    @Override
    public double calculateArcScore(List<CharacterArcStage> stages) {
        if (stages.size() < 2) {
            return 0.0;
        }
        
        double goalClarity = evaluateGoalClarity(stages);
        double conflictIntensity = evaluateConflictIntensity(stages);
        double beliefTransformation = evaluateBeliefTransformation(stages);
        double consistency = evaluateConsistency(stages);
        
        return (goalClarity + conflictIntensity + beliefTransformation + consistency) / 4.0;
    }
    
    private List<CharacterArcStage> extractStages(Character character, List<Chapter> chapters) {
        // 使用模型提取角色的目标、冲突、信念
    }
}
```

---

### 5.2 PlotGapAnalyzer

**职责**: 检测情节漏洞

```java
public interface PlotGapAnalyzer {
    List<PlotGap> detectGaps(List<Chapter> chapters);
    PlotGapSummary summarize(List<PlotGap> gaps);
}
```

**实现**:
```java
public class PlotGapAnalyzerImpl implements PlotGapAnalyzer {
    
    @Override
    public List<PlotGap> detectGaps(List<Chapter> chapters) {
        List<PlotGap> gaps = new ArrayList<>();
        
        gaps.addAll(detectCharacterTeleport(chapters));
        gaps.addAll(detectMotivationMissing(chapters));
        gaps.addAll(detectTimelineConflict(chapters));
        gaps.addAll(detectCausalityBreak(chapters));
        
        return gaps;
    }
    
    private List<PlotGap> detectCharacterTeleport(List<Chapter> chapters) {
        List<PlotGap> gaps = new ArrayList<>();
        
        for (int i = 0; i < chapters.size() - 1; i++) {
            Chapter current = chapters.get(i);
            Chapter next = chapters.get(i + 1);
            
            // 检测角色位置突变
            gaps.addAll(findTeleportGaps(current, next));
        }
        
        return gaps;
    }
}
```

---

### 5.3 ContextBuilder

**职责**: 构建上下文包

```java
public interface ContextBuilder {
    ContextBundle build(NovelProjectId projectId, String userInput, int tokenBudget);
}
```

**实现**:
```java
public class ContextBuilderImpl implements ContextBuilder {
    
    private final ShortTermMemoryRepository shortTermMemoryRepo;
    private final LongTermMemoryRepository longTermMemoryRepo;
    private final WorkingStateRepository workingStateRepo;
    
    @Override
    public ContextBundle build(NovelProjectId projectId, String userInput, int tokenBudget) {
        // 1. 短期记忆
        List<Turn> shortTermMemory = shortTermMemoryRepo.getWindow(projectId, 10);
        
        // 2. 长期记忆
        List<MemoryChunk> relevantChunks = longTermMemoryRepo.retrieve(projectId, userInput, 5);
        
        // 3. 工作记忆
        WorkingState workingState = workingStateRepo.get(projectId);
        
        return new ContextBundle(shortTermMemory, relevantChunks, workingState);
    }
}
```

---

### 5.4 ModelRouter

**职责**: 路由模型请求

```java
public interface ModelRouter {
    ModelAdapter selectModel(IntentType intent, RoutingPolicy policy);
    List<ModelAdapter> getFallbackChain(RoutingPolicy policy);
}
```

**实现**:
```java
public class ModelRouterImpl implements ModelRouter {
    
    private final Map<String, ModelAdapter> adapters;
    private final RoutingPolicy defaultPolicy;
    
    @Override
    public ModelAdapter selectModel(IntentType intent, RoutingPolicy policy) {
        String modelName = policy.getModelForIntent(intent);
        return adapters.get(modelName);
    }
    
    @Override
    public List<ModelAdapter> getFallbackChain(RoutingPolicy policy) {
        return policy.getFallbackModels().stream()
            .map(adapters::get)
            .collect(Collectors.toList());
    }
}
```

---

## 6. 应用服务

### 6.1 WritingAgentService

**职责**: 协调整个创作辅助流程

```java
public interface WritingAgentService {
    Flux<TokenChunk> handleUserRequest(UserRequest request);
    AgentResponse analyzeCharacter(NovelProjectId projectId, String characterName);
    AgentResponse continueWriting(NovelProjectId projectId, int chapterNumber);
}
```

**实现**:
```java
public class WritingAgentServiceImpl implements WritingAgentService {
    
    private final IntentRouter intentRouter;
    private final ContextBuilder contextBuilder;
    private final ToolExecutor toolExecutor;
    private final ModelGateway modelGateway;
    private final MemoryManager memoryManager;
    
    @Override
    public Flux<TokenChunk> handleUserRequest(UserRequest request) {
        // 1. 意图识别
        IntentType intent = intentRouter.detect(request.text());
        
        // 2. 上下文构建
        ContextBundle context = contextBuilder.build(request.projectId(), request.text(), 12000);
        
        // 3. 工具调用（可选）
        List<ToolResult> toolResults = executeTools(intent, context);
        
        // 4. 模型生成
        PromptBundle prompt = buildPrompt(request, context, toolResults);
        Flux<TokenChunk> stream = modelGateway.chatStream(prompt, ModelPolicy.defaultPolicy());
        
        // 5. 状态持久化
        stream.doOnComplete(() -> persistTurn(request, context));
        
        return stream;
    }
}
```

---

### 6.2 MemoryService

**职责**: 管理三层记忆

```java
public interface MemoryService {
    void appendShortTermMemory(NovelProjectId projectId, Turn turn);
    List<Turn> getShortTermMemory(NovelProjectId projectId, int windowSize);
    
    void indexChapter(NovelProjectId projectId, Chapter chapter);
    List<MemoryChunk> retrieveLongTermMemory(NovelProjectId projectId, String query, int topK);
    
    WorkingState getWorkingState(NovelProjectId projectId);
    void updateWorkingState(NovelProjectId projectId, WorkingState state);
}
```

---

## 7. 仓储（Repository）

### 7.1 NovelProjectRepository

```java
public interface NovelProjectRepository {
    NovelProject findById(NovelProjectId projectId);
    void save(NovelProject project);
    void delete(NovelProjectId projectId);
    List<NovelProject> findByAuthor(String author);
}
```

---

### 7.2 ChapterRepository

```java
public interface ChapterRepository {
    Chapter findById(ChapterId chapterId);
    List<Chapter> findByProjectId(NovelProjectId projectId);
    void save(Chapter chapter);
    void delete(ChapterId chapterId);
}
```

---

### 7.3 ShortTermMemoryRepository

```java
public interface ShortTermMemoryRepository {
    void append(NovelProjectId projectId, Turn turn);
    List<Turn> getWindow(NovelProjectId projectId, int windowSize);
    void clear(NovelProjectId projectId);
}
```

---

### 7.4 LongTermMemoryRepository

```java
public interface LongTermMemoryRepository {
    void index(NovelProjectId projectId, List<MemoryChunk> chunks);
    List<MemoryChunk> retrieve(NovelProjectId projectId, String query, int topK);
    void deleteByProjectId(NovelProjectId projectId);
}
```

---

### 7.5 WorkingStateRepository

```java
public interface WorkingStateRepository {
    WorkingState get(NovelProjectId projectId);
    void save(NovelProjectId projectId, WorkingState state);
    void delete(NovelProjectId projectId);
}
```

---

## 8. 领域事件

### 8.1 事件定义

#### 8.1.1 ChapterAddedEvent

```java
public record ChapterAddedEvent(
    NovelProjectId projectId,
    ChapterId chapterId,
    int chapterNumber,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

#### 8.1.2 CharacterArcAnalyzedEvent

```java
public record CharacterArcAnalyzedEvent(
    CharacterId characterId,
    double arcScore,
    List<ArcSuggestion> suggestions,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

#### 8.1.3 PlotGapDetectedEvent

```java
public record PlotGapDetectedEvent(
    NovelProjectId projectId,
    List<PlotGap> gaps,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

### 8.2 事件处理器

```java
public class ChapterAddedEventHandler implements DomainEventHandler<ChapterAddedEvent> {
    
    private final MemoryService memoryService;
    
    @Override
    public void handle(ChapterAddedEvent event) {
        // 1. 将新章节索引到长期记忆
        Chapter chapter = chapterRepository.findById(event.chapterId());
        memoryService.indexChapter(event.projectId(), chapter);
        
        // 2. 更新工作记忆
        WorkingState state = memoryService.getWorkingState(event.projectId());
        state.updateFromChapter(chapter);
        memoryService.updateWorkingState(event.projectId(), state);
    }
}
```

---

## 9. 模块依赖关系

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 (Application)                  │
│  WritingAgentService, MemoryService                     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    领域层 (Domain)                       │
│  NovelProject, Chapter, Character                       │
│  CharacterArcAnalyzer, PlotGapAnalyzer, ContextBuilder  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    基础设施层 (Infrastructure)           │
│  NovelProjectRepository, ChapterRepository              │
│  ShortTermMemoryRepository, LongTermMemoryRepository    │
│  WorkingStateRepository                                 │
└─────────────────────────────────────────────────────────┘
```

---

## 10. 设计原则遵循

### 10.1 DDD 原则

1. **聚合原则**: NovelProject、Chapter、Character 作为聚合根，保证事务一致性
2. **值对象不可变**: 所有值对象使用 Java Record，保证不可变性
3. **领域服务无状态**: CharacterArcAnalyzer、PlotGapAnalyzer 等领域服务无状态
4. **仓储只负责持久化**: 仓储不包含业务逻辑

### 10.2 SOLID 原则

1. **单一职责**: 每个类职责单一，如 CharacterArcAnalyzer 只负责角色弧光分析
2. **开闭原则**: 通过接口抽象，支持扩展（如新增工具、模型）
3. **里氏替换**: 所有实现类可替换接口
4. **接口隔离**: 接口粒度适中，不强迫实现不需要的方法
5. **依赖倒置**: 高层模块依赖抽象接口，不依赖具体实现

---

## 11. 下一步

1. **生成技术方案**: 详细的技术实现方案
2. **分解任务列表**: 可执行的开发任务
