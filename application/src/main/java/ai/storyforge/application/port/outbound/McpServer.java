package ai.storyforge.application.port.outbound;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

public interface McpServer {
    void registerTool(Object tool);
    CompletableFuture<Map<String, Object>> callTool(String toolName, Map<String, Object> parameters);
    Map<String, Object> getToolSchema(String toolName);
    Map<String, Map<String, Object>> getAllToolSchemas();
}