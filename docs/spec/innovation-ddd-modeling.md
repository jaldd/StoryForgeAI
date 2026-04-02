# 创新功能领域建模

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 创新子域分析

### 1.1 子域划分

```
创新子域
├── 角色模拟子域（Character Simulation）
│   ├── 角色状态管理
│   ├── 角色决策引擎
│   └── 多角色协调
├── 反事实推理子域（Counterfactual Reasoning）
│   ├── 反事实路径生成
│   ├── 伏笔推导
│   └── 伏笔验证
├── 故事规划子域（Story Planning）
│   ├── 故事图构建
│   ├── 符号规划
│   └── 一致性验证
├── 叙事编辑子域（Narrative Editing）
│   ├── 因果依赖管理
│   ├── 回滚计算
│   └── 补丁应用
└── 约束求解子域（Constraint Solving）
    ├── 约束建模
    ├── 约束求解
    └── 解空间输出
```

---

## 2. 限界上下文

### 2.1 角色模拟上下文（Character Simulation Context）

**职责**: 管理角色状态和决策

**聚合**:
- CharacterMind（角色心智）

**实体**:
- CharacterState（角色状态）

**值对象**:
- Goal（目标）
- Belief（信念）
- Emotion（情绪）
- Decision（决策）

---

### 2.2 反事实推理上下文（Counterfactual Reasoning Context）

**职责**: 生成反事实路径和推导伏笔

**聚合**:
- CounterfactualScenario（反事实场景）

**实体**:
- CounterfactualPath（反事实路径）

**值对象**:
- Foreshadowing（伏笔）
- Dependency（依赖关系）

---

### 2.3 故事规划上下文（Story Planning Context）

**职责**: 构建故事图和规划行动序列

**聚合**:
- StoryGraph（故事图）

**实体**:
- Scene（场景）
- Transition（转换）

**值对象**:
- ActionSequence（行动序列）

---

### 2.4 叙事编辑上下文（Narrative Editing Context）

**职责**: 管理因果依赖和支持回滚

**聚合**:
- CausalGraph（因果图）

**实体**:
- Paragraph（段落）

**值对象**:
- Dependency（依赖）
- RollbackPoint（回滚点）

---

### 2.5 约束求解上下文（Constraint Solving Context）

**职责**: 建模和求解叙事约束

**聚合**:
- NarrativeConstraint（叙事约束）

**实体**:
- Constraint（约束）

**值对象**:
- NarrativeSpec（叙事规格）
- SolutionSpace（解空间）

---

## 3. 聚合设计

### 3.1 CharacterMind 聚合

**聚合根**: CharacterMind

**边界**: 一个角色的完整心智状态

```java
public class CharacterMind {
    private CharacterId characterId;
    private CharacterState state;
    private List<Decision> recentDecisions;
    private LocalDateTime lastUpdated;
    
    public Decision decide(Event event) {
        // 1. 更新情绪
        state.updateEmotion(event);
        
        // 2. 评估目标
        Goal activeGoal = state.evaluateGoals(event);
        
        // 3. 生成决策
        Decision decision = generateDecision(event, activeGoal);
        
        // 4. 记录决策
        recentDecisions.add(decision);
        
        return decision;
    }
    
    public void updateState(CharacterState newState) {
        this.state = newState;
        this.lastUpdated = LocalDateTime.now();
    }
}
```

**不变性约束**:
1. 角色必须有至少一个目标
2. 情绪值在 [0, 1] 范围内
3. 决策历史不能为空（至少有初始状态）

---

### 3.2 CounterfactualScenario 聚合

**聚合根**: CounterfactualScenario

**边界**: 一个反事实推理场景

```java
public class CounterfactualScenario {
    private ScenarioId scenarioId;
    private Plot originalPlot;
    private Plot counterfactualPlot;
    private List<Foreshadowing> inferredForeshadowings;
    
    public List<Foreshadowing> inferForeshadowings() {
        // 1. 生成反事实路径
        counterfactualPlot = generateCounterfactual(originalPlot);
        
        // 2. 识别依赖关系
        List<Dependency> dependencies = identifyDependencies(originalPlot, counterfactualPlot);
        
        // 3. 推导伏笔
        inferredForeshadowings = deduceForeshadowings(dependencies);
        
        return inferredForeshadowings;
    }
}
```

**不变性约束**:
1. 原始情节不能为空
2. 反事实情节必须与原始情节有差异
3. 推导的伏笔必须有明确的依赖关系

---

### 3.3 StoryGraph 聚合

**聚合根**: StoryGraph

**边界**: 整个故事的空间-时间-因果图

```java
public class StoryGraph {
    private GraphId graphId;
    private NovelProjectId projectId;
    private List<Scene> scenes;
    private List<Transition> transitions;
    
    public ActionSequence plan(Goal goal, Constraints constraints) {
        // 1. 构建规划问题
        PlanningProblem problem = buildProblem(goal, constraints);
        
        // 2. 调用规划器
        ActionSequence sequence = planner.plan(problem);
        
        // 3. 验证一致性
        validate(sequence);
        
        return sequence;
    }
    
    public ValidationResult validate(ActionSequence sequence) {
        // 验证空间、时间、因果一致性
    }
}
```

**不变性约束**:
1. 场景不能重复
2. 转换必须连接已存在的场景
3. 图必须连通（无孤立场景）

---

### 3.4 CausalGraph 聚合

**聚合根**: CausalGraph

**边界**: 一个章节的因果依赖图

```java
public class CausalGraph {
    private GraphId graphId;
    private ChapterId chapterId;
    private List<Paragraph> paragraphs;
    private List<Dependency> dependencies;
    
    public RollbackPoint findMinimalRollback(Constraint violation) {
        // 1. 找到违反约束的段落
        List<Paragraph> violated = findViolated(violation);
        
        // 2. 找到所有依赖段落
        Set<Paragraph> dependent = findAllDependent(violated);
        
        // 3. 计算最小回滚点
        Paragraph earliest = findEarliest(violated, dependent);
        
        return new RollbackPoint(earliest, violated, dependent);
    }
    
    public void applyPatch(RollbackPoint point, List<Paragraph> newParagraphs) {
        // 应用补丁，替换段落
    }
}
```

**不变性约束**:
1. 段落顺序不能改变（除非应用补丁）
2. 依赖关系必须有向无环
3. 每个段落至少有一个依赖（除了首段）

---

### 3.5 NarrativeConstraint 聚合

**聚合根**: NarrativeConstraint

**边界**: 一个章节的所有约束

```java
public class NarrativeConstraint {
    private ConstraintId constraintId;
    private ChapterId chapterId;
    private Set<Constraint> constraints;
    private NarrativeSpec solution;
    
    public NarrativeSpec solve() {
        // 1. 建模约束
        ConstraintModel model = modelConstraints(constraints);
        
        // 2. 调用求解器
        SolutionSpace space = solver.solve(model);
        
        // 3. 生成叙事规格
        solution = generateSpec(space);
        
        return solution;
    }
    
    public boolean isFeasible() {
        return solution != null && solution.isFeasible();
    }
}
```

**不变性约束**:
1. 约束集合不能为空
2. 约束之间不能矛盾（求解器会检测）
3. 解必须满足所有硬约束

---

## 4. 实体与值对象

### 4.1 实体（Entity）

#### 4.1.1 CharacterState

```java
public class CharacterState {
    private CharacterId characterId;
    private String name;
    private Goal primaryGoal;
    private List<Goal> secondaryGoals;
    private Set<Belief> beliefs;
    private EmotionState emotionState;
    private Location currentLocation;
    private Map<CharacterId, Relationship> relationships;
    private List<Memory> memories;
    
    public void updateEmotion(Event event) {
        EmotionImpact impact = event.getImpact(characterId);
        emotionState.apply(impact);
    }
    
    public Goal evaluateGoals(Event event) {
        // 评估目标优先级
    }
}
```

---

#### 4.1.2 Scene

```java
public class Scene {
    private SceneId sceneId;
    private Location location;
    private LocalDateTime timestamp;
    private Set<CharacterId> characters;
    private List<Event> events;
    
    public boolean isConsistentWith(Scene previous) {
        // 检查时间、空间一致性
    }
}
```

---

#### 4.1.3 Paragraph

```java
public class Paragraph {
    private ParagraphId paragraphId;
    private String text;
    private int wordCount;
    private int dialogueCount;
    private Set<String> containedWords;
    private LocalDateTime createdAt;
    
    public boolean violates(Constraint constraint) {
        // 检查是否违反约束
    }
}
```

---

#### 4.1.4 Constraint

```java
public class Constraint {
    private ConstraintId constraintId;
    private ConstraintType type;
    private ConstraintOperator operator;
    private Object value;
    private ConstraintPriority priority; // HARD / SOFT
    
    public boolean isSatisfiedBy(NarrativeSpec spec) {
        // 检查约束是否满足
    }
}
```

---

### 4.2 值对象（Value Object）

#### 4.2.1 Goal

```java
public record Goal(
    String description,
    double priority,
    GoalStatus status
) {
    public Goal {
        if (priority < 0 || priority > 1) {
            throw new IllegalArgumentException("Priority must be in [0, 1]");
        }
    }
}
```

---

#### 4.2.2 Belief

```java
public record Belief(
    String content,
    double confidence,
    BeliefSource source
) {
    public Belief {
        if (confidence < 0 || confidence > 1) {
            throw new IllegalArgumentException("Confidence must be in [0, 1]");
        }
    }
}
```

---

#### 4.2.3 EmotionState

```java
public record EmotionState(
    double anger,
    double fear,
    double hope,
    double sadness,
    double joy
) {
    public EmotionState {
        if (anger < 0 || anger > 1 || fear < 0 || fear > 1 || 
            hope < 0 || hope > 1 || sadness < 0 || sadness > 1 || 
            joy < 0 || joy > 1) {
            throw new IllegalArgumentException("Emotion values must be in [0, 1]");
        }
    }
    
    public String getDominantEmotion() {
        Map<String, Double> emotions = Map.of(
            "anger", anger,
            "fear", fear,
            "hope", hope,
            "sadness", sadness,
            "joy", joy
        );
        
        return emotions.entrySet().stream()
            .max(Map.Entry.comparingByValue())
            .map(Map.Entry::getKey)
            .orElse("neutral");
    }
}
```

---

#### 4.2.4 Decision

```java
public record Decision(
    CharacterId characterId,
    Action action,
    String reasoning,
    List<Alternative> alternatives,
    LocalDateTime timestamp
) {
    public Decision {
        if (action == null) {
            throw new IllegalArgumentException("Action cannot be null");
        }
    }
}
```

---

#### 4.2.5 Foreshadowing

```java
public record Foreshadowing(
    String id,
    String description,
    int plantedChapter,
    int resolvedChapter,
    ForeshadowingStatus status,
    List<String> suggestions
) {
    public Foreshadowing {
        if (plantedChapter >= resolvedChapter) {
            throw new IllegalArgumentException("Planted chapter must be before resolved chapter");
        }
    }
}
```

---

#### 4.2.6 ActionSequence

```java
public record ActionSequence(
    List<Action> actions,
    int totalSteps,
    Duration estimatedDuration,
    boolean isValid
) {
    public ActionSequence {
        if (actions == null || actions.isEmpty()) {
            throw new IllegalArgumentException("Actions cannot be null or empty");
        }
    }
}
```

---

#### 4.2.7 Dependency

```java
public record Dependency(
    DependencyType type,
    String reference,
    String description
) {
    public enum DependencyType {
        CHARACTER_STATE,
        EVENT,
        PARAGRAPH,
        CHARACTER_GOAL,
        FORESHADOWING
    }
}
```

---

#### 4.2.8 RollbackPoint

```java
public record RollbackPoint(
    ParagraphId targetParagraph,
    Set<ParagraphId> violatedParagraphs,
    Set<ParagraphId> dependentParagraphs
) {
    public int getTotalRegenerateCount() {
        return violatedParagraphs.size() + dependentParagraphs.size();
    }
}
```

---

#### 4.2.9 NarrativeSpec

```java
public record NarrativeSpec(
    IntRange chapterLengthRange,
    IntRange dialogueCountRange,
    Map<String, Boolean> foreshadowingResolutions,
    Set<String> forbiddenWords,
    boolean feasible
) {
    public record IntRange(int min, int max) {
        public IntRange {
            if (min > max) {
                throw new IllegalArgumentException("Min cannot be greater than max");
            }
        }
    }
}
```

---

## 5. 领域服务

### 5.1 CharacterDecisionService

**职责**: 角色决策服务

```java
public interface CharacterDecisionService {
    Decision decide(CharacterId characterId, Event event);
    List<Decision> batchDecide(List<CharacterId> characterIds, Event event);
    Decision resolveConflict(List<Decision> conflictingDecisions);
}
```

---

### 5.2 CounterfactualReasoningService

**职责**: 反事实推理服务

```java
public interface CounterfactualReasoningService {
    Plot generateCounterfactual(Plot original, EventModification modification);
    List<Foreshadowing> inferForeshadowings(Plot plot);
    boolean validateForeshadowing(Foreshadowing foreshadowing, Plot plot);
}
```

---

### 5.3 StoryPlanningService

**职责**: 故事规划服务

```java
public interface StoryPlanningService {
    StoryGraph buildGraph(List<Chapter> chapters);
    ActionSequence plan(Goal goal, StoryState state, Constraints constraints);
    ValidationResult validate(ActionSequence sequence);
}
```

---

### 5.4 NarrativeEditingService

**职责**: 叙事编辑服务

```java
public interface NarrativeEditingService {
    CausalGraph buildCausalGraph(Chapter chapter);
    RollbackPoint findMinimalRollback(Constraint violation, CausalGraph graph);
    Chapter applyPatch(Chapter chapter, RollbackPoint point, List<Paragraph> newParagraphs);
}
```

---

### 5.5 ConstraintSolvingService

**职责**: 约束求解服务

```java
public interface ConstraintSolvingService {
    NarrativeSpec solve(Set<Constraint> constraints);
    boolean isFeasible(Set<Constraint> constraints);
    List<Constraint> findConflicts(Set<Constraint> constraints);
}
```

---

## 6. 仓储（Repository）

### 6.1 CharacterMindRepository

```java
public interface CharacterMindRepository {
    CharacterMind findById(CharacterId characterId);
    List<CharacterMind> findByProjectId(NovelProjectId projectId);
    void save(CharacterMind mind);
    void delete(CharacterId characterId);
}
```

---

### 6.2 CounterfactualScenarioRepository

```java
public interface CounterfactualScenarioRepository {
    CounterfactualScenario findById(ScenarioId scenarioId);
    List<CounterfactualScenario> findByProjectId(NovelProjectId projectId);
    void save(CounterfactualScenario scenario);
}
```

---

### 6.3 StoryGraphRepository

```java
public interface StoryGraphRepository {
    StoryGraph findById(GraphId graphId);
    StoryGraph findByChapterId(ChapterId chapterId);
    void save(StoryGraph graph);
}
```

---

### 6.4 CausalGraphRepository

```java
public interface CausalGraphRepository {
    CausalGraph findById(GraphId graphId);
    CausalGraph findByChapterId(ChapterId chapterId);
    void save(CausalGraph graph);
}
```

---

### 6.5 NarrativeConstraintRepository

```java
public interface NarrativeConstraintRepository {
    NarrativeConstraint findById(ConstraintId constraintId);
    NarrativeConstraint findByChapterId(ChapterId chapterId);
    void save(NarrativeConstraint constraint);
}
```

---

## 7. 领域事件

### 7.1 事件定义

#### 7.1.1 CharacterDecisionMadeEvent

```java
public record CharacterDecisionMadeEvent(
    CharacterId characterId,
    Decision decision,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

#### 7.1.2 ForeshadowingInferredEvent

```java
public record ForeshadowingInferredEvent(
    NovelProjectId projectId,
    List<Foreshadowing> foreshadowings,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

#### 7.1.3 StoryPlanCreatedEvent

```java
public record StoryPlanCreatedEvent(
    GraphId graphId,
    ActionSequence sequence,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

#### 7.1.4 NarrativePatchedEvent

```java
public record NarrativePatchedEvent(
    ChapterId chapterId,
    RollbackPoint rollbackPoint,
    int regeneratedCount,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

#### 7.1.5 ConstraintSolvedEvent

```java
public record ConstraintSolvedEvent(
    ConstraintId constraintId,
    NarrativeSpec solution,
    boolean feasible,
    LocalDateTime occurredAt
) implements DomainEvent {}
```

---

## 8. 模块依赖关系

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 (Application)                  │
│  CharacterDecisionAppService, CounterfactualAppService  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    领域层 (Domain)                       │
│  CharacterMind, CounterfactualScenario, StoryGraph      │
│  CharacterDecisionService, CounterfactualReasoningService│
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    基础设施层 (Infrastructure)           │
│  CharacterMindRepository, CounterfactualScenarioRepo    │
│  StoryGraphRepository, CausalGraphRepository            │
└─────────────────────────────────────────────────────────┘
```

---

## 9. 设计原则遵循

### 9.1 DDD 原则

1. **聚合原则**: CharacterMind、CounterfactualScenario、StoryGraph 等作为聚合根
2. **值对象不可变**: 所有值对象使用 Java Record
3. **领域服务无状态**: CharacterDecisionService 等领域服务无状态
4. **仓储只负责持久化**: 仓储不包含业务逻辑

### 9.2 SOLID 原则

1. **单一职责**: 每个聚合职责单一
2. **开闭原则**: 通过接口抽象，支持扩展
3. **里氏替换**: 所有实现类可替换接口
4. **接口隔离**: 接口粒度适中
5. **依赖倒置**: 高层模块依赖抽象接口
