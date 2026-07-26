package ai.storyforge.application.service.markdown;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SimpleConversionStrategy implements MarkdownConversionStrategy {
    
    private static final Logger log = LoggerFactory.getLogger(SimpleConversionStrategy.class);

    @Override
    public String convertToMarkdown(String content, String fileName) {
        String lowerFileName = fileName.toLowerCase();
        
        // 如果已经是Markdown文件，直接返回
        if (lowerFileName.endsWith(".md")) {
            return content;
        }
        
        // 对于纯文本文件，添加Markdown格式
        if (lowerFileName.endsWith(".txt")) {
            return content;
        }
        
        // 对于HTML文件，简单转换为Markdown
        if (lowerFileName.endsWith(".html")) {
            // 移除HTML标签，保留内容
            content = content.replaceAll("<[^>]*>", "");
            // 替换换行符
            content = content.replaceAll("\\s+\\n\\s+", "\n\n");
            return content;
        }
        
        // 对于JSON文件，格式化显示
        if (lowerFileName.endsWith(".json")) {
            // 添加代码块
            return "```json\n" + content + "\n```";
        }
        
        return content;
    }

    @Override
    public String getStrategyName() {
        return "simple";
    }
}