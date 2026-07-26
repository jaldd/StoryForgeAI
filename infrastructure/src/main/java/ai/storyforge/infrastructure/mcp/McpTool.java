package ai.storyforge.infrastructure.mcp;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

public interface McpTool {
    /**
     * 获取工具名称
     * @return 工具名称
     */
    String getName();

    /**
     * 获取工具描述
     * @return 工具描述
     */
    String getDescription();

    /**
     * 执行工具
     * @param parameters 工具参数
     * @return 执行结果
     */
    CompletableFuture<Map<String, Object>> execute(Map<String, Object> parameters);

    /**
     * 获取工具 schema
     * @return 工具 schema
     */
    Map<String, Object> getSchema();
}