package ai.storyforge.application.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "storyforge.project")
public class ProjectProperties {
    
    private String defaultProjectId;
    private String defaultTitle;
    private String defaultAuthor;
    private String documentsPath;
    private String markdownConversionStrategy;

    // Getters and setters
    public String getDefaultProjectId() {
        return defaultProjectId;
    }

    public void setDefaultProjectId(String defaultProjectId) {
        this.defaultProjectId = defaultProjectId;
    }

    public String getDefaultTitle() {
        return defaultTitle;
    }

    public void setDefaultTitle(String defaultTitle) {
        this.defaultTitle = defaultTitle;
    }

    public String getDefaultAuthor() {
        return defaultAuthor;
    }

    public void setDefaultAuthor(String defaultAuthor) {
        this.defaultAuthor = defaultAuthor;
    }

    public String getDocumentsPath() {
        return documentsPath;
    }

    public void setDocumentsPath(String documentsPath) {
        this.documentsPath = documentsPath;
    }

    public String getMarkdownConversionStrategy() {
        return markdownConversionStrategy;
    }

    public void setMarkdownConversionStrategy(String markdownConversionStrategy) {
        this.markdownConversionStrategy = markdownConversionStrategy;
    }
}
