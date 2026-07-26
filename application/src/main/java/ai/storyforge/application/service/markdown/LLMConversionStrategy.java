package ai.storyforge.application.service.markdown;

import ai.storyforge.application.port.outbound.ModelGateway;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class LLMConversionStrategy implements MarkdownConversionStrategy {
    
    private static final Logger log = LoggerFactory.getLogger(LLMConversionStrategy.class);
    private final ModelGateway modelGateway;

    public LLMConversionStrategy(ModelGateway modelGateway) {
        this.modelGateway = modelGateway;
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
            
            String prompt = String.format("""
                请将以下%s文件内容转换为标准的Markdown格式：
                
                文件内容：
                %s
                
                转换要求：
                1. 保持内容的完整性和准确性
                2. 格式化为标准的Markdown
                3. 对于代码或结构化数据，使用适当的代码块
                4. 对于列表、标题等内容，使用正确的Markdown语法
                5. 保持原文的段落结构和逻辑关系
                
                请直接返回转换后的Markdown内容，不要添加任何额外的解释或说明。
                """, fileType, content);
            
            return modelGateway.chat(prompt);
        } catch (Exception e) {
            log.warn("Failed to convert with LLM: {}", e.getMessage());
            // 失败时返回原文
            return content;
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
        return "llm";
    }
}