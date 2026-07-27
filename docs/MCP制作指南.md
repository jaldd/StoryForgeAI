# MCP (Model Context Protocol) 制作指南

## 什么是MCP

MCP（Model Context Protocol）是一种协议，用于连接大语言模型与外部工具和服务。它定义了模型如何与外部工具交互的标准方式，使模型能够通过标准化的接口调用外部功能。

## MCP的核心概念

1. **工具（Tool）**：执行特定功能的组件，如文件转换、数据查询等
2. **工具注册**：将工具注册到MCP服务器
3. **工具调用**：模型通过标准格式请求调用工具
4. **结果处理**：模型处理工具返回的结果

## MCP实现步骤

### 步骤1：创建MCP服务器

MCP服务器负责管理和执行工具。

```java
public class McpServer {
    private final Map<String, McpTool> tools = new HashMap<>();

    public void registerTool(McpTool tool) {
        tools.put(tool.getName(), tool);
    }

    public CompletableFuture<Map<String, Object>> callTool(String toolName, Map<String, Object> parameters) {
        McpTool tool = tools.get(toolName);
        if (tool == null) {
            // 处理工具不存在的情况
        }
        return tool.execute(parameters);
    }
}
```

### 步骤2：定义工具接口

工具接口定义了所有MCP工具必须实现的方法。

```java
public interface McpTool {
    String getName();
    String getDescription();
    CompletableFuture<Map<String, Object>> execute(Map<String, Object> parameters);
    Map<String, Object> getSchema();
}
```

### 步骤3：实现具体工具

创建具体的工具实现，如Markdown转换工具。

```java
public class MarkdownConversionTool implements McpTool {
    @Override
    public String getName() {
        return "convert_to_markdown";
    }

    @Override
    public CompletableFuture<Map<String, Object>> execute(Map<String, Object> parameters) {
        // 实现转换逻辑
    }
}
```

### 步骤4：注册工具

将工具注册到MCP服务器。

```java
@Configuration
public class McpConfig {
    @Bean
    public McpServer mcpServer(MarkdownConversionTool markdownConversionTool) {
        McpServer mcpServer = new McpServer();
        mcpServer.registerTool(markdownConversionTool);
        return mcpServer;
    }
}
```

### 步骤5：使用MCP工具

通过MCP服务器调用工具。

```java
Map<String, Object> parameters = new HashMap<>();
parameters.put("content", fileContent);
parameters.put("file_type", "html");
Map<String, Object> result = mcpServer.callTool("convert_to_markdown", parameters).join();
String markdown = (String) result.get("markdown");
```

## 我们的MCP实现

### 1. 核心组件

- **McpServer**：MCP服务器，管理工具注册和调用
- **McpTool**：工具接口，定义工具的基本方法
- **MarkdownConversionTool**：Markdown转换工具，使用LLM将各种文件格式转换为Markdown
- **MCPConversionStrategy**：使用MCP的转换策略

### 2. 工具调用流程

1. 客户端构建工具调用参数
2. 调用McpServer的callTool方法
3. McpServer找到对应的工具并执行
4. 工具执行并返回结果
5. McpServer将结果返回给客户端

### 3. 配置和使用

在配置文件中设置默认转换策略：

```yaml
storyforge:
  project:
    markdown-conversion-strategy: mcp  # 使用MCP策略
```

## MCP最佳实践

### 1. 工具设计

- **单一职责**：每个工具应该只负责一个特定功能
- **清晰的参数**：参数应该明确且易于理解
- **详细的描述**：工具应该有详细的描述和使用说明
- **错误处理**：工具应该优雅处理错误情况

### 2. 性能优化

- **异步执行**：使用CompletableFuture实现异步执行
- **缓存机制**：对于重复的请求可以考虑缓存
- **超时处理**：设置合理的超时时间

### 3. 安全性

- **参数验证**：验证输入参数的合法性
- **权限控制**：限制工具的访问权限
- **输入 sanitization**：清理输入内容，防止注入攻击

## MCP vs 直接API调用

| 特性 | MCP | 直接API调用 |
|------|-----|------------|
| 标准化 | ✅ 标准接口 | ❌ 自定义接口 |
| 可扩展性 | ✅ 易于添加新工具 | ❌ 需要修改代码 |
| 模型理解 | ✅ 模型可以理解工具 | ❌ 模型无法理解 |
| 维护性 | ✅ 集中管理工具 | ❌ 分散的调用逻辑 |

## 示例：使用MCP转换HTML为Markdown

### 输入
```html
<h1>标题</h1>
<p>这是一个段落。</p>
<ul>
  <li>项目 1</li>
  <li>项目 2</li>
</ul>
```

### 工具调用
```java
Map<String, Object> parameters = new HashMap<>();
parameters.put("content", htmlContent);
parameters.put("file_type", "HTML");
Map<String, Object> result = mcpServer.callTool("convert_to_markdown", parameters).join();
```

### 输出
```markdown
# 标题

这是一个段落。

- 项目 1
- 项目 2
```

## 总结

MCP是一种强大的协议，它使大语言模型能够与外部工具和服务进行标准化的交互。通过实现MCP，我们可以：

1. 扩展模型的能力，使其能够执行复杂的任务
2. 提供标准化的工具接口，便于模型理解和使用
3. 集中管理工具，提高代码的可维护性
4. 实现工具的动态发现和调用

MCP的实现并不复杂，只需要几个核心组件和遵循一定的规范即可。通过本文的指南，您应该能够理解如何创建和使用MCP工具，为您的AI应用添加更多功能。