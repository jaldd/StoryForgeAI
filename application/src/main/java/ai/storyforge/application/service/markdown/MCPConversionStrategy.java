package ai.storyforge.application.service.markdown;

import ai.storyforge.application.port.outbound.McpServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashMap;
import java.util.Map;

public class MCPConversionStrategy implements MarkdownConversionStrategy {
    
    private static final Logger log = LoggerFactory.getLogger(MCPConversionStrategy.class);
    private final McpServer mcpServer;

    public MCPConversionStrategy(McpServer mcpServer) {
        this.mcpServer = mcpServer;
    }

    @Override
    public String convertToMarkdown(String content, String fileName) {
        String lowerFileName = fileName.toLowerCase();
        
        // 如果已经是Markdown文件，直接返回
        if (lowerFileName.endsWith(".md")) {
            return content;
        }
        
        try {
            String fileType = getFileType(fileName);
            
            // 构建MCP工具调用参数
            Map<String, Object> parameters = new HashMap<>();
            parameters.put("content", content);
            parameters.put("file_type", fileType);
            
            // 调用MCP工具
            Map<String, Object> result = mcpServer.callTool("convert_to_markdown", parameters).join();
            
            if (result.containsKey("success") && (boolean) result.get("success")) {
                return (String) result.get("markdown");
            } else {
                log.warn("MCP conversion failed: {}", result.get("error"));
                // 失败时回退到简单转换
                return new SimpleConversionStrategy().convertToMarkdown(content, fileName);
            }
        } catch (Exception e) {
            log.warn("Failed to convert with MCP: {}", e.getMessage());
            // 失败时回退到简单转换
            return new SimpleConversionStrategy().convertToMarkdown(content, fileName);
        }
    }

    private String getFileType(String fileName) {
        String lowerFileName = fileName.toLowerCase();
        
        if (lowerFileName.endsWith(".txt")) {
            return "纯文本";
        }
        if (lowerFileName.endsWith(".html")) {
            return "HTML";
        }
        if (lowerFileName.endsWith(".json")) {
            return "JSON";
        }
        
        return "文本";
    }

    @Override
    public String getStrategyName() {
        return "mcp";
    }
}