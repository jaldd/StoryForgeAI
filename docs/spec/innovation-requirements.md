# 创新功能需求规格

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 创新功能模块总览

```
StoryForgeAI 创新功能
├── 角色驱动情节生成模块
│   ├── 角色状态管理
│   ├── 角色决策引擎
│   └── 多角色冲突解决
├── 反事实推理模块
│   ├── 反事实路径生成
│   ├── 伏笔推导引擎
│   └── 伏笔验证系统
├── 多模态故事板模块
│   ├── 故事图构建
│   ├── 符号规划器
│   └── 路径验证
├── 叙事韧性模块
│   ├── 因果依赖图存储
│   ├── 最小回滚计算
│   └── 补丁应用系统
└── 元叙事约束求解模块
    ├── 约束建模
    ├── 约束求解器
    └── 可行解空间输出
```

---

## 2. 角色驱动情节生成模块

### 2.1 功能描述

让每个主要角色拥有独立的"微型 Agent"，通过角色决策涌现情节，而非上帝视角生成。

### 2.2 功能规格

#### 2.2.1 角色状态管理

**角色状态结构**:
```json
{
  "characterId": "char_001",
  "name": "张伟",
  "goal": {
    "primary": "复仇",
    "secondary": ["保护家人", "寻找真相"],
    "priority": 0.8
  },
  "beliefs": {
    "core": ["正义必胜", "家人至上"],
    "current": ["李明是叛徒", "组织在隐瞒真相"]
  },
  "emotion": {
    "anger": 0.8,
    "fear": 0.3,
    "hope": 0.5,
    "dominant": "anger"
  },
  "memory": [
    {
      "event": "李明背叛",
      "interpretation": "李明为了利益出卖了我",
      "emotionalImpact": 0.9
    }
  ],
  "location": "北京",
  "relationships": {
    "李明": {"type": "enemy", "intensity": 0.9},
    "王芳": {"type": "ally", "intensity": 0.7}
  }
}
```

**状态更新规则**:
- 情绪值随事件影响变化（-0.1 ~ +0.1 per event）
- 目标优先级随情节发展调整
- 信念系统根据新信息更新

---

#### 2.2.2 角色决策引擎

**决策流程**:
```
事件触发 → 角色感知 → 情绪更新 → 目标评估 → 行动选择 → 执行
```

**决策输入**:
```json
{
  "characterId": "char_001",
  "event": {
    "type": "character_appearance",
    "character": "李明",
    "location": "咖啡馆",
    "context": "张伟正在喝咖啡，李明突然出现"
  }
}
```

**决策输出**:
```json
{
  "characterId": "char_001",
  "decision": {
    "action": "confront",
    "target": "李明",
    "intensity": 0.8,
    "reasoning": "愤怒值高（0.8），目标是复仇，李明是敌人"
  },
  "expectedOutcome": "冲突升级，可能引发打斗",
  "alternatives": [
    {"action": "ignore", "probability": 0.1, "reason": "避免暴露"},
    {"action": "flee", "probability": 0.1, "reason": "恐惧值低（0.3）"}
  ]
}
```

**决策算法**:
```java
class CharacterDecisionEngine {
    Decision decide(CharacterState state, Event event) {
        // 1. 情绪更新
        state.updateEmotion(event);
        
        // 2. 目标评估
        Goal activeGoal = state.evaluateGoals(event);
        
        // 3. 行动选择（基于性格、目标、情绪）
        List<Action> possibleActions = generateActions(state, event);
        Action selectedAction = selectAction(possibleActions, state);
        
        return new Decision(selectedAction, state);
    }
}
```

---

#### 2.2.3 多角色冲突解决

**冲突类型**:
- **目标冲突**: 多个角色目标互相矛盾
- **资源冲突**: 多个角色争夺同一资源
- **情感冲突**: 角色间情感关系冲突

**冲突解决策略**:
```java
class ConflictResolver {
    Decision resolveConflict(List<Decision> decisions) {
        // 1. 识别冲突类型
        ConflictType type = identifyConflict(decisions);
        
        // 2. 计算角色权重（性格强度、情节重要性）
        Map<CharacterId, Double> weights = calculateWeights(decisions);
        
        // 3. 选择主导角色
        CharacterId dominant = selectDominant(weights);
        
        // 4. 折中或妥协
        return compromise(decisions, dominant);
    }
}
```

**权重计算**:
- 性格强度（果断性、固执度）
- 情节重要性（主角 > 配角）
- 情绪强度（愤怒值高 > 愤怒值低）

---

### 2.3 验收标准

- [ ] 能管理至少 5 个角色的状态
- [ ] 角色决策符合性格逻辑（人工验证）
- [ ] 多角色冲突解决合理（人工验证）
- [ ] 情节涌现自然（人工验证）

---

## 3. 反事实推理模块

### 3.1 功能描述

通过反事实推理系统化设计伏笔，从"灵光一现"变为逻辑必需性推导。

### 3.2 功能规格

#### 3.2.1 反事实路径生成

**输入**:
```json
{
  "currentPlot": {
    "events": [
      {"id": "e1", "description": "主角捡到一把旧钥匙"},
      {"id": "e2", "description": "主角发现密室"},
      {"id": "e3", "description": "主角获得关键线索"}
    ]
  },
  "targetEvent": "e1",
  "modification": "remove"
}
```

**输出**:
```json
{
  "counterfactualPlot": {
    "events": [
      {"id": "e2", "description": "主角发现密室", "status": "impossible"},
      {"id": "e3", "description": "主角获得关键线索", "status": "impossible"}
    ]
  },
  "consequences": [
    "无法打开密室",
    "无法获得关键线索",
    "情节断裂"
  ]
}
```

---

#### 3.2.2 伏笔推导引擎

**推导流程**:
```
当前情节 → 反事实推理 → 识别依赖关系 → 推导必需伏笔 → 生成伏笔清单
```

**伏笔清单**:
```json
{
  "requiredForeshadowings": [
    {
      "id": "f1",
      "description": "钥匙与密室有关",
      "plantedIn": "第1-2章",
      "resolvedIn": "第3章",
      "priority": "high",
      "suggestions": [
        "墙上挂画暗示密室位置",
        "老人提到'那把钥匙能打开重要的门'",
        "钥匙上的符号与密室门上的符号一致"
      ]
    }
  ]
}
```

---

#### 3.2.3 伏笔验证系统

**验证维度**:
- **埋设验证**: 伏笔是否在前文埋下
- **回收验证**: 伏笔是否在后文回收
- **一致性验证**: 伏笔是否与情节一致

**验证报告**:
```json
{
  "foreshadowingId": "f1",
  "status": "incomplete",
  "issues": [
    {
      "type": "not_planted",
      "description": "伏笔未在前文埋下",
      "suggestion": "在第1章增加暗示"
    }
  ]
}
```

---

### 3.3 验收标准

- [ ] 能生成反事实路径
- [ ] 能推导必需伏笔
- [ ] 伏笔建议具有可操作性
- [ ] 伏笔验证准确率 > 70%

---

## 4. 多模态故事板模块

### 4.1 功能描述

用图结构表示故事的空间、时间、因果关系，生成前先规划，再渲染成文字。

### 4.2 功能规格

#### 4.2.1 故事图构建

**图结构**:
```
节点：Scene（场景）
  - location: 地点
  - timestamp: 时间戳
  - characters: 在场角色
  - events: 发生的事件

边：Transition（转换）
  - character_move: 角色移动
  - event_causality: 事件因果
  - info_flow: 信息传递
```

**示例**:
```json
{
  "nodes": [
    {
      "id": "scene_1",
      "location": "北京·咖啡馆",
      "timestamp": "2026-04-01T10:00:00Z",
      "characters": ["张伟", "李明"],
      "events": ["张伟与李明对话"]
    },
    {
      "id": "scene_2",
      "location": "北京·张伟家",
      "timestamp": "2026-04-01T12:00:00Z",
      "characters": ["张伟"],
      "events": ["张伟思考对策"]
    }
  ],
  "edges": [
    {
      "from": "scene_1",
      "to": "scene_2",
      "type": "character_move",
      "character": "张伟",
      "duration": "2 hours"
    }
  ]
}
```

---

#### 4.2.2 符号规划器

**PDDL 定义**:

**Domain**:
```lisp
(define (domain story-writing)
  (:predicates (at ?character ?location)
               (has ?character ?item)
               (knows ?character ?information))
  
  (:action move
    :parameters (?character ?from ?to)
    :precondition (at ?character ?from)
    :effect (and (at ?character ?to)
                 (not (at ?character ?from))))
  
  (:action acquire
    :parameters (?character ?item)
    :precondition (and (at ?character ?location)
                       (at-item ?item ?location))
    :effect (has ?character ?item))
)
```

**Problem**:
```lisp
(define (problem chapter-3)
  (:domain story-writing)
  (:objects 张伟 李明 北京 上海 钥匙)
  (:init (at 张伟 北京)
         (at 李明 上海)
         (at-item 钥匙 北京))
  (:goal (and (has 张伟 钥匙)
              (at 张伟 上海)))
)
```

**规划输出**:
```
1. 张伟在北京找到钥匙
2. 张伟从北京移动到上海
```

---

#### 4.2.3 路径验证

**验证规则**:
- **空间一致性**: 角色不能瞬移（移动时间合理）
- **时间一致性**: 事件顺序符合时间线
- **因果一致性**: 事件因果链完整

**验证报告**:
```json
{
  "valid": false,
  "violations": [
    {
      "type": "spatial_inconsistency",
      "description": "张伟在第3章结尾在北京，第4章开头突然在上海",
      "suggestion": "增加移动场景或说明交通方式"
    }
  ]
}
```

---

### 4.3 验收标准

- [ ] 能构建故事图
- [ ] 符号规划器能生成行动序列
- [ ] 能检测空间/时间不一致性
- [ ] 规划结果可解释

---

## 5. 叙事韧性模块

### 5.1 功能描述

支持叙事回滚与补丁，用户修改约束时只重新生成违反约束的部分。

### 5.2 功能规格

#### 5.2.1 因果依赖图存储

**依赖图结构**:
```json
{
  "paragraphs": [
    {
      "id": "p1",
      "text": "张伟愤怒地盯着李明...",
      "dependencies": [
        {"type": "character_state", "ref": "张伟.anger", "value": 0.8},
        {"type": "event", "ref": "e1", "description": "李明背叛"}
      ]
    },
    {
      "id": "p2",
      "text": "张伟决定复仇...",
      "dependencies": [
        {"type": "paragraph", "ref": "p1"},
        {"type": "character_goal", "ref": "张伟.goal", "value": "复仇"}
      ]
    }
  ]
}
```

---

#### 5.2.2 最小回滚计算

**回滚算法**:
```java
class RollbackCalculator {
    RollbackPoint findMinimalRollback(Constraint violation, DependencyGraph graph) {
        // 1. 找到违反约束的段落
        List<Paragraph> violated = findViolatedParagraphs(violation);
        
        // 2. 找到所有依赖这些段落的后续段落
        Set<Paragraph> dependent = findAllDependent(violated, graph);
        
        // 3. 计算最小回滚点
        Paragraph earliest = findEarliest(violated, dependent);
        
        return new RollbackPoint(earliest, violated, dependent);
    }
}
```

**示例**:
```
用户约束: "张三不能黑化"
违反段落: p5（张三黑化）
依赖段落: p6, p7, p8
最小回滚点: p5
重新生成: p5, p6, p7, p8
保留: p1, p2, p3, p4
```

---

#### 5.2.3 补丁应用系统

**补丁请求**:
```json
{
  "constraint": {
    "type": "character_trait",
    "character": "张三",
    "trait": "善良",
    "operator": "must_have"
  },
  "fromChapter": 3
}
```

**补丁响应**:
```json
{
  "rollbackPoint": "p5",
  "regenerateCount": 4,
  "preserveCount": 4,
  "newContent": [
    {"id": "p5_new", "text": "张三犹豫了，最终还是选择了原谅..."},
    {"id": "p6_new", "text": "..."},
    {"id": "p7_new", "text": "..."},
    {"id": "p8_new", "text": "..."}
  ]
}
```

---

### 5.3 验收标准

- [ ] 能构建因果依赖图
- [ ] 能计算最小回滚点
- [ ] 补丁应用后约束满足
- [ ] 保留内容不丢失

---

## 6. 元叙事约束求解模块

### 6.1 功能描述

使用约束求解器处理复杂叙事约束，自动输出可行解空间。

### 6.2 功能规格

#### 6.2.1 约束建模

**约束类型**:
```java
enum ConstraintType {
    CHAPTER_LENGTH,      // 章节长度
    DIALOGUE_COUNT,      // 对话次数
    FORESHADOWING_RESOLVE, // 伏笔回收
    FORBIDDEN_WORDS,     // 禁止词
    CHARACTER_APPEARANCE, // 角色出场
    EMOTION_ARC          // 情感弧光
}
```

**约束示例**:
```json
{
  "constraints": [
    {
      "type": "CHAPTER_LENGTH",
      "operator": "<=",
      "value": 3000,
      "unit": "words"
    },
    {
      "type": "DIALOGUE_COUNT",
      "operator": ">=",
      "value": 3
    },
    {
      "type": "FORESHADOWING_RESOLVE",
      "foreshadowingId": "f1",
      "operator": "must_resolve"
    },
    {
      "type": "FORBIDDEN_WORDS",
      "words": ["突然", "忽然", "猛然"],
      "operator": "not_contains"
    }
  ]
}
```

---

#### 6.2.2 约束求解器

**OptaPlanner 配置**:
```java
@PlanningSolution
class NarrativeSpec {
    @PlanningEntityCollectionProperty
    List<ParagraphSpec> paragraphs;
    
    @ProblemFactCollectionProperty
    List<Constraint> constraints;
    
    @PlanningScore
    HardSoftScore score;
}

@PlanningEntity
class ParagraphSpec {
    @PlanningVariable
    int length;
    
    @PlanningVariable
    int dialogueCount;
    
    @PlanningVariable
    boolean resolvesForeshadowing;
}
```

**求解过程**:
```
初始化 → 约束传播 → 变量赋值 → 冲突检测 → 回溯 → 最优解
```

---

#### 6.2.3 可行解空间输出

**输出**:
```json
{
  "feasible": true,
  "solution": {
    "chapterLengthRange": {"min": 2500, "max": 3000},
    "dialogueCount": {"min": 3, "max": 5},
    "foreshadowingResolution": {
      "f1": {"required": true, "minLength": 200, "maxLength": 500}
    },
    "forbiddenWords": ["突然", "忽然", "猛然"]
  },
  "constraints": {
    "satisfied": ["CHAPTER_LENGTH", "DIALOGUE_COUNT", "FORBIDDEN_WORDS"],
    "conflict": []
  }
}
```

---

### 6.3 验收标准

- [ ] 能建模叙事约束
- [ ] 约束求解器能找到可行解
- [ ] 能检测约束冲突
- [ ] 可行解空间合理

---

## 7. 非功能性需求

### 7.1 性能需求

| 模块 | 性能目标 | 理由 |
|------|---------|------|
| 角色决策 | < 1秒 | 单个角色决策不应成为瓶颈 |
| 反事实推理 | < 5秒 | 推理过程可能复杂 |
| 符号规划 | < 3秒 | PDDL 规划应快速 |
| 因果图查询 | < 500ms | 图数据库查询应快速 |
| 约束求解 | < 5秒 | OptaPlanner 应快速收敛 |

### 7.2 可扩展性需求

- 支持新增约束类型
- 支持新增角色属性
- 支持新增规划策略

---

## 8. 验收标准总览

### 8.1 功能验收

- [ ] 角色驱动情节生成模块正常工作
- [ ] 反事实推理模块能推导伏笔
- [ ] 多模态故事板能保证一致性
- [ ] 叙事韧性模块支持回滚
- [ ] 约束求解器能处理复杂约束

### 8.2 性能验收

- [ ] 所有模块满足性能目标
- [ ] 无明显性能瓶颈

### 8.3 创新性验收

- [ ] 至少 3 个创新点实现并验证
- [ ] 创新点具有实际价值
