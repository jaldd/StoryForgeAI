package ai.storyforge.application.service.markdown;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

public class MarkItDownMCPConversionStrategy implements MarkdownConversionStrategy {
    
    private static final Logger log = LoggerFactory.getLogger(MarkItDownMCPConversionStrategy.class);

    @Override
    public String convertToMarkdown(String content, String fileName) {
        String lowerFileName = fileName.toLowerCase();
        
        // 如果已经是Markdown文件，直接返回
        if (lowerFileName.endsWith(".md")) {
            return content;
        }
        
        try {
            // 检查markitdown是否安装
            if (!isMarkItDownInstalled()) {
                log.warn("MarkItDown is not installed, falling back to simple conversion");
                return new SimpleConversionStrategy().convertToMarkdown(content, fileName);
            }
            
            // 调用markitdown命令行工具
            ProcessBuilder processBuilder = new ProcessBuilder("python", "-m", "markitdown", "--stdin");
            processBuilder.redirectErrorStream(true);
            Process process = processBuilder.start();
            
            // 写入内容到标准输入
            try (OutputStream os = process.getOutputStream()) {
                os.write(content.getBytes(StandardCharsets.UTF_8));
                os.flush();
            }
            
            // 读取标准输出
            StringBuilder output = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    output.append(line).append("\n");
                }
            }
            
            // 等待进程完成
            int exitCode = process.waitFor();
            
            if (exitCode == 0) {
                return output.toString();
            } else {
                log.warn("MarkItDown conversion failed with exit code: {}", exitCode);
                return new SimpleConversionStrategy().convertToMarkdown(content, fileName);
            }
        } catch (Exception e) {
            log.warn("Failed to convert with MarkItDown-MCP: {}", e.getMessage());
            // 失败时回退到简单转换
            return new SimpleConversionStrategy().convertToMarkdown(content, fileName);
        }
    }

    private boolean isMarkItDownInstalled() {
        try {
            ProcessBuilder processBuilder = new ProcessBuilder("python", "-m", "markitdown", "--version");
            Process process = processBuilder.start();
            int exitCode = process.waitFor();
            return exitCode == 0;
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public String getStrategyName() {
        return "markitdown-mcp";
    }
}