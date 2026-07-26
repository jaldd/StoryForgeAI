package ai.storyforge.infrastructure.mcp;

import ai.storyforge.application.port.outbound.ModelGateway;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

@Component
public class MarkdownConversionTool implements McpTool {
    
    private static final Logger log = LoggerFactory.getLogger(MarkdownConversionTool.class);
    private final ModelGateway modelGateway;

    public MarkdownConversionTool(ModelGateway modelGateway) {
        this.modelGateway = modelGateway;
    }

    @Override
    public String getName() {
        return "convert_to_markdown";
    }

    @Override
    public String getDescription() {
        return "将各种文件格式转换为Markdown格式";
    }

    @Override
    public CompletableFuture<Map<String, Object>> execute(Map<String, Object> parameters) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                String content = (String) parameters.get("content");
                String fileType = (String) parameters.get("file_type");

                if (content == null || fileType == null) {
                    Map<String, Object> errorResult = new HashMap<>();
                    errorResult.put("error", "Missing required parameters: content and file_type");
                    return errorResult;
                }

                log.info("Converting {} content to Markdown", fileType);
                String markdownContent = convertToMarkdown(content, fileType);

                Map<String, Object> result = new HashMap<>();
                result.put("markdown", markdownContent);
                result.put("success", true);
                return result;
            } catch (Exception e) {
                log.error("Error converting to Markdown", e);
                Map<String, Object> errorResult = new HashMap<>();
                errorResult.put("error", e.getMessage());
                errorResult.put("success", false);
                return errorResult;
            }
        });
    }

    @Override
    public Map<String, Object> getSchema() {
        Map<String, Object> schema = new HashMap<>();
        schema.put("name", getName());
        schema.put("description", getDescription());

        Map<String, Object> parameters = new HashMap<>();
        parameters.put("type", "object");

        Map<String, Object> properties = new HashMap<>();

        Map<String, Object> contentProperty = new HashMap<>();
        contentProperty.put("type", "string");
        contentProperty.put("description", "要转换的文件内容");
        properties.put("content", contentProperty);

        Map<String, Object> fileTypeProperty = new HashMap<>();
        fileTypeProperty.put("type", "string");
        fileTypeProperty.put("description", "文件类型，如txt、html、json等");
        properties.put("file_type", fileTypeProperty);

        parameters.put("properties", properties);

        schema.put("parameters", parameters);
        return schema;
    }

    private String convertToMarkdown(String content, String fileType) {
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
    }
}