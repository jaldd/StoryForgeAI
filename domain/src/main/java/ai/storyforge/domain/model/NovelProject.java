package ai.storyforge.domain.model;

import ai.storyforge.domain.model.vo.NovelProjectId;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import java.time.LocalDateTime;

@Entity
public class NovelProject {

    @EmbeddedId
    private NovelProjectId projectId;
    private String title;
    private String author;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    protected NovelProject() {}

    public NovelProject(NovelProjectId projectId, String title, String author) {
        this.projectId = projectId;
        this.title = title;
        this.author = author;
        this.createdAt = LocalDateTime.now();
        this.updatedAt = LocalDateTime.now();
    }

    public NovelProjectId getProjectId() { return projectId; }
    public String getTitle() { return title; }
    public String getAuthor() { return author; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
}
