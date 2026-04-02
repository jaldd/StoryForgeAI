# 创新功能技术实现方案

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 创新功能架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent 编排层                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  AgentOrchestrator (增强版)                          │  │
│  │  ├─ IntentRouter                                     │  │
│  │  ├─ ToolExecutor                                     │  │
│  │  ├─ MemoryManager (增强)                             │  │
│  │  │   ├─ CharacterMind (创新点1)                      │  │
│  │  │   └─ CausalGraphStore (创新点4)                   │  │
│  │  ├─ StoryPlanner (创新点3)                           │  │
│  │  └─ ConstraintSolver (创新点5)                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────┬─────────────┬─────────────┬──────────────────┐
│   工具层    │   记忆层    │   模型层    │   创新工具层     │
│  ┌───────┐  │  ┌───────┐  │  ┌───────┐  │  ┌────────────┐  │
│  │Tools  │  │  │Memory │  │  │Model  │  │  │Counterfact │  │
│  │Registry│  │  │Manager│  │  │Gateway│  │  │Tool (创新2)│  │
│  └───────┘  │  └───────┘  │  └───────┘  │  └────────────┘  │
└─────────────┴─────────────┴─────────────┴──────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    基础设施层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Redis   │  │  Milvus  │  │PostgreSQL│  │  Neo4j   │   │
│  │  7.0+    │  │  2.3+    │  │   15+    │  │  (因果图) │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │OptaPlanner│  │  Llama 3 │  │  PDDL    │                 │
│  │(约束求解) │  │  (本地)  │  │ Planner  │                 │
│  └──────────┘  └──────────┘  └──────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 创新点 1：角色驱动情节生成

### 2.1 技术架构

```
用户请求续写
  ↓
加载角色状态（CharacterMind）
  ↓
事件触发 → 角色感知 → 情绪更新 → 目标评估 → 行动选择
  ↓
多角色决策 → 冲突解决 → 情节约束
  ↓
模型生成具体叙事
```

### 2.2 核心组件实现

#### 2.2.1 CharacterMind 模块

```java
package ai.storyforge.infrastructure.character;

import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

@Component
public class CharacterMindManager {
    
    private final CharacterMindRepository repository;
    private final CharacterDecisionEngine decisionEngine;
    private final ConflictResolver conflictResolver;
    
    public Mono<List<Decision>> processEvent(NovelProjectId projectId, Event event) {
        return repository.findByProjectId(projectId)
            .flatMap(minds -> {
                // 1. 每个角色独立决策
                List<Mono<Decision>> decisions = minds.stream()
                    .map(mind -> decisionEngine.decide(mind, event))
                    .collect(Collectors.toList());
                
                // 2. 合并决策
                return Mono.zip(decisions, results -> 
                    Arrays.stream(results)
                        .map(obj -> (Decision) obj)
                        .collect(Collectors.toList())
                );
            })
            .map(decisions -> {
                // 3. 解决冲突
                return conflictResolver.resolve(decisions);
            });
    }
}
```

---

#### 2.2.2 CharacterDecisionEngine

```java
package ai.storyforge.domain.service;

import org.springframework.stereotype.Service;

@Service
public class CharacterDecisionEngine {
    
    private final ChatLanguageModel chatModel;
    
    public Mono<Decision> decide(CharacterMind mind, Event event) {
        return Mono.fromCallable(() -> {
            // 1. 更新情绪
            mind.getState().updateEmotion(event);
            
            // 2. 评估目标
            Goal activeGoal = evaluateGoals(mind.getState(), event);
            
            // 3. 生成决策（使用模型）
            String prompt = buildDecisionPrompt(mind, event, activeGoal);
            String response = chatModel.generate(prompt);
            
            return parseDecision(response, mind.getCharacterId());
        });
    }
    
    private String buildDecisionPrompt(CharacterMind mind, Event event, Goal goal) {
        return """
            角色信息：
            - 姓名：%s
            - 当前目标：%s (优先级: %.2f)
            - 核心信念：%s
            - 当前情绪：%s (强度: %.2f)
            - 当前位置：%s
            
            事件：%s
            
            请根据角色的性格、目标、情绪，决定角色会如何行动。
            输出 JSON 格式：
            {
              "action": "具体行动",
              "target": "目标对象（如果有）",
              "intensity": 0.0-1.0,
              "reasoning": "决策理由"
            }
            """.formatted(
                mind.getState().getName(),
                goal.description(),
                goal.priority(),
                mind.getState().getBeliefs(),
                mind.getState().getEmotionState().getDominantEmotion(),
                mind.getState().getEmotionState().getDominantEmotionValue(),
                mind.getState().getCurrentLocation(),
                event.getDescription()
            );
    }
}
```

---

#### 2.2.3 ConflictResolver

```java
package ai.storyforge.domain.service;

import org.springframework.stereotype.Service;
import java.util.*;

@Service
public class ConflictResolver {
    
    public List<Decision> resolve(List<Decision> decisions) {
        // 1. 识别冲突
        Map<ConflictType, List<Decision>> conflicts = identifyConflicts(decisions);
        
        // 2. 解决每种冲突
        List<Decision> resolved = new ArrayList<>();
        for (Map.Entry<ConflictType, List<Decision>> entry : conflicts.entrySet()) {
            resolved.add(resolveConflict(entry.getKey(), entry.getValue()));
        }
        
        return resolved;
    }
    
    private Decision resolveConflict(ConflictType type, List<Decision> conflicting) {
        return switch (type) {
            case GOAL_CONFLICT -> resolveGoalConflict(conflicting);
            case RESOURCE_CONFLICT -> resolveResourceConflict(conflicting);
            case EMOTIONAL_CONFLICT -> resolveEmotionalConflict(conflicting);
        };
    }
    
    private Decision resolveGoalConflict(List<Decision> decisions) {
        // 按性格强度和情节重要性加权
        return decisions.stream()
            .max(Comparator.comparingDouble(this::calculateWeight))
            .orElseThrow();
    }
    
    private double calculateWeight(Decision decision) {
        // 性格强度 + 情节重要性 + 情绪强度
        return decision.characterStrength() * 0.4 +
               decision.plotImportance() * 0.4 +
               decision.emotionIntensity() * 0.2;
    }
}
```

---

### 2.3 数据存储

#### 2.3.1 PostgreSQL 表结构

```sql
CREATE TABLE character_minds (
    character_id VARCHAR(64) PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL REFERENCES novel_projects(project_id),
    name VARCHAR(128) NOT NULL,
    state JSONB NOT NULL,
    recent_decisions JSONB,
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_character_minds_project_id ON character_minds(project_id);
```

---

## 3. 创新点 2：反事实推理

### 3.1 技术架构

```
当前情节 → 反事实推理引擎 → 伏笔推导 → 伏笔清单
```

### 3.2 核心组件实现

#### 3.2.1 CounterfactualTool

```java
package ai.storyforge.infrastructure.tool;

import dev.langchain4j.agent.tool.Tool;
import org.springframework.stereotype.Component;

@Component
public class CounterfactualTool implements Tool<CounterfactualInput, ForeshadowingList> {
    
    private final ChatLanguageModel localModel; // 本地 Llama 3
    
    @Override
    public String name() {
        return "counterfactual_reasoning";
    }
    
    @Override
    public String description() {
        return "通过反事实推理推导必需伏笔";
    }
    
    @Override
    public ForeshadowingList execute(CounterfactualInput input, ToolContext context) {
        // 1. 生成反事实路径
        List<CounterfactualPath> paths = generateCounterfactualPaths(input.getPlot());
        
        // 2. 识别依赖关系
        List<Dependency> dependencies = identifyDependencies(input.getPlot(), paths);
        
        // 3. 推导伏笔
        List<Foreshadowing> foreshadowings = deduceForeshadowings(dependencies);
        
        return new ForeshadowingList(foreshadowings);
    }
    
    private List<CounterfactualPath> generateCounterfactualPaths(Plot plot) {
        String prompt = """
            给定当前情节：
            %s
            
            请生成 3 个反事实场景（如果某个关键事件没发生）：
            1. 移除某个事件
            2. 改变某个选择
            3. 改变某个角色行动
            
            输出 JSON 格式：
            [
              {
                "modification": "移除/改变的具体内容",
                "consequences": ["后果1", "后果2", ...]
              }
            ]
            """.formatted(formatPlot(plot));
        
        String response = localModel.generate(prompt);
        return parseCounterfactualPaths(response);
    }
}
```

---

### 3.3 本地模型部署

#### 3.3.1 Ollama 集成

```yaml
ollama:
  models:
    - name: llama3
      tag: 8b
      port: 11434
```

```java
@Configuration
public class OllamaConfig {
    
    @Bean
    public ChatLanguageModel localModel() {
        return OllamaChatModel.builder()
            .baseUrl("http://localhost:11434")
            .modelName("llama3:8b")
            .temperature(0.7)
            .build();
    }
}
```

---

## 4. 创新点 3：多模态故事板

### 4.1 技术架构

```
故事图构建 → 符号规划 → 路径验证 → 文本渲染
```

### 4.2 核心组件实现

#### 4.2.1 StoryPlanner

```java
package ai.storyforge.infrastructure.planning;

import org.springframework.stereotype.Component;
import java.util.*;

@Component
public class SymbolicStoryPlanner implements StoryPlanner {
    
    private final PddlPlanner pddlPlanner;
    
    @Override
    public ActionSequence plan(Goal goal, StoryState state, Constraints constraints) {
        // 1. 构建 PDDL 问题
        PddlProblem problem = buildPddlProblem(goal, state, constraints);
        
        // 2. 调用规划器
        PddlSolution solution = pddlPlanner.solve(problem);
        
        // 3. 转换为行动序列
        return convertToActionSequence(solution);
    }
    
    private PddlProblem buildPddlProblem(Goal goal, StoryState state, Constraints constraints) {
        return PddlProblem.builder()
            .domain("story-writing")
            .problemName("chapter-" + state.getCurrentChapter())
            .objects(defineObjects(state))
            .init(defineInitialState(state))
            .goal(defineGoal(goal))
            .constraints(defineConstraints(constraints))
            .build();
    }
}
```

---

#### 4.2.2 PddlPlanner

```java
package ai.storyforge.infrastructure.planning;

import org.springframework.stereotype.Component;
import java.io.*;

@Component
public class PddlPlanner {
    
    private final String plannerPath = "/opt/planner/fast-downward.py";
    
    public PddlSolution solve(PddlProblem problem) {
        try {
            // 1. 写入 PDDL 文件
            writePddlFiles(problem);
            
            // 2. 调用规划器
            ProcessBuilder pb = new ProcessBuilder(
                "python3", plannerPath,
                problem.getDomainFile(),
                problem.getProblemFile(),
                "--search", "astar(lmcut())"
            );
            
            Process process = pb.start();
            process.waitFor();
            
            // 3. 解析结果
            return parseSolution(process.getInputStream());
            
        } catch (Exception e) {
            throw new PlanningException("Planning failed", e);
        }
    }
}
```

---

### 4.3 一致性验证

```java
package ai.storyforge.domain.service;

import org.springframework.stereotype.Service;

@Service
public class ConsistencyValidator {
    
    public ValidationResult validate(ActionSequence sequence) {
        List<Violation> violations = new ArrayList<>();
        
        // 1. 空间一致性
        violations.addAll(checkSpatialConsistency(sequence));
        
        // 2. 时间一致性
        violations.addAll(checkTemporalConsistency(sequence));
        
        // 3. 因果一致性
        violations.addAll(checkCausalConsistency(sequence));
        
        return new ValidationResult(violations.isEmpty(), violations);
    }
    
    private List<Violation> checkSpatialConsistency(ActionSequence sequence) {
        List<Violation> violations = new ArrayList<>();
        
        for (int i = 0; i < sequence.getActions().size() - 1; i++) {
            Action current = sequence.getActions().get(i);
            Action next = sequence.getActions().get(i + 1);
            
            if (current.involvesCharacterMove() && 
                !isValidTransition(current, next)) {
                violations.add(new Violation(
                    ViolationType.SPATIAL_INCONSISTENCY,
                    "角色移动不合理：" + current.getDescription()
                ));
            }
        }
        
        return violations;
    }
}
```

---

## 5. 创新点 4：叙事韧性

### 5.1 技术架构

```
生成段落 → 构建因果依赖图 → 存储到 Neo4j
  ↓
用户修改约束 → 查询依赖图 → 计算最小回滚点 → 应用补丁
```

### 5.2 核心组件实现

#### 5.2.1 CausalGraphStore

```java
package ai.storyforge.infrastructure.graph;

import org.neo4j.driver.*;
import org.springframework.stereotype.Repository;

@Repository
public class CausalGraphRepository {
    
    private final Driver neo4jDriver;
    
    public void saveDependencies(Paragraph paragraph, List<Dependency> dependencies) {
        try (Session session = neo4jDriver.session()) {
            // 1. 创建段落节点
            session.run(
                "CREATE (p:Paragraph {id: $id, text: $text, wordCount: $wordCount})",
                Values.parameters(
                    "id", paragraph.getId(),
                    "text", paragraph.getText(),
                    "wordCount", paragraph.getWordCount()
                )
            );
            
            // 2. 创建依赖关系
            for (Dependency dep : dependencies) {
                session.run(
                    "MATCH (p:Paragraph {id: $paragraphId}) " +
                    "MATCH (t {id: $targetId}) " +
                    "CREATE (p)-[:DEPENDS_ON {type: $type, description: $desc}]->(t)",
                    Values.parameters(
                        "paragraphId", paragraph.getId(),
                        "targetId", dep.getReference(),
                        "type", dep.getType().name(),
                        "desc", dep.getDescription()
                    )
                );
            }
        }
    }
    
    public RollbackPoint findMinimalRollback(Constraint violation, ChapterId chapterId) {
        try (Session session = neo4jDriver.session()) {
            // 1. 找到违反约束的段落
            Result result = session.run(
                "MATCH (p:Paragraph)-[:DEPENDS_ON]->(d) " +
                "WHERE p.chapterId = $chapterId AND p.violates($constraint) " +
                "RETURN p.id as violatedId",
                Values.parameters(
                    "chapterId", chapterId.getValue(),
                    "constraint", violation.toJson()
                )
            );
            
            List<String> violatedIds = result.list(r -> r.get("violatedId").asString());
            
            // 2. 找到所有依赖段落
            Result dependentResult = session.run(
                "MATCH (p:Paragraph)-[:DEPENDS_ON*]->(v:Paragraph) " +
                "WHERE v.id IN $violatedIds " +
                "RETURN DISTINCT p.id as dependentId",
                Values.parameters("violatedIds", violatedIds)
            );
            
            List<String> dependentIds = dependentResult.list(r -> r.get("dependentId").asString());
            
            // 3. 找到最早段落
            Result earliestResult = session.run(
                "MATCH (p:Paragraph) " +
                "WHERE p.id IN $allIds " +
                "RETURN p.id ORDER BY p.createdAt ASC LIMIT 1",
                Values.parameters("allIds", 
                    Stream.concat(violatedIds.stream(), dependentIds.stream())
                        .collect(Collectors.toList()))
            );
            
            String earliestId = earliestResult.single().get("p.id").asString();
            
            return new RollbackPoint(
                new ParagraphId(earliestId),
                violatedIds.stream().map(ParagraphId::new).collect(Collectors.toSet()),
                dependentIds.stream().map(ParagraphId::new).collect(Collectors.toSet())
            );
        }
    }
}
```

---

### 5.3 Neo4j 配置

```yaml
spring:
  neo4j:
    uri: bolt://localhost:7687
    authentication:
      username: neo4j
      password: ${NEO4J_PASSWORD}
```

```java
@Configuration
public class Neo4jConfig {
    
    @Bean
    public Driver neo4jDriver() {
        return GraphDatabase.driver(
            "bolt://localhost:7687",
            AuthTokens.basic("neo4j", "password")
        );
    }
}
```

---

## 6. 创新点 5：元叙事约束求解

### 6.1 技术架构

```
用户约束 → 约束建模 → OptaPlanner 求解 → 可行解空间 → 模型生成
```

### 6.2 核心组件实现

#### 6.2.1 ConstraintSolver

```java
package ai.storyforge.infrastructure.constraint;

import org.optaplanner.core.api.solver.SolverJob;
import org.optaplanner.core.api.solver.SolverManager;
import org.springframework.stereotype.Service;

@Service
public class NarrativeConstraintSolver {
    
    private final SolverManager<NarrativeSpec, Long> solverManager;
    
    public NarrativeSpec solve(Set<Constraint> constraints) {
        // 1. 创建规划问题
        NarrativeSpec problem = new NarrativeSpec();
        problem.setConstraints(constraints);
        
        // 2. 求解
        SolverJob<NarrativeSpec, Long> solverJob = solverManager.solve(1L, problem);
        
        // 3. 获取解
        NarrativeSpec solution = solverJob.getFinalBestSolution();
        
        return solution;
    }
}
```

---

#### 6.2.2 NarrativeSpec（规划实体）

```java
package ai.storyforge.domain.model;

import org.optaplanner.core.api.domain.entity.PlanningEntity;
import org.optaplanner.core.api.domain.variable.PlanningVariable;
import org.optaplanner.core.api.domain.constraint.ConstraintWeight;
import org.optaplanner.core.api.score.buildin.hardsoft.HardSoftScore;

@PlanningEntity
public class NarrativeSpec {
    
    private Set<Constraint> constraints;
    
    @PlanningVariable(valueRangeProviderRefs = "chapterLengthRange")
    private IntRange chapterLengthRange;
    
    @PlanningVariable(valueRangeProviderRefs = "dialogueCountRange")
    private IntRange dialogueCountRange;
    
    @PlanningVariable(valueRangeProviderRefs = "foreshadowingResolutions")
    private Map<String, Boolean> foreshadowingResolutions;
    
    @ConstraintWeight("章节长度约束")
    private HardSoftScore chapterLengthWeight = HardSoftScore.ofHard(10);
    
    @ConstraintWeight("对话次数约束")
    private HardSoftScore dialogueCountWeight = HardSoftScore.ofHard(8);
    
    @ConstraintWeight("伏笔回收约束")
    private HardSoftScore foreshadowingWeight = HardSoftScore.ofHard(9);
    
    // Getters and setters...
}
```

---

#### 6.2.3 约束定义

```java
package ai.storyforge.infrastructure.constraint;

import org.optaplanner.core.api.score.stream.Constraint;
import org.optaplanner.core.api.score.stream.ConstraintFactory;
import org.optaplanner.core.api.score.stream.ConstraintProvider;

public class NarrativeConstraintProvider implements ConstraintProvider {
    
    @Override
    public Constraint[] defineConstraints(ConstraintFactory factory) {
        return new Constraint[] {
            chapterLengthConstraint(factory),
            dialogueCountConstraint(factory),
            foreshadowingConstraint(factory)
        };
    }
    
    private Constraint chapterLengthConstraint(ConstraintFactory factory) {
        return factory.from(NarrativeSpec.class)
            .filter(spec -> !spec.satisfiesChapterLength())
            .penalize("章节长度约束", HardSoftScore.ONE_HARD);
    }
    
    private Constraint dialogueCountConstraint(ConstraintFactory factory) {
        return factory.from(NarrativeSpec.class)
            .filter(spec -> !spec.satisfiesDialogueCount())
            .penalize("对话次数约束", HardSoftScore.ONE_HARD);
    }
    
    private Constraint foreshadowingConstraint(ConstraintFactory factory) {
        return factory.from(NarrativeSpec.class)
            .filter(spec -> !spec.satisfiesForeshadowing())
            .penalize("伏笔回收约束", HardSoftScore.ONE_HARD);
    }
}
```

---

### 6.3 OptaPlanner 配置

```xml
<solver>
  <solutionClass>ai.storyforge.domain.model.NarrativeSpec</solutionClass>
  <entityClass>ai.storyforge.domain.model.NarrativeSpec</entityClass>
  
  <scoreDirectorFactory>
    <constraintProviderClass>ai.storyforge.infrastructure.constraint.NarrativeConstraintProvider</constraintProviderClass>
  </scoreDirectorFactory>
  
  <termination>
    <secondsSpentLimit>30</secondsSpentLimit>
  </termination>
</solver>
```

---

## 7. 部署方案

### 7.1 Docker Compose（增强版）

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - SPRING_PROFILES_ACTIVE=prod
      - ZHIPU_API_KEY=${ZHIPU_API_KEY}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
    depends_on:
      - redis
      - milvus
      - postgres
      - neo4j
      - ollama
    networks:
      - storyforge-network
  
  neo4j:
    image: neo4j:5.15
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
    volumes:
      - neo4j-data:/data
    networks:
      - storyforge-network
  
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama
    networks:
      - storyforge-network

volumes:
  neo4j-data:
  ollama-data:
```

---

## 8. 性能优化

### 8.1 角色决策优化

- 使用缓存存储角色状态
- 并行处理多角色决策
- 使用本地模型减少延迟

### 8.2 因果图查询优化

- Neo4j 索引优化
- 查询结果缓存
- 图遍历优化

### 8.3 约束求解优化

- OptaPlanner 并行求解
- 约束传播优化
- 提前终止策略

---

## 9. 监控与日志

### 9.1 创新功能指标

- 角色决策延迟
- 反事实推理耗时
- 规划器成功率
- 因果图查询延迟
- 约束求解耗时

### 9.2 日志规范

```
[traceId=abc123] Character decision: character=张伟, action=confront, latency=800ms
[traceId=abc123] Counterfactual reasoning: paths=3, foreshadowings=5, latency=3200ms
[traceId=abc123] Story planning: actions=8, valid=true, latency=2100ms
[traceId=abc123] Causal graph query: rollbackPoint=p5, latency=450ms
[traceId=abc123] Constraint solving: feasible=true, latency=4800ms
```
