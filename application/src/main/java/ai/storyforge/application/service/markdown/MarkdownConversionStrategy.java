package ai.storyforge.application.service.markdown;

public interface MarkdownConversionStrategy {
    /**
     * 将文件内容转换为Markdown格式
     * @param content 文件内容
     * @param fileName 文件名
     * @return 转换后的Markdown内容
     */
    String convertToMarkdown(String content, String fileName);
    
    /**
     * 获取策略名称
     * @return 策略名称
     */
    String getStrategyName();
}