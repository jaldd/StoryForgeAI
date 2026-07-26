package ai.storyforge.infrastructure.config;

import ai.storyforge.application.port.outbound.McpServer;
import ai.storyforge.infrastructure.mcp.McpServerImpl;
import ai.storyforge.infrastructure.mcp.MarkdownConversionTool;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class McpConfig {

    @Bean
    public McpServer mcpServer(MarkdownConversionTool markdownConversionTool) {
        McpServerImpl mcpServer = new McpServerImpl();
        mcpServer.registerTool(markdownConversionTool);
        return mcpServer;
    }
}