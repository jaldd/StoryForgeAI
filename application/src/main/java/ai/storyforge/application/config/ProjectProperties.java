package ai.storyforge.application.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "storyforge.project")
public class ProjectProperties {

    private String defaultProjectId = "550e8400-e29b-41d4-a716-446655440000";
    private String defaultTitle = "默认小说项目";
    private String defaultAuthor = "作者";
    private String documentsPath = "./documents";

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
}
