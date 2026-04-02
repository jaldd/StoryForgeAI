# 技术实现方案

**项目**: StoryForgeAI  
**版本**: 1.0  
**日期**: 2026-04-02

---

## 1. 技术架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      用户接口层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   CLI 界面   │  │   Web 界面   │  │   IDE 插件   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                      API 网关层                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Spring Boot 3.2+                                    │  │
│  │  - REST Controller                                   │  │
│  │  - SSE Endpoint                                      │  │
│  │  - Exception Handler                                 │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Agent 编排层                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  LangChain4j 0.35+                                   │  │
│  │  ┌────────────────────────────────────────────────┐ │  │
│  │  │  AgentOrchestrator                             │ │  │
│  │  │  ├─ IntentRouter                               │ │  │
│  │  │  ├─ ToolExecutor                               │ │  │
│  │  │  └─ MemoryManager                              │ │  │
│  │  └────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────┬─────────────┬─────────────┬──────────────────┐
│   工具层    │   记忆层    │   模型层    │   MCP 服务层     │
│  ┌───────┐  │  ┌───────┐  │  ┌───────┐  │  ┌────────────┐  │
│  │Tools  │  │  │Memory │  │  │Model  │  │  │MCP Server  │  │
│  │Registry│  │  │Manager│  │  │Gateway│  │  │JSON-RPC    │  │
│  └───────┘  │  └───────┘  │  └───────┘  │  └────────────┘  │
└─────────────┴─────────────┴─────────────┴──────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    基础设施层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Redis   │  │  Milvus  │  │PostgreSQL│  │  智谱AI  │   │
│  │  7.0+    │  │  2.3+    │  │   15+    │  │   API    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈详细说明

| 层次 | 技术 | 版本 | 用途 | 理由 |
|------|------|------|------|------|
| **语言** | Java | 21 | 核心开发语言 | 虚拟线程、Record、Pattern Matching |
| **框架** | Spring Boot | 3.2+ | Web 框架 | 企业级生态、依赖注入、配置管理 |
| **Agent 框架** | LangChain4j | 0.35+ | Agent 编排 | Agent 抽象成熟、Java 生态友好 |
| **向量数据库** | Milvus | 2.3+ | 长期记忆存储 | 本地可控、性能好、支持大规模数据 |
| **缓存** | Redis | 7.0+ | 短期记忆存储 | 高性能、支持 List 数据结构 |
| **关系数据库** | PostgreSQL | 15+ | 工作记忆、摘要存储 | JSONB 支持好、成熟稳定 |
| **模型服务** | 智谱 AI | - | GLM-4-Flash | 低成本、OpenAI 兼容 |
| **构建工具** | Maven | 3.9+ | 项目构建 | 主流构建工具、依赖管理 |
| **测试框架** | JUnit 5 | 5.10+ | 单元测试 | Java 标准测试框架 |
| **日志框架** | SLF4J + Logback | - | 日志记录 | 主流日志方案 |
| **监控** | Micrometer | - | 指标收集 | Spring Boot 集成好 |

---

## 2. 项目结构

### 2.1 Maven 模块划分

```
storyforge-ai/
├── pom.xml (父 POM)
├── storyforge-domain/ (领域层)
│   ├── src/main/java/ai/storyforge/domain/
│   │   ├── model/ (实体、值对象)
│   │   ├── service/ (领域服务)
│   │   ├── repository/ (仓储接口)
│   │   └── event/ (领域事件)
│   └── pom.xml
├── storyforge-application/ (应用层)
│   ├── src/main/java/ai/storyforge/application/
│   │   ├── service/ (应用服务)
│   │   ├── dto/ (数据传输对象)
│   │   └── assembler/ (对象组装器)
│   └── pom.xml
├── storyforge-infrastructure/ (基础设施层)
│   ├── src/main/java/ai/storyforge/infrastructure/
│   │   ├── persistence/ (持久化实现)
│   │   ├── memory/ (记忆系统实现)
│   │   ├── model/ (模型网关实现)
│   │   └── mcp/ (MCP 服务实现)
│   └── pom.xml
├── storyforge-api/ (API 层)
│   ├── src/main/java/ai/storyforge/api/
│   │   ├── controller/ (REST 控制器)
│   │   ├── config/ (配置类)
│   │   └── exception/ (异常处理)
│   └── pom.xml
└── storyforge-cli/ (CLI 入口)
    ├── src/main/java/ai/storyforge/cli/
    └── pom.xml
```

### 2.2 依赖管理

**父 POM**:
```xml
<project>
    <modelVersion>4.0.0</modelVersion>
    <groupId>ai.storyforge</groupId>
    <artifactId>storyforge-ai</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <packaging>pom</packaging>
    
    <modules>
        <module>storyforge-domain</module>
        <module>storyforge-application</module>
        <module>storyforge-infrastructure</module>
        <module>storyforge-api</module>
        <module>storyforge-cli</module>
    </modules>
    
    <properties>
        <java.version>21</java.version>
        <spring-boot.version>3.2.0</spring-boot.version>
        <langchain4j.version>0.35.0</langchain4j.version>
        <milvus-sdk.version>2.3.4</milvus-sdk.version>
    </properties>
    
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-dependencies</artifactId>
                <version>${spring-boot.version}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
            
            <dependency>
                <groupId>dev.langchain4j</groupId>
                <artifactId>langchain4j</artifactId>
                <version>${langchain4j.version}</version>
            </dependency>
            
            <dependency>
                <groupId>io.milvus</groupId>
                <artifactId>milvus-sdk-java</artifactId>
                <version>${milvus-sdk.version}</version>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
```

---

## 3. 核心模块实现方案

### 3.1 Agent 编排模块

#### 3.1.1 AgentOrchestrator

**职责**: 协调整个请求处理流程

**实现**:
```java
package ai.storyforge.application.service;

import dev.langchain4j.agent.tool.Tool;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.input.Prompt;
import dev.langchain4j.model.input.PromptTemplate;
import reactor.core.publisher.Flux;

public class AgentOrchestrator {
    
    private final IntentRouter intentRouter;
    private final ContextBuilder contextBuilder;
    private final ToolExecutor toolExecutor;
    private final ChatLanguageModel chatModel;
    private final MemoryManager memoryManager;
    
    public Flux<TokenChunk> handleUserRequest(UserRequest request) {
        return Flux.create(emitter -> {
            try {
                // 1. 意图识别
                IntentType intent = intentRouter.detect(request.text());
                emitter.next(TokenChunk.info("Intent detected: " + intent));
                
                // 2. 上下文构建
                ContextBundle context = contextBuilder.build(
                    request.projectId(), 
                    request.text(), 
                    12000
                );
                
                // 3. 工具调用（可选）
                List<ToolResult> toolResults = executeToolsIfNeeded(intent, context);
                
                // 4. 构建 Prompt
                Prompt prompt = buildPrompt(request, context, toolResults);
                
                // 5. 流式生成
                chatModel.generate(prompt.toUserMessage())
                    .handlers()
                    .onPartialResponse(token -> emitter.next(TokenChunk.token(token)))
                    .onCompleteResponse(response -> {
                        emitter.next(TokenChunk.done());
                        emitter.complete();
                        
                        // 6. 持久化
                        persistTurn(request, context, response);
                    })
                    .onError(emitter::error)
                    .execute();
                    
            } catch (Exception e) {
                emitter.error(e);
            }
        });
    }
    
    private List<ToolResult> executeToolsIfNeeded(IntentType intent, ContextBundle context) {
        return switch (intent) {
            case ANALYZE -> List.of(
                toolExecutor.execute("character_arc_planner", context),
                toolExecutor.execute("plot_gap_detector", context)
            );
            case POLISH -> List.of(
                toolExecutor.execute("style_transfer", context)
            );
            default -> List.of();
        };
    }
}
```

---

### 3.2 记忆管理模块

#### 3.2.1 短期记忆实现

**存储**: Redis List

**实现**:
```java
package ai.storyforge.infrastructure.memory;

import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ShortTermMemoryRepositoryImpl implements ShortTermMemoryRepository {
    
    private final RedisTemplate<String, Object> redisTemplate;
    
    @Override
    public void append(NovelProjectId projectId, Turn turn) {
        String key = "storyforge:shortterm:" + projectId.value();
        redisTemplate.opsForList().rightPush(key, turn);
        
        // 滑动窗口：保留最近 10 轮
        redisTemplate.opsForList().trim(key, -10, -1);
    }
    
    @Override
    public List<Turn> getWindow(NovelProjectId projectId, int windowSize) {
        String key = "storyforge:shortterm:" + projectId.value();
        List<Object> objects = redisTemplate.opsForList().range(key, -windowSize, -1);
        
        return objects.stream()
            .map(obj -> (Turn) obj)
            .collect(Collectors.toList());
    }
    
    @Override
    public void clear(NovelProjectId projectId) {
        String key = "storyforge:shortterm:" + projectId.value();
        redisTemplate.delete(key);
    }
}
```

---

#### 3.2.2 长期记忆实现

**存储**: Milvus

**实现**:
```java
package ai.storyforge.infrastructure.memory;

import io.milvus.client.MilvusServiceClient;
import io.milvus.param.collection.LoadCollectionParam;
import io.milvus.param.dml.InsertParam;
import io.milvus.param.dml.SearchParam;
import io.milvus.response.SearchResultsWrapper;
import org.springframework.stereotype.Repository;

@Repository
public class LongTermMemoryRepositoryImpl implements LongTermMemoryRepository {
    
    private final MilvusServiceClient milvusClient;
    private final EmbeddingClient embeddingClient;
    private final String collectionName = "novel_chunks";
    
    @Override
    public void index(NovelProjectId projectId, List<MemoryChunk> chunks) {
        List<InsertParam.Field> fields = new ArrayList<>();
        
        List<String> ids = new ArrayList<>();
        List<String> texts = new ArrayList<>();
        List<List<Float>> embeddings = new ArrayList<>();
        List<String> metadatas = new ArrayList<>();
        
        for (MemoryChunk chunk : chunks) {
            ids.add(chunk.chunkId());
            texts.add(chunk.text());
            embeddings.add(toFloatList(chunk.embedding()));
            metadatas.add(toJson(chunk.metadata()));
        }
        
        fields.add(new InsertParam.Field("id", ids));
        fields.add(new InsertParam.Field("text", texts));
        fields.add(new InsertParam.Field("embedding", embeddings));
        fields.add(new InsertParam.Field("metadata", metadatas));
        
        InsertParam insertParam = InsertParam.newBuilder()
            .withCollectionName(collectionName)
            .withFields(fields)
            .build();
        
        milvusClient.insert(insertParam);
    }
    
    @Override
    public List<MemoryChunk> retrieve(NovelProjectId projectId, String query, int topK) {
        // 1. 生成查询向量
        float[] queryEmbedding = embeddingClient.embed(query);
        
        // 2. 构建搜索参数
        String searchParams = "{\"nprobe\": 10}";
        
        SearchParam searchParam = SearchParam.newBuilder()
            .withCollectionName(collectionName)
            .withMetricType(MetricType.L2)
            .withTopK(topK)
            .withVectors(toFloatList(queryEmbedding))
            .withVectorFieldName("embedding")
            .withExpr("project_id == '" + projectId.value() + "'")
            .withParams(searchParams)
            .build();
        
        // 3. 执行搜索
        R<SearchResults> response = milvusClient.search(searchParam);
        SearchResultsWrapper wrapper = new SearchResultsWrapper(response.getData().getResults());
        
        // 4. 转换结果
        return wrapper.getRowRecords().stream()
            .map(record -> new MemoryChunk(
                record.get("id").toString(),
                projectId,
                new ChapterId(record.get("chapter_id").toString()),
                record.get("text").toString(),
                toFloatArray(record.get("embedding")),
                parseMetadata(record.get("metadata").toString())
            ))
            .collect(Collectors.toList());
    }
}
```

---

#### 3.2.3 工作记忆实现

**存储**: PostgreSQL JSONB

**实现**:
```java
package ai.storyforge.infrastructure.persistence;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class WorkingStateRepositoryImpl implements WorkingStateRepository {
    
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    
    @Override
    public WorkingState get(NovelProjectId projectId) {
        String sql = "SELECT state FROM working_memory WHERE project_id = ?";
        
        try {
            String json = jdbcTemplate.queryForObject(sql, String.class, projectId.value());
            return objectMapper.readValue(json, WorkingState.class);
        } catch (EmptyResultDataAccessException e) {
            return WorkingState.empty(projectId);
        }
    }
    
    @Override
    public void save(NovelProjectId projectId, WorkingState state) {
        String sql = """
            INSERT INTO working_memory (project_id, state, updated_at)
            VALUES (?, ?::jsonb, NOW())
            ON CONFLICT (project_id)
            DO UPDATE SET state = ?::jsonb, updated_at = NOW()
            """;
        
        String json = objectMapper.writeValueAsString(state);
        jdbcTemplate.update(sql, projectId.value(), json, json);
    }
}
```

---

### 3.3 工具调用模块

#### 3.3.1 ToolExecutor

**实现**:
```java
package ai.storyforge.application.service;

import dev.langchain4j.agent.tool.Tool;
import dev.langchain4j.agent.tool.ToolSpecification;
import org.springframework.stereotype.Service;

@Service
public class ToolExecutor {
    
    private final ToolRegistry toolRegistry;
    private final McpClient mcpClient;
    
    public ToolResult execute(String toolName, ContextBundle context) {
        ToolCall call = new ToolCall(toolName, buildArguments(context), false);
        return execute(call, new ToolContext(context));
    }
    
    public ToolResult execute(ToolCall call, ToolContext context) {
        if (call.viaMcp()) {
            return executeWithMcp(call, context);
        }
        
        Tool<Object, Object> tool = toolRegistry.get(call.toolName());
        Object input = convertInput(call.arguments(), tool.inputType());
        Object output = tool.execute(input, context);
        
        return ToolResult.success(call.toolName(), output);
    }
    
    private ToolResult executeWithMcp(ToolCall call, ToolContext context) {
        return mcpClient.callTool(call.toolName(), call.arguments());
    }
}
```

---

#### 3.3.2 CharacterArcPlanner 工具

**实现**:
```java
package ai.storyforge.infrastructure.tool;

import dev.langchain4j.agent.tool.Tool;
import org.springframework.stereotype.Component;

@Component
public class CharacterArcPlanner implements Tool<CharacterArcInput, CharacterArcOutput> {
    
    private final ChatLanguageModel chatModel;
    
    @Override
    public String name() {
        return "character_arc_planner";
    }
    
    @Override
    public String description() {
        return "分析角色的成长轨迹，规划起点-转折-终点弧光";
    }
    
    @Override
    public Class<CharacterArcInput> inputType() {
        return CharacterArcInput.class;
    }
    
    @Override
    public CharacterArcOutput execute(CharacterArcInput input, ToolContext context) {
        // 1. 提取角色相关章节
        List<Chapter> chapters = input.chapters();
        
        // 2. 构建分析 Prompt
        String prompt = buildAnalysisPrompt(input.characterName(), chapters);
        
        // 3. 调用模型分析
        String analysis = chatModel.generate(prompt);
        
        // 4. 解析结果
        return parseAnalysisResult(analysis);
    }
    
    private String buildAnalysisPrompt(String characterName, List<Chapter> chapters) {
        return """
            请分析角色"%s"的弧光轨迹，包括：
            1. 目标变化：角色的目标如何演变
            2. 冲突升级：角色面临的冲突如何升级
            3. 信念转变：角色的核心价值观如何变化
            
            章节内容：
            %s
            
            请以 JSON 格式输出分析结果。
            """.formatted(characterName, formatChapters(chapters));
    }
}
```

---

### 3.4 模型网关模块

#### 3.4.1 ModelGateway

**实现**:
```java
package ai.storyforge.infrastructure.model;

import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.chat.StreamingChatLanguageModel;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

@Service
public class AdaptiveModelGateway implements ModelGateway {
    
    private final List<ModelAdapter> adapters;
    private final CostTracker costTracker;
    private final ModelRouter modelRouter;
    
    @Override
    public Flux<ModelChunk> chatStream(ModelRequest request, RoutingPolicy policy) {
        ModelAdapter adapter = modelRouter.selectModel(request.intent(), policy);
        
        return Flux.create(emitter -> {
            try {
                adapter.chatStream(request)
                    .handlers()
                    .onPartialResponse(token -> {
                        emitter.next(new ModelChunk(token, false));
                    })
                    .onCompleteResponse(response -> {
                        // 记录成本
                        costTracker.record(adapter.name(), response.tokenCount());
                        emitter.next(new ModelChunk("", true));
                        emitter.complete();
                    })
                    .onError(error -> {
                        // Fallback
                        log.warn("Model {} failed, trying fallback", adapter.name());
                        tryFallback(request, policy, emitter);
                    })
                    .execute();
            } catch (Exception e) {
                emitter.error(e);
            }
        });
    }
    
    private void tryFallback(ModelRequest request, RoutingPolicy policy, FluxSink<ModelChunk> emitter) {
        List<ModelAdapter> fallbackChain = modelRouter.getFallbackChain(policy);
        
        for (ModelAdapter fallback : fallbackChain) {
            try {
                fallback.chatStream(request)
                    .handlers()
                    .onPartialResponse(token -> emitter.next(new ModelChunk(token, false)))
                    .onCompleteResponse(response -> {
                        costTracker.record(fallback.name(), response.tokenCount());
                        emitter.next(new ModelChunk("", true));
                        emitter.complete();
                    })
                    .onError(emitter::error)
                    .execute();
                return;
            } catch (Exception e) {
                log.warn("Fallback model {} also failed", fallback.name());
            }
        }
        
        emitter.error(new NoModelAvailableException("All models failed"));
    }
}
```

---

#### 3.4.2 CostTracker

**实现**:
```java
package ai.storyforge.infrastructure.model;

import org.springframework.stereotype.Service;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class CostTracker {
    
    private final ConcurrentHashMap<LocalDate, BigDecimal> dailyCosts = new ConcurrentHashMap<>();
    
    private final Map<String, BigDecimal> costPerModel = Map.of(
        "glm-4-flash", new BigDecimal("0.00001"),
        "glm-4.5-flash", new BigDecimal("0.000008")
    );
    
    public void record(String modelName, int tokenCount) {
        BigDecimal costPer1k = costPerModel.getOrDefault(modelName, BigDecimal.ZERO);
        BigDecimal cost = costPer1k.multiply(BigDecimal.valueOf(tokenCount / 1000.0));
        
        LocalDate today = LocalDate.now();
        dailyCosts.merge(today, cost, BigDecimal::add);
        
        log.info("Model call: model={}, tokens={}, cost=${}", modelName, tokenCount, cost);
    }
    
    public BigDecimal getTodayCost() {
        return dailyCosts.getOrDefault(LocalDate.now(), BigDecimal.ZERO);
    }
    
    public void checkBudget(BigDecimal dailyLimit) {
        BigDecimal todayCost = getTodayCost();
        if (todayCost.compareTo(dailyLimit) >= 0) {
            throw new BudgetExceededException("Daily budget exceeded: $" + todayCost);
        }
    }
}
```

---

### 3.5 MCP 服务模块

#### 3.5.1 MCP Server

**实现**:
```java
package ai.storyforge.infrastructure.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import java.io.*;

@Service
public class StdioMcpServer {
    
    private final ObjectMapper objectMapper;
    private final Map<String, McpMethodHandler> handlers;
    
    public void start() throws Exception {
        try (BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
             BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out))) {
            
            String line;
            while ((line = in.readLine()) != null) {
                JsonNode request = objectMapper.readTree(line);
                JsonNode response = handleRequest(request);
                
                out.write(objectMapper.writeValueAsString(response));
                out.newLine();
                out.flush();
            }
        }
    }
    
    private JsonNode handleRequest(JsonNode request) {
        String method = request.path("method").asText();
        JsonNode id = request.path("id");
        JsonNode params = request.path("params");
        
        try {
            McpMethodHandler handler = handlers.get(method);
            if (handler == null) {
                return createErrorResponse(id, -32601, "Method not found");
            }
            
            JsonNode result = handler.handle(params);
            return createSuccessResponse(id, result);
            
        } catch (Exception e) {
            return createErrorResponse(id, -32603, "Internal error: " + e.getMessage());
        }
    }
    
    private JsonNode createSuccessResponse(JsonNode id, JsonNode result) {
        return objectMapper.createObjectNode()
            .put("jsonrpc", "2.0")
            .set("id", id)
            .set("result", result);
    }
    
    private JsonNode createErrorResponse(JsonNode id, int code, String message) {
        return objectMapper.createObjectNode()
            .put("jsonrpc", "2.0")
            .set("id", id)
            .set("error", objectMapper.createObjectNode()
                .put("code", code)
                .put("message", message));
    }
}
```

---

## 4. 数据库设计

### 4.1 PostgreSQL 表结构

#### 4.1.1 working_memory 表

```sql
CREATE TABLE working_memory (
    project_id VARCHAR(64) PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_working_memory_updated_at ON working_memory(updated_at);
```

#### 4.1.2 novel_projects 表

```sql
CREATE TABLE novel_projects (
    project_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    author VARCHAR(128),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.3 chapters 表

```sql
CREATE TABLE chapters (
    chapter_id VARCHAR(64) PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL REFERENCES novel_projects(project_id),
    chapter_number INT NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(project_id, chapter_number)
);

CREATE INDEX idx_chapters_project_id ON chapters(project_id);
```

#### 4.1.4 cost_records 表

```sql
CREATE TABLE cost_records (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(64),
    model_name VARCHAR(64) NOT NULL,
    token_count INT NOT NULL,
    cost_usd DECIMAL(10, 6) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cost_records_created_at ON cost_records(created_at);
CREATE INDEX idx_cost_records_project_id ON cost_records(project_id);
```

---

### 4.2 Milvus Collection 设计

#### 4.2.1 novel_chunks Collection

```python
from pymilvus import CollectionSchema, FieldSchema, DataType

fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
    FieldSchema(name="project_id", dtype=DataType.VARCHAR, max_length=64),
    FieldSchema(name="chapter_id", dtype=DataType.VARCHAR, max_length=64),
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
    FieldSchema(name="metadata", dtype=DataType.JSON)
]

schema = CollectionSchema(fields=fields, description="Novel chunks for RAG")
collection = Collection(name="novel_chunks", schema=schema)

# 创建索引
index_params = {
    "metric_type": "L2",
    "index_type": "IVF_FLAT",
    "params": {"nlist": 1024}
}
collection.create_index(field_name="embedding", index_params=index_params)
```

---

### 4.3 Redis 数据结构

#### 4.3.1 短期记忆

```
Key: storyforge:shortterm:{project_id}
Type: List
Value: [
  {"turnId": "turn_001", "role": "user", "content": "...", "timestamp": "..."},
  {"turnId": "turn_002", "role": "assistant", "content": "...", "timestamp": "..."}
]
TTL: 24 hours
```

---

## 5. API 设计

### 5.1 REST API

#### 5.1.1 对话接口

**POST /api/v1/chat**

请求:
```json
{
  "projectId": "novel_123",
  "text": "帮我分析张伟是否扁平",
  "context": {}
}
```

响应（SSE）:
```
data: {"type":"info","content":"Intent detected: ANALYZE"}

data: {"type":"token","content":"根据"}

data: {"type":"token","content":"分析"}

data: {"type":"done"}
```

---

#### 5.1.2 项目管理接口

**POST /api/v1/projects**

请求:
```json
{
  "title": "我的科幻小说",
  "author": "张三"
}
```

响应:
```json
{
  "projectId": "novel_123",
  "title": "我的科幻小说",
  "author": "张三",
  "createdAt": "2026-04-02T10:00:00Z"
}
```

---

#### 5.1.3 章节管理接口

**POST /api/v1/projects/{projectId}/chapters**

请求:
```json
{
  "chapterNumber": 1,
  "title": "开端",
  "content": "第一章内容..."
}
```

响应:
```json
{
  "chapterId": "chapter_001",
  "projectId": "novel_123",
  "chapterNumber": 1,
  "title": "开端",
  "createdAt": "2026-04-02T10:00:00Z"
}
```

---

### 5.2 MCP API

#### 5.2.1 列出工具

**请求**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/list"
}
```

**响应**:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "tools": [
      {
        "name": "character_arc_planner",
        "description": "分析角色的成长轨迹"
      },
      {
        "name": "plot_gap_detector",
        "description": "检测情节漏洞"
      }
    ]
  }
}
```

---

## 6. 部署方案

### 6.1 Docker Compose

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
      - REDIS_HOST=redis
      - MILVUS_HOST=milvus
      - POSTGRES_HOST=postgres
    depends_on:
      - redis
      - milvus
      - postgres
    networks:
      - storyforge-network
  
  redis:
    image: redis:7.0-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - storyforge-network
  
  milvus:
    image: milvusdb/milvus:v2.3.4
    ports:
      - "19530:19530"
    volumes:
      - milvus-data:/var/lib/milvus
    networks:
      - storyforge-network
  
  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=storyforge
      - POSTGRES_USER=storyforge
      - POSTGRES_PASSWORD=storyforge123
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - storyforge-network

volumes:
  redis-data:
  milvus-data:
  postgres-data:

networks:
  storyforge-network:
    driver: bridge
```

---

### 6.2 配置文件

**application.yml**:
```yaml
spring:
  application:
    name: storyforge-ai
  
  datasource:
    url: jdbc:postgresql://${POSTGRES_HOST:localhost}:5432/storyforge
    username: storyforge
    password: ${POSTGRES_PASSWORD:storyforge123}
  
  redis:
    host: ${REDIS_HOST:localhost}
    port: 6379
  
  jackson:
    serialization:
      write-dates-as-timestamps: false

storyforge:
  memory:
    shortterm:
      window-size: 10
    
    longterm:
      milvus:
        host: ${MILVUS_HOST:localhost}
        port: 19530
        collection: novel_chunks
  
  model:
    zhipu:
      api-key: ${ZHIPU_API_KEY}
      base-url: https://open.bigmodel.cn/api/paas/v4
      model: glm-4-flash
    
    routing:
      default: glm-4-flash
      fallback:
        - glm-4.5-flash
    
    budget:
      daily-limit-usd: 1.0
      warn-threshold: 0.8

logging:
  level:
    ai.storyforge: DEBUG
    dev.langchain4j: INFO
  pattern:
    console: "[%X{traceId}] %d{yyyy-MM-dd HH:mm:ss} [%thread] %-5level %logger{36} - %msg%n"
```

---

## 7. 性能优化方案

### 7.1 向量检索优化

1. **索引优化**: 使用 IVF_FLAT 索引，nlist=1024
2. **批量检索**: 批量生成 embedding，减少网络开销
3. **缓存热门查询**: 使用 Redis 缓存热门查询结果

---

### 7.2 模型调用优化

1. **Prompt 精简**: 避免冗余，减少 token 数
2. **流式输出**: 使用 SSE，提升用户体验
3. **并发控制**: 使用虚拟线程，提升并发能力

---

### 7.3 数据库优化

1. **连接池**: 使用 HikariCP，合理配置连接数
2. **索引优化**: 为常用查询字段创建索引
3. **JSONB 查询优化**: 使用 GIN 索引

---

## 8. 监控与日志

### 8.1 日志规范

```
[traceId=abc123] 2026-04-02 10:30:00 [main] INFO  ai.storyforge.AgentOrchestrator - Intent detected: ANALYZE
[traceId=abc123] 2026-04-02 10:30:01 [main] INFO  ai.storyforge.ModelGateway - Model call: model=glm-4-flash, tokens=150, cost=$0.000015
```

---

### 8.2 指标收集

使用 Micrometer 收集指标：
- 模型调用次数
- Token 消耗总量
- 平均响应时间
- 错误率

---

## 9. 下一步

1. **分解任务列表**: 可执行的开发任务
2. **开始迭代 1**: MVP 实现
