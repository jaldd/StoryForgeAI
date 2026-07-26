package ai.storyforge.application.service.markdown;

import ai.storyforge.application.config.ProjectProperties;
import ai.storyforge.application.port.outbound.ModelGateway;
import ai.storyforge.application.port.outbound.McpServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

@Service
public class MarkdownConversionStrategyFactory {
    
    private static final Logger log = LoggerFactory.getLogger(MarkdownConversionStrategyFactory.class);
    private final Map<String, MarkdownConversionStrategy> strategies = new HashMap<>();
    private final String defaultStrategyName;

    public MarkdownConversionStrategyFactory(ProjectProperties projectProperties, ModelGateway modelGateway, McpServer mcpServer) {
        // 注册所有策略
        strategies.put("simple", new SimpleConversionStrategy());
        strategies.put("llm", new LLMConversionStrategy(modelGateway));
        strategies.put("markitdown-mcp", new MarkItDownMCPConversionStrategy());
        strategies.put("mcp", new MCPConversionStrategy(mcpServer));
        
        // 从配置中获取默认策略，默认为markitdown-mcp
        this.defaultStrategyName = projectProperties.getMarkdownConversionStrategy() != null 
            ? projectProperties.getMarkdownConversionStrategy() 
            : "markitdown-mcp";
        
        log.info("Markdown conversion strategy factory initialized with default strategy: {}", defaultStrategyName);
    }

    /**
     * 获取默认策略
     * @return 默认策略
     */
    public MarkdownConversionStrategy getDefaultStrategy() {
        return getStrategy(defaultStrategyName);
    }

    /**
     * 根据名称获取策略
     * @param strategyName 策略名称
     * @return 策略实例
     */
    public MarkdownConversionStrategy getStrategy(String strategyName) {
        MarkdownConversionStrategy strategy = strategies.get(strategyName);
        if (strategy == null) {
            log.warn("Unknown markdown conversion strategy: {}, falling back to simple strategy", strategyName);
            return strategies.get("simple");
        }
        return strategy;
    }

    /**
     * 获取所有可用策略
     * @return 策略名称列表
     */
    public Map<String, MarkdownConversionStrategy> getAvailableStrategies() {
        return strategies;
    }
}