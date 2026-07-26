package ai.storyforge.infrastructure.mcp;

import ai.storyforge.application.port.outbound.McpServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

//@Component
public class McpServerImpl implements McpServer {
    
    private static final Logger log = LoggerFactory.getLogger(McpServerImpl.class);
    private final Map<String, McpTool> tools = new HashMap<>();

    @Override
    public void registerTool(Object tool) {
        if (tool instanceof McpTool) {
            McpTool mcpTool = (McpTool) tool;
            tools.put(mcpTool.getName(), mcpTool);
            log.info("Registered MCP tool: {}", mcpTool.getName());
        } else {
            log.warn("Invalid tool type: {}", tool.getClass().getName());
        }
    }

    public void registerTool(McpTool tool) {
        tools.put(tool.getName(), tool);
        log.info("Registered MCP tool: {}", tool.getName());
    }

    @Override
    public CompletableFuture<Map<String, Object>> callTool(String toolName, Map<String, Object> parameters) {
        McpTool tool = tools.get(toolName);
        if (tool == null) {
            log.warn("Tool not found: {}", toolName);
            CompletableFuture<Map<String, Object>> future = new CompletableFuture<>();
            Map<String, Object> errorResult = new HashMap<>();
            errorResult.put("error", "Tool not found");
            future.complete(errorResult);
            return future;
        }

        log.info("Calling MCP tool: {}", toolName);
        return tool.execute(parameters);
    }

    public Map<String, McpTool> getTools() {
        return tools;
    }

    @Override
    public Map<String, Object> getToolSchema(String toolName) {
        McpTool tool = tools.get(toolName);
        if (tool == null) {
            return null;
        }
        return tool.getSchema();
    }

    @Override
    public Map<String, Map<String, Object>> getAllToolSchemas() {
        Map<String, Map<String, Object>> schemas = new HashMap<>();
        for (Map.Entry<String, McpTool> entry : tools.entrySet()) {
            schemas.put(entry.getKey(), entry.getValue().getSchema());
        }
        return schemas;
    }
}